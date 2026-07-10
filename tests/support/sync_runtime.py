"""Make background work deterministic for headless flow tests.

Two things fight determinism in the wizard:

1. Screens spawn ``threading.Thread(...).start()`` for provider calls and
   the disc-drive poller. We replace ``threading.Thread`` with a thread that
   runs its target *synchronously* on ``start()`` — except the named drive
   poller, whose ``while not stop.wait(...)`` loop would spin forever; that
   one is turned into a no-op (its first poll already ran inline).

2. Real ``ft.Control.update()`` asserts the control is attached to a live
   page. Since our controls are never mounted, we patch the base
   ``Control.update`` to a no-op for the duration of a test.

Both are installed via the ``sync_runtime`` pytest fixture (see conftest).
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

import flet as ft

# Thread names that must NOT run synchronously because their target loops
# until an Event is set (which never happens under a sync thread model).
_NONBLOCKING_THREAD_PREFIXES = ("riplex-drive-poll",)


class SyncThread:
    """A ``threading.Thread`` replacement that runs its target inline.

    ``start()`` executes ``target(*args, **kwargs)`` immediately on the
    calling thread so provider calls / navigation complete before control
    returns to the test driver. Poller-style loop threads (identified by
    name) are skipped so they cannot block.
    """

    def __init__(
        self,
        group: Any = None,
        target: Callable[..., Any] | None = None,
        name: str | None = None,
        args: tuple = (),
        kwargs: dict | None = None,
        *,
        daemon: bool | None = None,
    ) -> None:
        self._target = target
        self._name = name or ""
        self._args = args
        self._kwargs = kwargs or {}
        self.daemon = daemon
        self._ran = False

    # threading.Thread API surface the screens rely on -------------------
    @property
    def name(self) -> str:
        return self._name

    def start(self) -> None:
        if any(self._name.startswith(p) for p in _NONBLOCKING_THREAD_PREFIXES):
            return
        self.run()

    def run(self) -> None:
        if self._target is not None:
            self._target(*self._args, **self._kwargs)
        self._ran = True

    def join(self, timeout: float | None = None) -> None:
        return None

    def is_alive(self) -> bool:
        return False


def install(monkeypatch) -> None:
    """Patch threading + Flet control updates for synchronous, headless runs.

    Call from a pytest fixture with the test's ``monkeypatch`` so everything
    is automatically undone at test teardown.
    """
    monkeypatch.setattr(threading, "Thread", SyncThread)

    # Screens sleep briefly before some navigations (e.g. progress waits 1s so
    # the final frame is visible). Under sync execution that's dead time.
    monkeypatch.setattr(time, "sleep", lambda *_a, **_k: None)

    # Control.update() would raise "must be added to the page first" because
    # our controls are never mounted on a real page. Make it a no-op.
    monkeypatch.setattr(ft.Control, "update", lambda self: None, raising=False)
