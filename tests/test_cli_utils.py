"""Tests for CLI utility functions."""

import pytest

from plex_planner.cli import _infer_title_from_scanned, _strip_year_from_title
from plex_planner.models import ScannedDisc, ScannedFile


# ---------------------------------------------------------------------------
# _strip_year_from_title
# ---------------------------------------------------------------------------


class TestStripYearFromTitle:
    def test_trailing_year(self):
        assert _strip_year_from_title("Waterworld (1995)") == ("Waterworld", 1995)

    def test_no_year(self):
        assert _strip_year_from_title("Waterworld") == ("Waterworld", None)

    def test_year_in_middle_ignored(self):
        title, year = _strip_year_from_title("2001 A Space Odyssey")
        assert title == "2001 A Space Odyssey"
        assert year is None

    def test_trailing_year_with_extra_spaces(self):
        assert _strip_year_from_title("Blade Runner  (1982) ") == ("Blade Runner", 1982)


# ---------------------------------------------------------------------------
# _infer_title_from_scanned
# ---------------------------------------------------------------------------


def _make_disc(files):
    return ScannedDisc(folder_name="test", files=files)


def _make_file(name="test.mkv", duration=100, title_tag=None):
    return ScannedFile(name=name, path=f"/tmp/{name}", duration_seconds=duration, title_tag=title_tag)


class TestInferTitleFromScanned:
    def test_uses_longest_file_title_tag(self):
        scanned = [_make_disc([
            _make_file("short.mkv", 300, "Waterworld"),
            _make_file("long.mkv", 8000, "Waterworld"),
            _make_file("extra.mkv", 500, "Waterworld"),
        ])]
        assert _infer_title_from_scanned(scanned) == "Waterworld"

    def test_returns_none_when_no_title_tag(self):
        scanned = [_make_disc([
            _make_file("a.mkv", 8000, None),
        ])]
        assert _infer_title_from_scanned(scanned) is None

    def test_returns_none_for_empty_title_tag(self):
        scanned = [_make_disc([
            _make_file("a.mkv", 8000, "  "),
        ])]
        assert _infer_title_from_scanned(scanned) is None

    def test_returns_none_for_empty_scanned(self):
        assert _infer_title_from_scanned([]) is None
        assert _infer_title_from_scanned([_make_disc([])]) is None

    def test_strips_trailing_year(self):
        scanned = [_make_disc([
            _make_file("a.mkv", 8000, "Blade Runner (1982)"),
        ])]
        assert _infer_title_from_scanned(scanned) == "Blade Runner"

    def test_colon_preserved(self):
        scanned = [_make_disc([
            _make_file("a.mkv", 8000, "Blade Runner: The Final Cut"),
        ])]
        assert _infer_title_from_scanned(scanned) == "Blade Runner: The Final Cut"
