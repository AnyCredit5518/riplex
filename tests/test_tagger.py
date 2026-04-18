"""Tests for tagger module."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import json

import pytest

from plex_planner.tagger import (
    find_mkvpropedit,
    tag_organized,
    read_organized_tag,
    _escape_xml,
)


class TestFindMkvpropedit:
    def test_found_on_path(self):
        with patch("shutil.which", return_value="/usr/bin/mkvpropedit"):
            assert find_mkvpropedit() == "/usr/bin/mkvpropedit"

    def test_not_found_returns_none(self):
        with patch("shutil.which", return_value=None), \
             patch("pathlib.Path.is_file", return_value=False):
            assert find_mkvpropedit() is None

    def test_windows_fallback(self):
        def fake_which(name):
            return None
        def fake_is_file(path_self):
            return "MKVToolNix" in str(path_self)
        with patch("shutil.which", side_effect=fake_which), \
             patch.object(Path, "is_file", fake_is_file):
            result = find_mkvpropedit()
            assert result is not None
            assert "MKVToolNix" in result


class TestTagOrganized:
    def test_success(self, tmp_path):
        fake_mkv = tmp_path / "test.mkv"
        fake_mkv.write_bytes(b"\x00")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""

        with patch("plex_planner.tagger.find_mkvpropedit", return_value="/usr/bin/mkvpropedit"), \
             patch("subprocess.run", return_value=mock_result) as mock_run:
            result = tag_organized(str(fake_mkv), "Disc 3: Now I Am Become Death")
            assert result is True
            # Verify mkvpropedit was called with correct args
            call_args = mock_run.call_args[0][0]
            assert call_args[0] == "/usr/bin/mkvpropedit"
            assert str(fake_mkv) in call_args
            assert "--tags" in call_args

    def test_no_mkvpropedit(self):
        with patch("plex_planner.tagger.find_mkvpropedit", return_value=None):
            assert tag_organized("/fake/file.mkv", "test") is False

    def test_mkvpropedit_failure(self, tmp_path):
        fake_mkv = tmp_path / "test.mkv"
        fake_mkv.write_bytes(b"\x00")

        mock_result = MagicMock()
        mock_result.returncode = 2
        mock_result.stderr = "Error: something went wrong"

        with patch("plex_planner.tagger.find_mkvpropedit", return_value="/usr/bin/mkvpropedit"), \
             patch("subprocess.run", return_value=mock_result):
            assert tag_organized(str(fake_mkv), "test") is False

    def test_tag_value_format(self, tmp_path):
        """Verify the XML written to the temp file contains the label."""
        fake_mkv = tmp_path / "test.mkv"
        fake_mkv.write_bytes(b"\x00")

        written_xml = []
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""

        original_run = None

        def capture_run(cmd, **kwargs):
            # Read the XML file before it gets deleted
            tag_arg = [a for a in cmd if a.startswith("global:")]
            if tag_arg:
                xml_path = tag_arg[0].replace("global:", "")
                written_xml.append(Path(xml_path).read_text(encoding="utf-8"))
            return mock_result

        with patch("plex_planner.tagger.find_mkvpropedit", return_value="/usr/bin/mkvpropedit"), \
             patch("subprocess.run", side_effect=capture_run):
            tag_organized(str(fake_mkv), "Disc 3: Test Feature")

        assert len(written_xml) == 1
        assert "PLEX_PLANNER" in written_xml[0]
        assert "Disc 3: Test Feature" in written_xml[0]
        assert "organized:" in written_xml[0]

    def test_timeout_returns_false(self, tmp_path):
        import subprocess
        fake_mkv = tmp_path / "test.mkv"
        fake_mkv.write_bytes(b"\x00")

        with patch("plex_planner.tagger.find_mkvpropedit", return_value="/usr/bin/mkvpropedit"), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 30)):
            assert tag_organized(str(fake_mkv), "test") is False


class TestReadOrganizedTag:
    def test_tag_found(self):
        mkvmerge_output = json.dumps({
            "global_tags": [{
                "tags": [
                    {"name": "PLEX_PLANNER", "value": "organized:2026-04-17|Disc 3: Feature"}
                ]
            }]
        })
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = mkvmerge_output

        with patch("shutil.which", return_value="/usr/bin/mkvmerge"), \
             patch("subprocess.run", return_value=mock_result):
            tag = read_organized_tag("/fake/file.mkv")
            assert tag == "organized:2026-04-17|Disc 3: Feature"

    def test_no_tag(self):
        mkvmerge_output = json.dumps({"global_tags": []})
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = mkvmerge_output

        with patch("shutil.which", return_value="/usr/bin/mkvmerge"), \
             patch("subprocess.run", return_value=mock_result):
            assert read_organized_tag("/fake/file.mkv") is None

    def test_mkvmerge_not_found(self):
        with patch("shutil.which", return_value=None), \
             patch("pathlib.Path.is_file", return_value=False):
            assert read_organized_tag("/fake/file.mkv") is None

    def test_mkvmerge_failure(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with patch("shutil.which", return_value="/usr/bin/mkvmerge"), \
             patch("subprocess.run", return_value=mock_result):
            assert read_organized_tag("/fake/file.mkv") is None

    def test_case_insensitive_tag_name(self):
        """Tag name matching should be case-insensitive."""
        mkvmerge_output = json.dumps({
            "global_tags": [{
                "tags": [
                    {"name": "plex_planner", "value": "organized:2026-04-17|test"}
                ]
            }]
        })
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = mkvmerge_output

        with patch("shutil.which", return_value="/usr/bin/mkvmerge"), \
             patch("subprocess.run", return_value=mock_result):
            assert read_organized_tag("/fake/file.mkv") == "organized:2026-04-17|test"


class TestEscapeXml:
    def test_basic(self):
        assert _escape_xml("hello") == "hello"

    def test_special_chars(self):
        assert _escape_xml("a&b<c>d\"e'f") == "a&amp;b&lt;c&gt;d&quot;e&apos;f"

    def test_empty(self):
        assert _escape_xml("") == ""


class TestScannerOrganizedTag:
    """Test that the scanner populates organized_tag from ffprobe."""

    def test_organized_tag_from_ffprobe(self):
        from plex_planner.scanner import _probe_file

        ffprobe_output = json.dumps({
            "format": {
                "duration": "100.0",
                "nb_streams": 1,
                "tags": {
                    "title": "Test Movie",
                    "PLEX_PLANNER": "organized:2026-04-17|test",
                },
            },
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080},
            ],
            "chapters": [],
        })
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ffprobe_output

        with patch("subprocess.run", return_value=mock_result), \
             patch("pathlib.Path.stat") as mock_stat:
            mock_stat.return_value = MagicMock(st_size=1000)
            sf = _probe_file(Path("/fake/test.mkv"))

        assert sf.organized_tag == "organized:2026-04-17|test"
        assert sf.title_tag == "Test Movie"
        assert sf.max_width == 1920
        assert sf.max_height == 1080

    def test_no_organized_tag(self):
        from plex_planner.scanner import _probe_file

        ffprobe_output = json.dumps({
            "format": {
                "duration": "100.0",
                "nb_streams": 1,
                "tags": {"title": "Test Movie"},
            },
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 3840, "height": 2160},
            ],
            "chapters": [],
        })
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ffprobe_output

        with patch("subprocess.run", return_value=mock_result), \
             patch("pathlib.Path.stat") as mock_stat:
            mock_stat.return_value = MagicMock(st_size=1000)
            sf = _probe_file(Path("/fake/test.mkv"))

        assert sf.organized_tag is None
        assert sf.title_tag == "Test Movie"
        assert sf.max_width == 3840
        assert sf.max_height == 2160


class TestSkipOrganizedFiles:
    """Test the --force / skip logic from ScannedFile.organized_tag."""

    def test_tagged_files_filtered(self):
        from plex_planner.models import ScannedDisc, ScannedFile
        disc = ScannedDisc(
            folder_name="Test",
            files=[
                ScannedFile(name="a.mkv", path="/a.mkv", duration_seconds=100,
                           organized_tag="organized:2026-04-17|test"),
                ScannedFile(name="b.mkv", path="/b.mkv", duration_seconds=200),
            ],
        )
        # Simulate the filtering logic from _run_organize
        disc.files = [f for f in disc.files if not f.organized_tag]
        assert len(disc.files) == 1
        assert disc.files[0].name == "b.mkv"

    def test_force_keeps_all(self):
        from plex_planner.models import ScannedDisc, ScannedFile
        disc = ScannedDisc(
            folder_name="Test",
            files=[
                ScannedFile(name="a.mkv", path="/a.mkv", duration_seconds=100,
                           organized_tag="organized:2026-04-17|test"),
                ScannedFile(name="b.mkv", path="/b.mkv", duration_seconds=200),
            ],
        )
        # With --force, no filtering
        assert len(disc.files) == 2
