"""Tests for the GUI-side disc-detection helpers that don't require Flet."""

from riplex.disc.makemkv import DriveInfo
from riplex_app.screens.disc_detection import diff_drive_lists


def _drive(index=0, device="D:", has_disc=False, label="", state="Empty", present=True):
    return DriveInfo(
        index=index,
        name="Test Drive",
        disc_label=label,
        device=device,
        has_disc=has_disc,
        is_present=present,
        state_label=state,
    )


class TestDiffDriveLists:
    def test_first_poll_always_changed(self):
        assert diff_drive_lists(None, [_drive()]) is True

    def test_no_change(self):
        a = [_drive()]
        b = [_drive()]
        assert diff_drive_lists(a, b) is False

    def test_disc_inserted(self):
        a = [_drive()]
        b = [_drive(has_disc=True, label="MOVIE", state="Disc: MOVIE")]
        assert diff_drive_lists(a, b) is True

    def test_label_change(self):
        a = [_drive(has_disc=True, label="A", state="Disc: A")]
        b = [_drive(has_disc=True, label="B", state="Disc: B")]
        assert diff_drive_lists(a, b) is True

    def test_placeholder_slots_ignored(self):
        a = [_drive(), _drive(index=1, device="", present=False)]
        b = [_drive()]
        assert diff_drive_lists(a, b) is False

    def test_drive_count_change(self):
        a = [_drive()]
        b = [_drive(), _drive(index=1, device="E:")]
        assert diff_drive_lists(a, b) is True
