from types import SimpleNamespace

from riplex_app import background
from riplex_app.screens.update import UpdateScreen


class _DeferredThread:
    created: list["_DeferredThread"] = []

    def __init__(self, *, target, daemon, name=None, args=()):
        self.target = target
        self.args = args
        self.created.append(self)

    def start(self):
        pass


def test_duplicate_update_click_starts_one_worker(monkeypatch):
    _DeferredThread.created = []
    monkeypatch.setattr(background.threading, "Thread", _DeferredThread)
    app = SimpleNamespace(
        state={"update_info": {"tag": "v2.0.0"}},
        page=SimpleNamespace(update=lambda: None),
    )
    screen = UpdateScreen(app)
    screen._progress = SimpleNamespace(visible=False, value=0)
    screen._status = SimpleNamespace(value="", color=None)
    screen._actions = SimpleNamespace(controls=[])

    screen._start_self_update(None)
    screen._start_self_update(None)

    assert len(_DeferredThread.created) == 1
    assert screen._progress.visible
    assert screen._status.value == "Downloading update\u2026"