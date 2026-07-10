"""Drive the wizard headlessly and query/click the current screen's controls.

``WizardDriver`` builds a real ``RiplexApp`` on a :class:`FakePage`, so the
production ``navigate()`` / ``build()`` code runs unchanged. Tests use it to
click buttons by label, read text, and assert which screen is showing — the
same way a user would move through the wizard, minus the pixels.
"""

from __future__ import annotations

from typing import Any, Callable

from riplex_app.main import RiplexApp

from .fake_page import FakePage, control_label, iter_tree


class FakeEvent:
    """Stand-in for a Flet ``ControlEvent`` passed to ``on_click`` handlers."""

    def __init__(self, control: Any = None, page: Any = None, data: Any = None) -> None:
        self.control = control
        self.page = page
        self.data = data


class NoSuchControl(AssertionError):
    pass


class WizardDriver:
    """A thin harness over ``RiplexApp`` + ``FakePage``."""

    def __init__(self) -> None:
        self.page = FakePage()
        self.app = RiplexApp(self.page)

    # -- state -----------------------------------------------------------
    @property
    def state(self) -> dict:
        return self.app.state

    @property
    def current(self) -> str:
        return getattr(self.app, "_current_screen_name", "")

    @property
    def screen(self) -> Any:
        return self.app.screens[self.current]

    def navigate(self, name: str) -> None:
        self.app.navigate(name)

    # -- tree queries ----------------------------------------------------
    def controls(self) -> list[Any]:
        out: list[Any] = []
        for root in self.page.controls:
            out.extend(iter_tree(root))
        return out

    def texts(self) -> list[str]:
        return [t for c in self.controls() if (t := control_label(c)) is not None]

    def has_text(self, substring: str) -> bool:
        low = substring.lower()
        return any(low in t.lower() for t in self.texts())

    def find(self, predicate: Callable[[Any], bool]) -> list[Any]:
        return [c for c in self.controls() if predicate(c)]

    def find_by_label(self, label: str) -> list[Any]:
        low = label.lower()
        return [
            c for c in self.controls()
            if (lbl := control_label(c)) is not None and low in lbl.lower()
        ]

    def _clickables(self) -> list[Any]:
        return [c for c in self.controls() if callable(getattr(c, "on_click", None))]

    def click(self, label: str) -> None:
        """Invoke the ``on_click`` of the first enabled control matching *label*."""
        low = label.lower()
        for c in self._clickables():
            lbl = control_label(c)
            if lbl is not None and low in lbl.lower() and not getattr(c, "disabled", False):
                c.on_click(FakeEvent(control=c, page=self.page))
                return
        available = sorted({control_label(c) for c in self._clickables()} - {None})
        raise NoSuchControl(
            f"No enabled clickable labelled {label!r} on screen {self.current!r}. "
            f"Available: {available}"
        )

    def crashed(self) -> bool:
        """True if a crash dialog was surfaced during the flow."""
        return bool(self.page.dialogs) and any(
            "crash" in str(getattr(d, "title", "")).lower() for d in self.page.dialogs
        ) or bool(self.page.errors)
