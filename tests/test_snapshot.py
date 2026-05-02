"""Tests for the snapshot capture/load round-trip."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from riplex.models import ScannedDisc, ScannedFile
from riplex.snapshot import (
    SNAPSHOT_VERSION,
    SNAPSHOT_VERSION_V2,
    _dict_to_file,
    _file_to_dict,
    capture,
    capture_from_scanned,
    copy_debug_log,
    get_debug_dir,
    load,
    load_organized_marker,
    save,
    save_from_scanned,
    save_organized_marker,
    save_rip_manifest,
    save_rip_snapshot,
    save_scan_snapshot,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_file(**overrides) -> ScannedFile:
    defaults = dict(
        name="title_t00.mkv",
        path="/fake/title_t00.mkv",
        duration_seconds=7200,
        size_bytes=5_000_000_000,
        stream_count=4,
        stream_fingerprint="hevc:3840x2160|truehd:eng:8ch|sub:eng|sub:spa",
        chapter_count=28,
        chapter_durations=[300] * 28,
        title_tag="My Movie",
        max_width=3840,
        max_height=2160,
        organized_tag=None,
        perceptual_hash=123456789,
    )
    defaults.update(overrides)
    return ScannedFile(**defaults)


def _make_discs() -> list[ScannedDisc]:
    return [
        ScannedDisc(
            folder_name="Movie Title",
            files=[
                _make_file(name="title_t00.mkv", duration_seconds=7200),
                _make_file(name="title_t01.mkv", duration_seconds=180, chapter_count=0, chapter_durations=[]),
            ],
        ),
        ScannedDisc(
            folder_name="Special Features",
            files=[
                _make_file(name="title_t02.mkv", duration_seconds=600),
            ],
        ),
    ]


# ---------------------------------------------------------------------------
# _file_to_dict / _dict_to_file round-trip
# ---------------------------------------------------------------------------

class TestFileRoundTrip:
    def test_round_trip_preserves_all_fields(self):
        original = _make_file()
        d = _file_to_dict(original)
        restored = _dict_to_file(d)

        assert restored.name == original.name
        assert restored.duration_seconds == original.duration_seconds
        assert restored.size_bytes == original.size_bytes
        assert restored.stream_count == original.stream_count
        assert restored.stream_fingerprint == original.stream_fingerprint
        assert restored.chapter_count == original.chapter_count
        assert restored.chapter_durations == original.chapter_durations
        assert restored.title_tag == original.title_tag
        assert restored.max_width == original.max_width
        assert restored.max_height == original.max_height
        assert restored.organized_tag == original.organized_tag
        assert restored.perceptual_hash == original.perceptual_hash

    def test_dict_does_not_include_path(self):
        d = _file_to_dict(_make_file())
        assert "path" not in d

    def test_restored_path_is_synthetic(self):
        f = _make_file(name="bonus.mkv")
        restored = _dict_to_file(_file_to_dict(f))
        assert restored.path == "bonus.mkv"

    def test_missing_optional_fields_use_defaults(self):
        minimal = {"name": "test.mkv"}
        restored = _dict_to_file(minimal)
        assert restored.duration_seconds == 0
        assert restored.stream_fingerprint == ""
        assert restored.chapter_durations == []
        assert restored.title_tag is None
        assert restored.organized_tag is None
        assert restored.perceptual_hash is None


# ---------------------------------------------------------------------------
# save / load round-trip
# ---------------------------------------------------------------------------

class TestSaveLoad:
    def test_save_creates_valid_json(self, tmp_path, monkeypatch):
        discs = _make_discs()
        monkeypatch.setattr("riplex.snapshot.scan_folder", lambda _: discs)

        out = tmp_path / "test.snapshot.json"
        save(Path("/fake/folder"), out)

        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["snapshot_version"] == SNAPSHOT_VERSION
        assert "created" in data
        assert data["source_folder"] == str(Path("/fake/folder"))
        assert len(data["groups"]) == 2
        assert len(data["groups"][0]["files"]) == 2
        assert len(data["groups"][1]["files"]) == 1

    def test_load_returns_scanned_discs(self, tmp_path, monkeypatch):
        discs = _make_discs()
        monkeypatch.setattr("riplex.snapshot.scan_folder", lambda _: discs)

        out = tmp_path / "test.snapshot.json"
        save(Path("/fake/folder"), out)
        loaded = load(out)

        assert len(loaded) == 2
        assert loaded[0].folder_name == "Movie Title"
        assert len(loaded[0].files) == 2
        assert loaded[0].files[0].duration_seconds == 7200
        assert loaded[0].files[1].duration_seconds == 180
        assert loaded[1].folder_name == "Special Features"

    def test_load_preserves_metadata(self, tmp_path, monkeypatch):
        discs = _make_discs()
        monkeypatch.setattr("riplex.snapshot.scan_folder", lambda _: discs)

        out = tmp_path / "test.snapshot.json"
        save(Path("/fake/folder"), out)
        loaded = load(out)

        f = loaded[0].files[0]
        assert f.stream_fingerprint == "hevc:3840x2160|truehd:eng:8ch|sub:eng|sub:spa"
        assert f.chapter_count == 28
        assert f.chapter_durations == [300] * 28
        assert f.title_tag == "My Movie"
        assert f.max_width == 3840
        assert f.max_height == 2160

    def test_load_rejects_wrong_version(self, tmp_path):
        data = {
            "snapshot_version": 999,
            "created": "2025-01-01",
            "source_folder": "/fake",
            "groups": [],
        }
        out = tmp_path / "bad.json"
        out.write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(ValueError, match="Unsupported snapshot version"):
            load(out)


# ---------------------------------------------------------------------------
# capture_from_scanned / save_from_scanned (no rescan)
# ---------------------------------------------------------------------------

class TestFromScanned:
    def test_capture_from_scanned_matches_capture(self, monkeypatch):
        discs = _make_discs()
        monkeypatch.setattr("riplex.snapshot.scan_folder", lambda _: discs)

        via_scan = capture(Path("/fake/folder"))
        via_pre = capture_from_scanned(Path("/fake/folder"), discs)

        # Same structure except timestamp
        assert via_scan["snapshot_version"] == via_pre["snapshot_version"]
        assert via_scan["source_folder"] == via_pre["source_folder"]
        assert len(via_scan["groups"]) == len(via_pre["groups"])
        for g1, g2 in zip(via_scan["groups"], via_pre["groups"]):
            assert g1["folder_name"] == g2["folder_name"]
            assert len(g1["files"]) == len(g2["files"])

    def test_save_from_scanned_creates_loadable_file(self, tmp_path):
        discs = _make_discs()
        out = tmp_path / "test.snapshot.json"
        save_from_scanned(Path("/fake/folder"), discs, out)

        loaded = load(out)
        assert len(loaded) == 2
        assert loaded[0].folder_name == "Movie Title"
        assert len(loaded[0].files) == 2

    def test_save_from_scanned_does_not_call_scan(self, tmp_path, monkeypatch):
        """Confirm save_from_scanned never invokes scan_folder."""
        def boom(_):
            raise AssertionError("scan_folder should not be called")
        monkeypatch.setattr("riplex.snapshot.scan_folder", boom)

        discs = _make_discs()
        out = tmp_path / "no_scan.snapshot.json"
        save_from_scanned(Path("/fake/folder"), discs, out)

        assert out.exists()
        loaded = load(out)
        assert len(loaded) == 2


# ---------------------------------------------------------------------------
# Debug directory
# ---------------------------------------------------------------------------

class TestGetDebugDir:
    def test_creates_directory(self, tmp_path):
        debug_dir = get_debug_dir(tmp_path / "Movie (2024)")
        assert debug_dir.exists()
        assert debug_dir.name == "_riplex"

    def test_creates_readme(self, tmp_path):
        debug_dir = get_debug_dir(tmp_path / "Movie (2024)")
        readme = debug_dir / "README.txt"
        assert readme.exists()
        text = readme.read_text(encoding="utf-8")
        assert "bug report" in text.lower()
        assert "github.com" in text

    def test_idempotent(self, tmp_path):
        base = tmp_path / "Movie (2024)"
        d1 = get_debug_dir(base)
        d2 = get_debug_dir(base)
        assert d1 == d2

    def test_does_not_overwrite_readme(self, tmp_path):
        debug_dir = get_debug_dir(tmp_path / "Movie (2024)")
        readme = debug_dir / "README.txt"
        readme.write_text("custom", encoding="utf-8")
        get_debug_dir(tmp_path / "Movie (2024)")
        assert readme.read_text(encoding="utf-8") == "custom"


class TestCopyDebugLog:
    def test_copies_existing_log(self, tmp_path, monkeypatch):
        # Create a fake log file
        fake_tmp = tmp_path / "tmp"
        fake_tmp.mkdir()
        log_dir = fake_tmp / "riplex"
        log_dir.mkdir()
        log_file = log_dir / "riplex.log"
        log_file.write_text("test log content", encoding="utf-8")

        monkeypatch.setattr("tempfile.gettempdir", lambda: str(fake_tmp))

        debug_dir = tmp_path / "_riplex"
        debug_dir.mkdir()
        result = copy_debug_log(debug_dir)

        assert result is not None
        assert result.exists()
        assert result.read_text(encoding="utf-8") == "test log content"

    def test_returns_none_when_no_log(self, tmp_path, monkeypatch):
        fake_tmp = tmp_path / "empty_tmp"
        fake_tmp.mkdir()
        monkeypatch.setattr("tempfile.gettempdir", lambda: str(fake_tmp))

        debug_dir = tmp_path / "_riplex"
        debug_dir.mkdir()
        result = copy_debug_log(debug_dir)
        assert result is None


# ---------------------------------------------------------------------------
# V2 rip snapshot
# ---------------------------------------------------------------------------

def _make_disc_info():
    """Create a minimal disc_info-like object for testing."""
    from dataclasses import dataclass, field

    @dataclass
    class FakeTitle:
        index: int = 0
        duration_seconds: int = 7200
        resolution: str = "3840x2160"
        size_bytes: int = 50_000_000_000
        chapters: int = 28

    @dataclass
    class FakeDiscInfo:
        disc_name: str = "TEST_DISC"
        titles: list = field(default_factory=lambda: [
            FakeTitle(index=0, duration_seconds=7200),
            FakeTitle(index=1, duration_seconds=300, resolution="1920x1080", size_bytes=500_000_000, chapters=0),
        ])

    return FakeDiscInfo()


class TestSaveRipSnapshot:
    def test_writes_valid_v2_json(self, tmp_path):
        debug_dir = tmp_path / "_riplex"
        debug_dir.mkdir()
        disc_info = _make_disc_info()

        result = save_rip_snapshot(
            debug_dir, disc_info,
            canonical="Test Movie", year=2024, is_movie=True,
            movie_runtime=7200, release_name="Test Release",
            ripped_titles=[0, 1],
        )

        assert result is not None
        data = json.loads(result.read_text(encoding="utf-8"))
        assert data["snapshot_version"] == SNAPSHOT_VERSION_V2
        assert data["type"] == "rip"
        assert "created" in data
        assert "riplex_version" in data
        assert "platform" in data
        assert data["data"]["disc_name"] == "TEST_DISC"
        assert data["data"]["title_count"] == 2
        assert data["data"]["tmdb"]["canonical_title"] == "Test Movie"
        assert data["data"]["ripped_titles"] == [0, 1]

    def test_filename(self, tmp_path):
        debug_dir = tmp_path / "_riplex"
        debug_dir.mkdir()
        result = save_rip_snapshot(debug_dir, _make_disc_info())
        assert result.name == "riplex-rip.snapshot.json"


class TestSaveRipManifest:
    def test_writes_valid_json(self, tmp_path):
        debug_dir = tmp_path / "_riplex"
        debug_dir.mkdir()
        manifest = {"title": "Test", "year": 2024, "files": []}

        result = save_rip_manifest(debug_dir, manifest)

        assert result is not None
        data = json.loads(result.read_text(encoding="utf-8"))
        assert data["title"] == "Test"
        assert result.name == "riplex-rip.manifest.json"


class TestSaveScanSnapshot:
    def test_writes_valid_v2_json(self, tmp_path):
        debug_dir = tmp_path / "_riplex"
        debug_dir.mkdir()
        discs = _make_discs()

        result = save_scan_snapshot(debug_dir, Path("/fake/folder"), discs)

        assert result is not None
        data = json.loads(result.read_text(encoding="utf-8"))
        assert data["snapshot_version"] == SNAPSHOT_VERSION_V2
        assert data["type"] == "scan"
        assert data["data"]["source_folder"] == str(Path("/fake/folder"))
        assert len(data["data"]["groups"]) == 2

    def test_loadable_as_scanned_discs(self, tmp_path):
        debug_dir = tmp_path / "_riplex"
        debug_dir.mkdir()
        discs = _make_discs()

        result = save_scan_snapshot(debug_dir, Path("/fake/folder"), discs)
        loaded = load(result)

        assert len(loaded) == 2
        assert loaded[0].folder_name == "Movie Title"
        assert len(loaded[0].files) == 2

    def test_filename(self, tmp_path):
        debug_dir = tmp_path / "_riplex"
        debug_dir.mkdir()
        result = save_scan_snapshot(debug_dir, Path("/fake"), _make_discs())
        assert result.name == "riplex-scan.snapshot.json"


class TestLoadV2:
    def test_load_rejects_rip_type(self, tmp_path):
        """Rip snapshots can't be loaded as ScannedDisc lists."""
        debug_dir = tmp_path / "_riplex"
        debug_dir.mkdir()
        save_rip_snapshot(debug_dir, _make_disc_info())
        rip_snap = debug_dir / "riplex-rip.snapshot.json"

        with pytest.raises(ValueError, match="Cannot load snapshot type"):
            load(rip_snap)

    def test_load_v2_scan_round_trip(self, tmp_path):
        debug_dir = tmp_path / "_riplex"
        debug_dir.mkdir()
        discs = _make_discs()
        save_scan_snapshot(debug_dir, Path("/fake"), discs)

        loaded = load(debug_dir / "riplex-scan.snapshot.json")
        assert len(loaded) == 2
        assert loaded[0].files[0].duration_seconds == 7200


class TestOrganizedMarker:
    def test_save_and_load(self, tmp_path):
        save_organized_marker(
            tmp_path, title="Test Movie", file_count=3, output_root="/out"
        )
        marker = load_organized_marker(tmp_path)
        assert marker is not None
        assert marker.title == "Test Movie"
        assert marker.file_count == 3
        assert marker.output_root == "/out"
        assert marker.organized_at  # non-empty timestamp

    def test_load_returns_none_when_missing(self, tmp_path):
        assert load_organized_marker(tmp_path) is None

    def test_load_returns_none_for_corrupt_json(self, tmp_path):
        debug_dir = tmp_path / "_riplex"
        debug_dir.mkdir()
        (debug_dir / "organized.json").write_text("not json", encoding="utf-8")
        assert load_organized_marker(tmp_path) is None

    def test_save_creates_debug_dir(self, tmp_path):
        save_organized_marker(tmp_path, title="X")
        assert (tmp_path / "_riplex" / "organized.json").is_file()
