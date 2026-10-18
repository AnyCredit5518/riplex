"""Single-flight launching for GUI background operations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
import threading
import time
from typing import Any


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScreenLease:
    """Identity of the screen visit that launched background work."""

    screen_name: str | None
    epoch: int | None


def capture_screen_lease(app: Any) -> ScreenLease:
    return ScreenLease(
        screen_name=getattr(app, "_current_screen_name", None),
        epoch=getattr(app, "_navigation_epoch", None),
    )


def screen_lease_is_current(app: Any, lease: ScreenLease | None) -> bool:
    """Return whether ``app`` is still on the visit represented by ``lease``."""
    if lease is None:
        return True
    current_epoch = getattr(app, "_navigation_epoch", None)
    current_screen = getattr(app, "_current_screen_name", None)
    if lease.epoch is not None and current_epoch is not None:
        current = (
            current_epoch == lease.epoch
            and current_screen == lease.screen_name
        )
    else:
        current = current_screen is None or current_screen == lease.screen_name
    if not current:
        log.debug(
            "discarding stale screen completion: screen=%s epoch=%s; current=%s epoch=%s",
            lease.screen_name, lease.epoch, current_screen, current_epoch,
        )
    return current


def screen_operation_key(base: str, lease: ScreenLease) -> str:
    """Scope a cancellable operation to one logical screen visit."""
    if lease.epoch is None:
        return base
    return f"{base}:{lease.epoch}"


class BackgroundOperations:
    """Track keyed worker threads and reject overlapping launches."""

    def __init__(self) -> None:
        self._active: set[str] = set()
        self._lock = threading.Lock()

    def is_active(self, key: str) -> bool:
        with self._lock:
            return key in self._active

    def start(
        self,
        key: str,
        target: Callable[..., Any],
        *,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ) -> bool:
        """Start ``target`` unless another worker already owns ``key``."""
        with self._lock:
            if key in self._active:
                log.debug("background operation %s already active; ignoring duplicate", key)
                return False
            self._active.add(key)

        def _run() -> None:
            started_at = time.monotonic()
            log.debug("background operation %s started", key)
            try:
                target(*args, **(kwargs or {}))
            except Exception:
                log.exception("background operation %s failed", key)
                raise
            finally:
                with self._lock:
                    self._active.discard(key)
                log.debug("background operation %s finished (elapsed=%.3fs)",
                          key, time.monotonic() - started_at)

        try:
            thread = threading.Thread(
                target=_run,
                daemon=True,
                name=f"riplex-{key}",
            )
            thread.start()
        except BaseException:
            with self._lock:
                self._active.discard(key)
            raise
        return True


_runner_init_lock = threading.Lock()


def operations_for(app: Any) -> BackgroundOperations:
    """Return the operation registry owned by an app or test double."""
    with _runner_init_lock:
        runner = vars(app).get("_background_operations")
        if runner is None:
            runner = BackgroundOperations()
            app._background_operations = runner
        return runner


def start_background_once(
    app: Any,
    key: str,
    target: Callable[..., Any],
    *,
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
) -> bool:
    """Start one keyed worker for ``app`` and report whether it launched."""
    return operations_for(app).start(
        key,
        target,
        args=args,
        kwargs=kwargs,
    )