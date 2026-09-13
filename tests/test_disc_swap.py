from types import SimpleNamespace

from riplex_app import background
from riplex_app.background import capture_screen_lease
from riplex_app.screens.disc_swap import DiscSwapScreen


class _DeferredThread:
    created: list["_DeferredThread"] = []

    def __init__(self, *, target, daemon, name=None, args=()):
        self.target = target
        self.args = args
        self.created.append(self)

    def start(self):
        pass


def test_duplicate_scan_click_starts_one_worker(monkeypatch):
    _DeferredThread.created = []
    monkeypatch.setattr(background.threading, "Thread", _DeferredThread)
    app = SimpleNamespace(
        state={
            "_orchestrate_disc_number": 1,
            "dvdcompare_discs": [],
            "current_disc_idx": 0,
        },
        page=SimpleNamespace(update=lambda: None),
    )
    screen = DiscSwapScreen(app)
    screen.build()

    screen._scan(None)
    screen._scan(None)

    assert len(_DeferredThread.created) == 1
    assert screen.scan_btn.disabled
    assert screen.spinner.visible


def test_late_disc_scan_does_not_mutate_new_screen(monkeypatch):
    monkeypatch.setattr(
        "riplex_app.screens.disc_swap.run_drive_list",
        lambda **_kwargs: [],
    )
    app = SimpleNamespace(
        state={
            "_orchestrate_disc_number": 1,
            "dvdcompare_discs": [],
            "current_disc_idx": 0,
        },
        _current_screen_name="disc_swap",
        _navigation_epoch=7,
        page=SimpleNamespace(update=lambda: None),
    )
    screen = DiscSwapScreen(app)
    screen.build()
    lease = capture_screen_lease(app)

    app._current_screen_name = "disc_overview"
    app._navigation_epoch += 1
    screen._do_scan(lease)

    assert "drive" not in app.state
    assert "disc_info" not in app.state