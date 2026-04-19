"""Tests for detect module."""

from pathlib import Path

import pytest

from plex_planner.detect import (
    TitleGroup,
    _normalize_title,
    detect_format,
    detect_incomplete,
    group_title_folders,
)
from plex_planner.models import ScannedDisc, ScannedFile


class TestDetectFormat:
    def test_4k(self):
        discs = [ScannedDisc(folder_name="D1", files=[
            ScannedFile(name="a.mkv", path="/a.mkv", max_width=3840, max_height=2160),
        ])]
        assert detect_format(discs) == "Blu-ray 4K"

    def test_1080p(self):
        discs = [ScannedDisc(folder_name="D1", files=[
            ScannedFile(name="a.mkv", path="/a.mkv", max_width=1920, max_height=1080),
        ])]
        assert detect_format(discs) == "Blu-ray"

    def test_720p(self):
        discs = [ScannedDisc(folder_name="D1", files=[
            ScannedFile(name="a.mkv", path="/a.mkv", max_width=1280, max_height=720),
        ])]
        assert detect_format(discs) == "Blu-ray"

    def test_dvd(self):
        discs = [ScannedDisc(folder_name="D1", files=[
            ScannedFile(name="a.mkv", path="/a.mkv", max_width=720, max_height=480),
        ])]
        assert detect_format(discs) == "DVD"

    def test_mixed_4k_and_1080p(self):
        """4K main disc + 1080p extras -> Blu-ray 4K."""
        discs = [
            ScannedDisc(folder_name="Main", files=[
                ScannedFile(name="a.mkv", path="/a.mkv", max_width=3840, max_height=2160),
            ]),
            ScannedDisc(folder_name="Bonus", files=[
                ScannedFile(name="b.mkv", path="/b.mkv", max_width=1920, max_height=1080),
            ]),
        ]
        assert detect_format(discs) == "Blu-ray 4K"

    def test_no_video(self):
        discs = [ScannedDisc(folder_name="D1", files=[
            ScannedFile(name="a.mkv", path="/a.mkv", max_width=0, max_height=0),
        ])]
        assert detect_format(discs) is None

    def test_empty_discs(self):
        assert detect_format([]) is None

    def test_multiple_files_picks_max(self):
        discs = [ScannedDisc(folder_name="D1", files=[
            ScannedFile(name="a.mkv", path="/a.mkv", max_width=720, max_height=480),
            ScannedFile(name="b.mkv", path="/b.mkv", max_width=3840, max_height=2160),
        ])]
        assert detect_format(discs) == "Blu-ray 4K"


class TestDetectIncomplete:
    def test_zero_duration(self):
        discs = [ScannedDisc(folder_name="D1", files=[
            ScannedFile(name="a.mkv", path="/a.mkv", duration_seconds=0, stream_count=3),
            ScannedFile(name="b.mkv", path="/b.mkv", duration_seconds=100, stream_count=3,
                        stream_fingerprint="h264:1920x1080|ac3:eng:6ch"),
        ])]
        incomplete = detect_incomplete(discs)
        assert len(incomplete) == 1
        assert incomplete[0].name == "a.mkv"

    def test_zero_streams(self):
        discs = [ScannedDisc(folder_name="D1", files=[
            ScannedFile(name="a.mkv", path="/a.mkv", duration_seconds=100, stream_count=0),
        ])]
        incomplete = detect_incomplete(discs)
        assert len(incomplete) == 1

    def test_all_complete(self):
        discs = [ScannedDisc(folder_name="D1", files=[
            ScannedFile(name="a.mkv", path="/a.mkv", duration_seconds=100, stream_count=3,
                        stream_fingerprint="h264:1920x1080|ac3:eng:6ch"),
        ])]
        assert detect_incomplete(discs) == []

    def test_empty_discs(self):
        assert detect_incomplete([]) == []

    def test_no_audio_is_incomplete(self):
        discs = [ScannedDisc(folder_name="D1", files=[
            ScannedFile(name="warn.mkv", path="/warn.mkv", duration_seconds=340,
                        stream_count=1, stream_fingerprint="h264:1920x1080"),
            ScannedFile(name="movie.mkv", path="/movie.mkv", duration_seconds=7200,
                        stream_count=4, stream_fingerprint="hevc:3840x2160|truehd:eng:8ch|sub:eng|sub:spa"),
        ])]
        incomplete = detect_incomplete(discs)
        assert len(incomplete) == 1
        assert incomplete[0].name == "warn.mkv"

    def test_subtitle_only_no_audio_is_incomplete(self):
        discs = [ScannedDisc(folder_name="D1", files=[
            ScannedFile(name="menu.mkv", path="/menu.mkv", duration_seconds=60,
                        stream_count=2, stream_fingerprint="h264:1920x1080|sub:eng"),
        ])]
        incomplete = detect_incomplete(discs)
        assert len(incomplete) == 1


