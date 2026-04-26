"""Tests for makemkv module (makemkvcon output parser)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from plex_planner.makemkv import (
    RipResult,
    parse_disc_info,
    parse_drive_list,
    _parse_progress,
    _split_robot_line,
    run_rip,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestParseDiscInfo:
    def setup_method(self):
        text = (FIXTURES / "makemkvcon_frozen_planet_ii_d2.txt").read_text(encoding="utf-8")
        self.info = parse_disc_info(text)

    def test_disc_name(self):
        assert self.info.disc_name == "Frozen Planet II - Disc 2"

    def test_disc_type(self):
        assert "Blu-ray" in self.info.disc_type

    def test_title_count(self):
        assert len(self.info.titles) == 5

    def test_title_0_duration(self):
        t = self.info.titles[0]
        assert t.duration_seconds == 50 * 60 + 25  # 0:50:25

    def test_title_0_chapters(self):
        assert self.info.titles[0].chapters == 5

    def test_title_0_resolution(self):
        # Title 0 is the 1080p play-all
        assert self.info.titles[0].resolution == "1920x1080"

    def test_title_1_is_4k(self):
        assert self.info.titles[1].resolution == "3840x2160"

    def test_title_1_duration(self):
        # 0:52:20
        assert self.info.titles[1].duration_seconds == 52 * 60 + 20

    def test_title_2_duration(self):
        # 0:52:06
        assert self.info.titles[2].duration_seconds == 52 * 60 + 6

    def test_title_3_duration(self):
        # 0:51:53
        assert self.info.titles[3].duration_seconds == 51 * 60 + 53

    def test_title_4_is_play_all(self):
        t = self.info.titles[4]
        # 2:36:21 = 3 episodes combined
        assert t.duration_seconds == 2 * 3600 + 36 * 60 + 21
        assert t.chapters == 18
        assert t.segment_count == 3

    def test_title_filenames(self):
        assert self.info.titles[0].filename == "Frozen Planet II - Disc 2_t00.mkv"
        assert self.info.titles[1].filename == "Frozen Planet II - Disc 2_t01.mkv"

    def test_title_playlists(self):
        assert self.info.titles[0].playlist == "00002.mpls"
        assert self.info.titles[1].playlist == "00024.mpls"

    def test_title_size(self):
        assert self.info.titles[0].size_bytes == 12868485120

    def test_audio_tracks(self):
        # Title 1 should have multiple audio tracks
        t = self.info.titles[1]
        assert len(t.audio_tracks) >= 2
        assert any("DTS-HD MA" in a for a in t.audio_tracks)

    def test_video_codec_1080p(self):
        assert self.info.titles[0].video_codec == "Mpeg4"

    def test_video_codec_4k(self):
        assert self.info.titles[1].video_codec == "MpegH"


class TestParseDriveList:
    def setup_method(self):
        text = (FIXTURES / "makemkvcon_list.txt").read_text(encoding="utf-8")
        self.drives = parse_drive_list(text)

    def test_drive_count(self):
        assert len(self.drives) == 16

    def test_drive_0_has_disc(self):
        d = self.drives[0]
        assert d.has_disc is True
        assert d.disc_label == "FROZEN_PLANET_II_D2"
        assert d.device == "D:"

    def test_empty_drives(self):
        for d in self.drives[1:]:
            assert d.has_disc is False
            assert d.disc_label == ""


class TestParseDiscInfoEmpty:
    def test_empty_input(self):
        info = parse_disc_info("")
        assert info.disc_name == ""
        assert info.titles == []

    def test_messages_only(self):
        output = 'MSG:1005,0,1,"MakeMKV started","",""'
        info = parse_disc_info(output)
        assert info.titles == []


class TestParseProgress:
    def test_valid_line(self):
        p = _parse_progress("PRGV:100,500,1000")
        assert p is not None
        assert p.current == 100
        assert p.total == 500
        assert p.max_val == 1000

    def test_not_progress_line(self):
        assert _parse_progress("MSG:1005,0,1,\"hello\"") is None

    def test_incomplete_line(self):
        assert _parse_progress("PRGV:100") is None

    def test_non_numeric(self):
        assert _parse_progress("PRGV:abc,def,ghi") is None


class TestRunRipMsgDetection:
    """Verify that MSG:3xxx are captured as errors and MSG:5xxx are not."""

    def _make_mock_proc(self, lines, returncode=0):
        """Create a mock Popen that yields the given lines from stdout."""
        proc = MagicMock()
        proc.stdout = iter(lines)
        proc.returncode = returncode
        proc.wait = MagicMock()
        proc.kill = MagicMock()
        return proc

    @patch("plex_planner.makemkv.subprocess.Popen")
    def test_msg5_not_treated_as_error(self, mock_popen, tmp_path):
        """MSG:5xxx (info messages) should not cause failure."""
        lines = [
            'MSG:5038,0,1,"Evaluation version, 17 day(s) out of 30 remaining","",""',
            'MSG:5039,0,1,"Loaded content hash table","",""',
            'MSG:5005,0,0,"Operation successfully completed","",""',
            'MSG:5011,16,1,"Saving 1 titles into directory","",""',
            'MSG:5036,0,1,"1 titles saved","",""',
            'MSG:5037,0,1,"Copy complete. 1 titles saved.","",""',
        ]
        mock_popen.return_value = self._make_mock_proc(lines, returncode=0)

        # Create a fake output MKV so run_rip finds it
        fake_mkv = tmp_path / "title_t00.mkv"
        fake_mkv.write_bytes(b"\x00" * 100)

        result = run_rip(0, 0, tmp_path, makemkvcon=Path("fake_makemkvcon"))
        assert result.success is True
        assert result.error_message == ""
        assert result.output_file == str(fake_mkv)

    @patch("plex_planner.makemkv.subprocess.Popen")
    def test_msg3_treated_as_error(self, mock_popen, tmp_path):
        """MSG:3xxx (real errors) should cause failure."""
        lines = [
            'MSG:3025,0,3,"Error Scsi error - MEDIUM ERROR:NO SEEK COMPLETE","",""',
        ]
        mock_popen.return_value = self._make_mock_proc(lines, returncode=1)

        result = run_rip(0, 0, tmp_path, makemkvcon=Path("fake_makemkvcon"))
        assert result.success is False
        assert "Scsi error" in result.error_message

    @patch("plex_planner.makemkv.subprocess.Popen")
    def test_nonzero_exit_no_msg(self, mock_popen, tmp_path):
        """Non-zero exit with no MSG errors should still report failure."""
        lines = ['MSG:1005,0,1,"MakeMKV started","",""']
        mock_popen.return_value = self._make_mock_proc(lines, returncode=1)

        result = run_rip(0, 0, tmp_path, makemkvcon=Path("fake_makemkvcon"))
        assert result.success is False
        assert "exited with code 1" in result.error_message
