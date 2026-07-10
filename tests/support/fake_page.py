"""A headless stand-in for ``flet.Page`` plus control-tree helpers.

Screens build real ``flet`` controls but never attach to a live desktop
runtime in tests. ``FakePage`` implements only the Page attributes/methods
the screens and ``RiplexApp`` actually use, records ``update()`` calls, and
runs ``run_task`` coroutines synchronously so navigation that hops back onto
the event loop completes before the driver inspects the tree.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Iterator


class FakeWindow:
    """Stand-in for ``page.window`` — accepts arbitrary attribute writes."""

    def __init__(self) -> None:
        self.width: int | None = None
        self.height: int | None = None

    def __setattr__(self, name: str, value: Any) -> None:  # pragma: no cover - trivial
        object.__setattr__(self, name, value)


class FakePage:
    """Minimal ``ft.Page`` replacement for headless flow tests.

    Only the surface exercised by ``RiplexApp`` and the screens is
    implemented. Anything unexpected raises ``AttributeError`` loudly so a
    screen reaching for a new Page API is caught rather than silently no-op'd.
    """

    def __init__(self) -> None:
        self.title: str = ""
        self.theme_mode: Any = None
        self.padding: Any = None
        self.window = FakeWindow()
        self.controls: list[Any] = []
        self.overlay: list[Any] = []
        self.appbar: Any = None
        self.floating_action_button: Any = None
        self.on_error: Callable[[Any], Any] | None = None

        # Bookkeeping the driver / tests can assert on.
        self.update_count: int = 0
        self.dialogs: list[Any] = []
        self.errors: list[Any] = []

    # -- refresh ---------------------------------------------------------
    def update(self, *_controls: Any) -> None:
        self.update_count += 1

    # -- async hop back onto the "event loop" ---------------------------
    def run_task(self, handler: Any, *args: Any) -> Any:
        """Run a coroutine (or coroutine function) synchronously.

        Flet passes an ``async def`` handler (optionally with args). Real
        Flet schedules it on its loop; here we drain it inline so the
        follow-on navigation is visible to the driver immediately.

        The screens' handlers are navigation shims (``async def _nav:
        self.app.navigate(...)``) that never await real IO, so we *step* the
        coroutine to completion by hand rather than running it under
        ``loop.run_until_complete``. That matters because navigation rebuilds
        a screen which may itself call ``asyncio.run(...)`` for a provider
        lookup — and ``asyncio.run`` refuses to nest inside a running loop.
        """
        result = handler(*args) if callable(handler) else handler
        if inspect.iscoroutine(result):
            try:
                for _ in range(10_000):
                    result.send(None)
            except StopIteration as stop:
                return stop.value
            else:  # pragma: no cover - defensive, our handlers don't block
                result.close()
                raise RuntimeError(
                    "FakePage.run_task: coroutine did not complete synchronously"
                )
        return result

    # Some Flet versions/screens use run_thread as a sibling of run_task.
    def run_thread(self, handler: Any, *args: Any) -> Any:  # pragma: no cover - rare
        return handler(*args) if callable(handler) else handler

    # -- dialogs ---------------------------------------------------------
    def show_dialog(self, dialog: Any) -> None:
        self.dialogs.append(dialog)
        try:
            dialog.open = True
        except Exception:  # pragma: no cover - dialog may be a MagicMock
            pass

    def open(self, dialog: Any) -> None:  # pragma: no cover - legacy alias
        self.show_dialog(dialog)

    def close(self, dialog: Any) -> None:  # pragma: no cover - legacy alias
        try:
            dialog.open = False
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Control-tree walking helpers
# ---------------------------------------------------------------------------

# Flet containers expose their children under different attribute names.
_CHILD_ATTRS = ("controls", "content", "actions", "leading", "title", "trailing")


def iter_tree(control: Any) -> Iterator[Any]:
    """Depth-first walk yielding *control* and every nested child control.

    Handles the several ways Flet nests children: ``.controls`` (Column/Row),
    ``.content`` (Container/AlertDialog), ``.actions`` (AlertDialog), etc.
    Plain strings (e.g. a TextButton's ``.content``) are skipped.
    """
    if control is None:
        return
    yield control
    seen: set[int] = {id(control)}
    for attr in _CHILD_ATTRS:
        child = getattr(control, attr, None)
        if child is None or isinstance(child, (str, bytes, int, float, bool)):
            continue
        if isinstance(child, (list, tuple)):
            for item in child:
                if item is None or isinstance(item, (str, bytes)):
                    continue
                if id(item) in seen:
                    continue
                yield from iter_tree(item)
        else:
            if id(child) in seen:
                continue
            yield from iter_tree(child)


def control_label(control: Any) -> str | None:
    """Return a control's visible text label across Flet versions.

    ``ft.Text`` uses ``.value``; buttons use ``.text`` on some versions and
    ``.content`` (a plain str) on Flet 0.85+.
    """
    val = getattr(control, "value", None)
    if isinstance(val, str):
        return val
    for attr in ("text", "content", "label", "tooltip"):
        candidate = getattr(control, attr, None)
        if isinstance(candidate, str):
            return candidate
    return None
