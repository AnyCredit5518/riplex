import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

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


@pytest.mark.parametrize("failure", [None, "apply", "close"])
def test_self_update_awaits_close_and_reports_failures(monkeypatch, tmp_path, failure):
    from riplex import updater

    staged = tmp_path / "riplex-ui.exe.new"
    tasks = []
    events = []

    def apply_update(path):
        assert path == staged
        events.append("launch")
        if failure == "apply":
            raise OSError("cannot replace executable")

    async def close_window():
        events.append("close")
        if failure == "close":
            raise RuntimeError("cannot close window")

    close = AsyncMock(side_effect=close_window)
    app = SimpleNamespace(
        state={},
        page=SimpleNamespace(
            update=lambda: None,
            run_task=tasks.append,
            window=SimpleNamespace(close=close),
        ),
    )
    screen = UpdateScreen(app)
    screen._updating = True
    screen._progress = SimpleNamespace(visible=True, value=None)
    screen._status = SimpleNamespace(value="", color=None)
    screen._actions = SimpleNamespace(controls=[])
    monkeypatch.setattr(updater, "stage_update", lambda *a, **kw: staged)
    monkeypatch.setattr(updater, "apply_update_and_relaunch", apply_update)

    screen._run_self_update({"url": "https://example.com/release"})

    async def drain_tasks():
        while tasks:
            await tasks.pop(0)()

    asyncio.run(drain_tasks())

    if failure == "apply":
        assert events == ["launch"]
        close.assert_not_called()
    else:
        assert events == ["launch", "close"]
        close.assert_awaited_once_with()
    if failure:
        assert not screen._updating
        assert not screen._progress.visible
        assert "Update failed:" in screen._status.value
        assert screen._actions.controls
    else:
        assert screen._progress.value == 1.0
        assert screen._status.value == "Update verified. Restarting riplex\u2026"