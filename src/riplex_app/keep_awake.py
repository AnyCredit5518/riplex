"""Prevent the OS from sleeping/dimming the display during long operations.

Used as a context manager around long-running tasks (rips, large organize
runs) so the user can walk away without the app's UI render loop being
suspended by display sleep.
"""

from __future__ import annotations

import contextlib
import ctypes
import logging
import subprocess
import sys
from typing import Iterator

log = logging.getLogger(__name__)


# Windows SetThreadExecutionState flags
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002
_ES_AWAYMODE_REQUIRED = 0x00000040


def _windows_keep_awake_on(keep_display: bool) -> bool:
    flags = _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED
    if keep_display:
        flags |= _ES_DISPLAY_REQUIRED
    result = ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(flags))
    return result != 0


def _windows_keep_awake_off() -> None:
    ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(_ES_CONTINUOUS))


@contextlib.contextmanager
def keep_awake(reason: str = "long-running task", keep_display: bool = True) -> Iterator[None]:
    """Prevent system/display sleep for the duration of the context.

    On Windows: uses SetThreadExecutionState.
    On macOS: spawns `caffeinate` and kills it on exit.
    On Linux/other: no-op (logged).

    Safe to nest and safe to call from any thread. Failures are logged but
    never raised — sleep prevention is best-effort and must not crash the app.
    """
    proc: subprocess.Popen | None = None
    active = False
    try:
        if sys.platform == "win32":
            if _windows_keep_awake_on(keep_display):
                active = True
                log.info("keep_awake: enabled (Windows) for %s", reason)
            else:
                log.warning("keep_awake: SetThreadExecutionState returned 0")
        elif sys.platform == "darwin":
            args = ["caffeinate", "-i", "-s"]
            if keep_display:
                args.append("-d")
            try:
                proc = subprocess.Popen(args)
                active = True
                log.info("keep_awake: enabled (macOS caffeinate) for %s", reason)
            except FileNotFoundError:
                log.warning("keep_awake: caffeinate not available")
        else:
            log.info("keep_awake: no-op on platform %s for %s", sys.platform, reason)
        yield
    except Exception:
        log.exception("keep_awake: error while enabling")
        yield
    finally:
        try:
            if sys.platform == "win32" and active:
                _windows_keep_awake_off()
                log.info("keep_awake: disabled (Windows)")
            elif proc is not None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                log.info("keep_awake: disabled (macOS caffeinate)")
        except Exception:
            log.exception("keep_awake: error while disabling")
