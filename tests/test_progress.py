"""Tests for the progress screen's auto-eject behaviour."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from riplex.disc.makemkv import DriveInfo, RipResult
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
