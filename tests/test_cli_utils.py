"""Tests for CLI utility functions."""

import pytest

from plex_planner.cli import (
    _detect_disc_format,
    _infer_title_from_scanned,
    _parse_volume_label,
    _strip_year_from_title,
)
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

    def test_strips_trailing_disc_label(self):
        scanned = [_make_disc([
            _make_file("a.mkv", 8000, "SEVEN WORLDS ONE PLANET D1"),
        ])]
        assert _infer_title_from_scanned(scanned) == "SEVEN WORLDS ONE PLANET"

    def test_strips_disc_with_word(self):
        scanned = [_make_disc([
            _make_file("a.mkv", 8000, "Planet Earth III Disc 2"),
        ])]
        assert _infer_title_from_scanned(scanned) == "Planet Earth III"


# ---------------------------------------------------------------------------
# _parse_volume_label
# ---------------------------------------------------------------------------


class TestParseVolumeLabel:
    def test_frozen_planet_ii_d2(self):
        assert _parse_volume_label("FROZEN_PLANET_II_D2") == "Frozen Planet II"

    def test_planet_earth_iii_disc3(self):
        assert _parse_volume_label("PLANET_EARTH_III-Disc3") == "Planet Earth III"

    def test_blade_runner_2049(self):
        assert _parse_volume_label("BLADE_RUNNER_2049") == "Blade Runner 2049"

    def test_top_gun(self):
        assert _parse_volume_label("TOP_GUN") == "Top Gun"

    def test_disc_suffix_word_form(self):
        assert _parse_volume_label("OPPENHEIMER_Disc_1") == "Oppenheimer"

    def test_returns_none_for_short(self):
        assert _parse_volume_label("AB") is None

    def test_returns_none_for_empty(self):
        assert _parse_volume_label("") is None

    def test_returns_none_for_none(self):
        assert _parse_volume_label(None) is None

    def test_preserves_roman_numerals(self):
        assert _parse_volume_label("ROCKY_IV") == "Rocky IV"

    def test_preserves_mixed_roman(self):
        assert _parse_volume_label("STAR_WARS_III") == "Star Wars III"


# ---------------------------------------------------------------------------
# _detect_disc_format
# ---------------------------------------------------------------------------


class TestDetectDiscFormat:
    def _make_disc_info(self, resolutions):
        from plex_planner.makemkv import DiscInfo, DiscTitle

        titles = [
            DiscTitle(
                index=i, name=f"title_{i}", duration_seconds=3600,
                chapters=10, size_bytes=1_000_000, filename=f"t{i}.mkv",
                playlist=f"000{i}.mpls", resolution=res,
                video_codec="Mpeg4",
            )
            for i, res in enumerate(resolutions)
        ]
        return DiscInfo(disc_name="TEST", disc_type="Blu-ray disc", titles=titles)

    def test_4k_detected(self):
        info = self._make_disc_info(["3840x2160", "1920x1080"])
        assert _detect_disc_format(info) == "Blu-ray 4K"

    def test_bluray_hd(self):
        info = self._make_disc_info(["1920x1080", "1920x1080"])
        assert _detect_disc_format(info) == "Blu-ray"

    def test_no_titles(self):
        info = self._make_disc_info([])
        assert _detect_disc_format(info) is None

    def test_single_4k_title(self):
        info = self._make_disc_info(["3840x2160"])
        assert _detect_disc_format(info) == "Blu-ray 4K"