class TestNormalizeTitle:
    def test_plain_title(self):
        assert _normalize_title("Oppenheimer") == "Oppenheimer"

    def test_disc_number_dash(self):
        assert _normalize_title("Planet Earth III - Disc 1") == "Planet Earth III"

    def test_disc_number_dash_d(self):
        assert _normalize_title("Planet Earth III - D2") == "Planet Earth III"

    def test_disc_number_space(self):
        assert _normalize_title("BLUE PLANET II D2") == "BLUE PLANET II"

    def test_special_features_dash(self):
        assert _normalize_title("Batman Begins - Special Features") == "Batman Begins"

    def test_bonus_suffix(self):
        assert _normalize_title("Batman Begins Bonus") == "Batman Begins"

    def test_extras_suffix(self):
        assert _normalize_title("Movie Name Extras") == "Movie Name"

    def test_multi_disc_with_bonus(self):
        """Disc number stripped, not bonus since it's the disc suffix."""
        assert _normalize_title("Movie - Disc 3") == "Movie"

    def test_preserves_inner_words(self):
        """'Bonus' inside title is not stripped."""
        assert _normalize_title("Bonus Round Movie") == "Bonus Round Movie"

    def test_case_insensitive(self):
        assert _normalize_title("Movie - DISC 1") == "Movie"
        assert _normalize_title("Movie - special features") == "Movie"


class TestGroupTitleFolders:
    def test_single_title(self, tmp_path):
        d = tmp_path / "Oppenheimer"
        d.mkdir()
        (d / "file.mkv").write_bytes(b"\x00")
        groups = group_title_folders(tmp_path)
        assert len(groups) == 1
        assert groups[0].title == "Oppenheimer"
        assert groups[0].folders == [d]

    def test_multi_disc(self, tmp_path):
        for name in ["Planet Earth III - Disc 1", "Planet Earth III - Disc 2"]:
            d = tmp_path / name
            d.mkdir()
            (d / "file.mkv").write_bytes(b"\x00")
        groups = group_title_folders(tmp_path)
        assert len(groups) == 1
        assert groups[0].title == "Planet Earth III"
        assert len(groups[0].folders) == 2

    def test_multiple_titles(self, tmp_path):
        for name in ["Batman Begins", "Dark Knight Rises"]:
            d = tmp_path / name
            d.mkdir()
            (d / "file.mkv").write_bytes(b"\x00")
        groups = group_title_folders(tmp_path)
        assert len(groups) == 2
        titles = [g.title for g in groups]
        assert "Batman Begins" in titles
        assert "Dark Knight Rises" in titles

    def test_ignores_underscore_folders(self, tmp_path):
        d = tmp_path / "_archive"
        d.mkdir()
        (d / "file.mkv").write_bytes(b"\x00")
        groups = group_title_folders(tmp_path)
        assert len(groups) == 0

    def test_ignores_empty_folders(self, tmp_path):
        (tmp_path / "EmptyFolder").mkdir()
        groups = group_title_folders(tmp_path)
        assert len(groups) == 0

    def test_title_with_bonus_subfolder(self, tmp_path):
        main = tmp_path / "Batman Begins"
        main.mkdir()
        (main / "file.mkv").write_bytes(b"\x00")
        bonus = tmp_path / "Batman Begins Bonus"
        bonus.mkdir()
        (bonus / "file.mkv").write_bytes(b"\x00")
        groups = group_title_folders(tmp_path)
        assert len(groups) == 1
        assert groups[0].title == "Batman Begins"
        assert len(groups[0].folders) == 2

    def test_subfolder_mkvs(self, tmp_path):
        """MKVs in a subfolder of a subfolder should still be found."""
        d = tmp_path / "Movie"
        d.mkdir()
        sub = d / "Special Features"
        sub.mkdir()
        (sub / "file.mkv").write_bytes(b"\x00")
        groups = group_title_folders(tmp_path)
        assert len(groups) == 1

    def test_sorted_output(self, tmp_path):
        for name in ["Zebra", "Apple", "Middle"]:
            d = tmp_path / name
            d.mkdir()
            (d / "file.mkv").write_bytes(b"\x00")
        groups = group_title_folders(tmp_path)
        titles = [g.title for g in groups]
        assert titles == sorted(titles)
