"""Tests for the progress screen's auto-eject behaviour."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from riplex.disc.makemkv import DiscInfo, DiscTitle, DriveInfo, RipResult
from riplex_app.screens import progress as progress_mod
from riplex_app.screens.progress import ProgressScreen


class _App:
    def __init__(self, state):
        self.state = state
        self.page = SimpleNamespace(update=lambda *a, **k: None)


def _screen(*, device="D:"):
    drive = DriveInfo(
        index=0, name="BD-RE", disc_label="MOVIE", device=device,
        has_disc=True, is_present=True, state_label="Disc: MOVIE",
    )
    app = _App({"drive": drive})
    screen = ProgressScreen(app)
    # _log_message appends to self.log.controls; give it a stand-in.
    screen.log = SimpleNamespace(controls=[])
    return screen


def _ok(idx=0):
    return RipResult(title_index=idx, success=True, output_file=f"t{idx}.mkv")


def _fail(idx=0):
    return RipResult(title_index=idx, success=False, output_file="", error_message="boom")


@pytest.fixture
def ejects(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr("riplex.disc.makemkv.eject_disc", lambda dev: calls.append(dev) or True)
    return calls


def _enable_eject(monkeypatch, enabled=True):
    monkeypatch.setattr("riplex.config.get_auto_eject", lambda: enabled)


def test_auto_eject_ejects_after_successful_rip(ejects, monkeypatch):
    _enable_eject(monkeypatch, True)
    screen = _screen(device="E:")

    screen._auto_eject([_ok()])

    assert ejects == ["E:"]


def test_auto_eject_disabled_by_config(ejects, monkeypatch):
    _enable_eject(monkeypatch, False)
    screen = _screen()

    screen._auto_eject([_ok()])

    assert ejects == []


def test_auto_eject_skipped_when_cancelled(ejects, monkeypatch):
    _enable_eject(monkeypatch, True)
    screen = _screen()
    screen._cancel_event.set()

    screen._auto_eject([_ok()])

    assert ejects == []


def test_auto_eject_skipped_when_no_rip_succeeded(ejects, monkeypatch):
    _enable_eject(monkeypatch, True)
    screen = _screen()

    screen._auto_eject([_fail()])

    assert ejects == []


def test_auto_eject_skipped_without_drive_device(ejects, monkeypatch):
    _enable_eject(monkeypatch, True)
    screen = _screen(device="")

    screen._auto_eject([_ok()])

    assert ejects == []


def test_auto_eject_failure_is_non_fatal(monkeypatch):
    _enable_eject(monkeypatch, True)

    def _boom(_dev):
        raise RuntimeError("tray stuck")

    monkeypatch.setattr("riplex.disc.makemkv.eject_disc", _boom)
    screen = _screen()

    # Must not raise — a failed eject is logged, not propagated.
    screen._auto_eject([_ok()])

    assert any("Auto-eject failed" in getattr(c, "value", "") for c in screen.log.controls)


# ---------------------------------------------------------------------------
# Cancel behaviour — a cancelled rip returns to the CURRENT disc, not the next
# ---------------------------------------------------------------------------


class _NoThread:
    """threading.Thread stand-in whose start() is a no-op.

    Stops ``build()``'s background rip thread from running so the test drives
    ``_run_rips_inner`` deterministically.
    """

    def __init__(self, *a, **k):
        pass

    def start(self):
        pass

    def join(self, *a, **k):
        pass


class _NavApp:
    def __init__(self, state):
        self.state = state
        self.navigated: list[str] = []

        def _run_task(handler, *args):
            coro = handler(*args) if callable(handler) else handler
            try:
                coro.send(None)
            except StopIteration:
                pass

        self.page = SimpleNamespace(update=lambda *a, **k: None, run_task=_run_task)

    def navigate(self, screen):
        self.navigated.append(screen)


def _orchestrate_state(tmp_path):
    drive = DriveInfo(
        index=0, name="BD-RE", disc_label="SEASON6_D3", device="D:",
        has_disc=True, is_present=True, state_label="Disc: SEASON6_D3",
    )
    disc_info = DiscInfo(
        disc_name="SEASON6_D3", disc_type="Blu-ray disc",
        titles=[DiscTitle(
            index=0, name="", duration_seconds=1300, chapters=0, size_bytes=1,
            filename="t00.mkv", playlist="", resolution="1920x1080", video_codec="",
        )],
    )
    return {
        "workflow": "orchestrate",
        "selected_titles": [0],
        "disc_info": disc_info,
        "output_dir": tmp_path,
        "makemkvcon": None,
        "drive": drive,
        # Ripping disc 3 of the [3, 4] queue.
        "disc_queue": [3, 4],
        "current_disc_idx": 0,
        "_orchestrate_disc_number": 3,
        "all_rip_results": {},
        "ripped_discs": set(),
    }


def _run_cancelled(monkeypatch, tmp_path):
    monkeypatch.setattr(progress_mod.threading, "Thread", _NoThread)
    app = _NavApp(_orchestrate_state(tmp_path))
    screen = ProgressScreen(app)
    screen.build()  # creates the UI controls; the rip thread is a no-op
    screen._cancel_event.set()  # user cancelled immediately
    screen._run_rips_inner()
    return app, screen


def test_cancel_returns_to_current_disc_swap(monkeypatch, tmp_path):
    app, _ = _run_cancelled(monkeypatch, tmp_path)

    # Back to the current disc's Insert Disc screen, NOT the next disc.
    assert app.navigated == ["disc_swap"]


def test_cancel_does_not_advance_the_queue(monkeypatch, tmp_path):
    app, _ = _run_cancelled(monkeypatch, tmp_path)

    assert app.state["current_disc_idx"] == 0
    assert app.state["_orchestrate_disc_number"] == 3


def test_cancel_does_not_mark_disc_ripped(monkeypatch, tmp_path):
    app, _ = _run_cancelled(monkeypatch, tmp_path)

    assert app.state["ripped_discs"] == set()
    assert 3 not in app.state["all_rip_results"]


def test_cancel_does_not_write_manifest(monkeypatch, tmp_path):
    called = {"manifest": False, "eject": False}
    monkeypatch.setattr(ProgressScreen, "_write_manifest", lambda self, r: called.__setitem__("manifest", True))
    monkeypatch.setattr(ProgressScreen, "_auto_eject", lambda self, r: called.__setitem__("eject", True))

    _run_cancelled(monkeypatch, tmp_path)

    # A cancelled disc must not be recorded as completed (resume relies on the
    # manifest) and must not auto-eject.
    assert called["manifest"] is False
    assert called["eject"] is False

