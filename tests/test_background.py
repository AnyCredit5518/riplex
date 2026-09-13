from types import SimpleNamespace

import pytest

from riplex_app import background


class _DeferredThread:
    created: list["_DeferredThread"] = []

    def __init__(self, *, target, daemon, name):
        self.target = target
        self.daemon = daemon
        self.name = name
        self.started = False
        self.created.append(self)

    def start(self):
        self.started = True

    def run(self):
        self.target()


@pytest.fixture(autouse=True)
def _defer_background_threads(monkeypatch):
    _DeferredThread.created = []
    monkeypatch.setattr(background.threading, "Thread", _DeferredThread)


def test_rejects_duplicate_until_worker_finishes():
    app = SimpleNamespace()
    calls: list[str] = []

    assert background.start_background_once(app, "lookup", calls.append, args=("first",))
    assert not background.start_background_once(app, "lookup", calls.append, args=("second",))
    assert len(_DeferredThread.created) == 1

    _DeferredThread.created[0].run()

    assert calls == ["first"]
    assert background.start_background_once(app, "lookup", calls.append, args=("retry",))


def test_releases_operation_after_worker_failure():
    app = SimpleNamespace()

    def _fail():
        raise RuntimeError("failed")

    assert background.start_background_once(app, "lookup", _fail)
    with pytest.raises(RuntimeError, match="failed"):
        _DeferredThread.created[0].run()

    assert background.start_background_once(app, "lookup", lambda: None)


def test_screen_lease_survives_rerender_but_not_navigation_away():
    app = SimpleNamespace(_current_screen_name="release", _navigation_epoch=4)
    lease = background.capture_screen_lease(app)

    assert background.screen_lease_is_current(app, lease)

    app._current_screen_name = "metadata"
    app._navigation_epoch += 1
    assert not background.screen_lease_is_current(app, lease)

    app._current_screen_name = "release"
    app._navigation_epoch += 1
    assert not background.screen_lease_is_current(app, lease)


def test_screen_operation_key_changes_for_new_visit():
    first = background.ScreenLease("release", 4)
    second = background.ScreenLease("release", 6)

    assert background.screen_operation_key("lookup", first) == "lookup:4"
    assert background.screen_operation_key("lookup", second) == "lookup:6"