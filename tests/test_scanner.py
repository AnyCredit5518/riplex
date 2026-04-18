"""Tests for scanner module."""

from pathlib import Path
from unittest.mock import patch

import pytest

from plex_planner.models import ScannedFile
from plex_planner.scanner import _probe_file, scan_folder


@pytest.fixture
def rip_folder(tmp_path):
    """Create a fake MakeMKV rip folder structure."""
    # Root-level MKVs
    (tmp_path / "Movie_t00.mkv").write_bytes(b"\x00")
    (tmp_path / "Movie_t01.mkv").write_bytes(b"\x00")

    # Subfolder with MKVs
    sf = tmp_path / "Special Features"
    sf.mkdir()
    (sf / "Special Features_t02.mkv").write_bytes(b"\x00")
    (sf / "Special Features_t03.mkv").write_bytes(b"\x00")

    # Ignored folder (starts with _)
    archive = tmp_path / "_archive"
    archive.mkdir()
    (archive / "old.mkv").write_bytes(b"\x00")

    return tmp_path


def _mock_probe(path):
    """Return fake ScannedFile based on filename."""
    name = Path(path).name
    durations = {
        "Movie_t00.mkv": 325,
        "Movie_t01.mkv": 10822,
        "Special Features_t02.mkv": 5238,
        "Special Features_t03.mkv": 501,
    }
    return ScannedFile(
        name=name,
        path=str(path),
        duration_seconds=durations.get(name, 0),
        size_bytes=1000,
        stream_count=3,
        stream_fingerprint="h264:1920x1080|ac3:eng:2ch|sub:eng",
        chapter_count=0,
    )


class TestScanFolder:
    def test_structure(self, rip_folder):
        with patch("plex_planner.scanner._probe_file", side_effect=_mock_probe):
            discs = scan_folder(rip_folder)

        assert len(discs) == 2

        # Root disc
        root = discs[0]
        assert root.folder_name == rip_folder.name
        assert len(root.files) == 2
        assert root.files[0].name == "Movie_t00.mkv"
        assert root.files[0].duration_seconds == 325
        assert root.files[1].name == "Movie_t01.mkv"
        assert root.files[1].duration_seconds == 10822

        # Subfolder disc
        sf = discs[1]
        assert sf.folder_name == "Special Features"
        assert len(sf.files) == 2
        assert sf.files[0].duration_seconds == 5238
        assert sf.files[1].duration_seconds == 501

    def test_ignores_underscore_folders(self, rip_folder):
        with patch("plex_planner.scanner._probe_file", side_effect=_mock_probe):
            discs = scan_folder(rip_folder)

        folder_names = [d.folder_name for d in discs]
        assert "_archive" not in folder_names

    def test_not_a_directory(self, tmp_path):
        fake = tmp_path / "nonexistent"
        with pytest.raises(FileNotFoundError):
            scan_folder(fake)

    def test_empty_folder(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        with patch("plex_planner.scanner._probe_file", side_effect=_mock_probe):
            discs = scan_folder(empty)
        assert discs == []

    def test_files_have_absolute_paths(self, rip_folder):
        with patch("plex_planner.scanner._probe_file", side_effect=_mock_probe):
            discs = scan_folder(rip_folder)

        for disc in discs:
            for f in disc.files:
                assert Path(f.path).is_absolute()
