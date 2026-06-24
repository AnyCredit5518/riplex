"""Tests for scanner module."""

from pathlib import Path
from unittest.mock import patch

import pytest

from riplex.models import ScannedFile
from riplex.scanner import _probe_file, find_ffprobe, scan_folder


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
        with patch("riplex.scanner._probe_file", side_effect=_mock_probe), \
             patch("riplex.scanner.find_ffprobe", return_value="/usr/bin/ffprobe"):
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
        with patch("riplex.scanner._probe_file", side_effect=_mock_probe), \
             patch("riplex.scanner.find_ffprobe", return_value="/usr/bin/ffprobe"):
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
        with patch("riplex.scanner._probe_file", side_effect=_mock_probe), \
             patch("riplex.scanner.find_ffprobe", return_value="/usr/bin/ffprobe"):
            discs = scan_folder(empty)
        assert discs == []

    def test_files_have_absolute_paths(self, rip_folder):
        with patch("riplex.scanner._probe_file", side_effect=_mock_probe), \
             patch("riplex.scanner.find_ffprobe", return_value="/usr/bin/ffprobe"):
            discs = scan_folder(rip_folder)

        for disc in discs:
            for f in disc.files:
                assert Path(f.path).is_absolute()


class TestFindFfprobe:
    def test_returns_path_when_on_path(self):
        with patch("riplex.scanner.shutil.which", return_value="/usr/bin/ffprobe"):
            assert find_ffprobe() == "/usr/bin/ffprobe"

    def test_returns_none_when_not_found(self, monkeypatch):
        monkeypatch.setattr("riplex.scanner.shutil.which", lambda _: None)
        monkeypatch.setattr("riplex.scanner.platform.system", lambda: "Linux")
        monkeypatch.setattr("riplex.scanner._FFPROBE_SEARCH_PATHS", [])
        assert find_ffprobe() is None

    def test_finds_winget_links_shim_on_windows(self, tmp_path, monkeypatch):
        local_appdata = tmp_path / "AppData" / "Local"
        links = local_appdata / "Microsoft" / "WinGet" / "Links"
        links.mkdir(parents=True)
        shim = links / "ffprobe.exe"
        shim.write_text("", encoding="utf-8")

        monkeypatch.setattr("riplex.scanner.shutil.which", lambda _: None)
        monkeypatch.setattr("riplex.scanner.platform.system", lambda: "Windows")
        monkeypatch.setattr("riplex.scanner._FFPROBE_SEARCH_PATHS", [])
        monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))

        assert find_ffprobe() == str(shim)

    def test_finds_winget_package_payload_on_windows(self, tmp_path, monkeypatch):
        local_appdata = tmp_path / "AppData" / "Local"
        bin_dir = (
            local_appdata / "Microsoft" / "WinGet" / "Packages"
            / "Gyan.FFmpeg_Microsoft.Winget.Source_abc"
            / "ffmpeg-7.0-full_build" / "bin"
        )
        bin_dir.mkdir(parents=True)
        exe = bin_dir / "ffprobe.exe"
        exe.write_text("", encoding="utf-8")

        monkeypatch.setattr("riplex.scanner.shutil.which", lambda _: None)
        monkeypatch.setattr("riplex.scanner.platform.system", lambda: "Windows")
        monkeypatch.setattr("riplex.scanner._FFPROBE_SEARCH_PATHS", [])
        monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))

        assert find_ffprobe() == str(exe)

    def test_windows_candidates_skipped_on_non_windows(self, monkeypatch):
        monkeypatch.setattr("riplex.scanner.shutil.which", lambda _: None)
        monkeypatch.setattr("riplex.scanner.platform.system", lambda: "Linux")
        monkeypatch.setattr("riplex.scanner._FFPROBE_SEARCH_PATHS", [])
        called = {"hit": False}

        def _should_not_run():
            called["hit"] = True
            return []

        monkeypatch.setattr("riplex.scanner._windows_ffprobe_candidates", _should_not_run)
        assert find_ffprobe() is None
        assert called["hit"] is False

