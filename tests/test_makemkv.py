"""Tests for makemkv module (makemkvcon output parser)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from riplex.disc.makemkv import (
    DiscTitle,
    MakeMKVError,
    MakeMKVPreflight,
    RipResult,
    build_stream_fingerprint,
    makemkv_preflight,
    parse_disc_info,
    parse_drive_list,
    parse_fatal_message,
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

    def test_title_0_stream_count(self):
        # Stream count should be positive (at least video + audio)
        assert self.info.titles[0].stream_count > 0

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
        assert d.is_present is True
        assert d.state_label.startswith("Disc:")

    def test_empty_drives(self):
        for d in self.drives[1:]:
            assert d.has_disc is False
            assert d.disc_label == ""
            # Placeholder slots (visible == 256, no name/device) should be
            # flagged as not present so the GUI can hide them.
            assert d.is_present is False


class TestParseDriveListStates:
    """Verify per-state labels for drives with no disc / opened tray."""

    def test_empty_with_drive_present(self):
        # visible=0 (empty closed), device populated => present but no disc
        line = 'DRV:0,0,999,0,"BD-RE Drive","","E:"\n'
        drives = parse_drive_list(line)
        assert len(drives) == 1
        d = drives[0]
        assert d.is_present is True
        assert d.has_disc is False
        assert d.state_label == "Empty"

    def test_tray_open(self):
        line = 'DRV:0,1,999,0,"BD-RE Drive","","E:"\n'
        d = parse_drive_list(line)[0]
        assert d.has_disc is False
        assert d.state_label == "Tray open"


class TestParseFatalMessage:
    def test_returns_none_for_normal_output(self):
        output = (
            'MSG:1005,0,1,"MakeMKV v1.18.3 win(x64-release) started",'
            '"%1 started","MakeMKV v1.18.3 win(x64-release)"\n'
            'DRV:0,2,999,12,"BD-RE Drive","DISC_LABEL","D:"\n'
        )
        assert parse_fatal_message(output) is None

    def test_detects_expired_beta(self):
        output = (
            'MSG:1005,0,1,"MakeMKV v1.18.3 started","%1","MakeMKV v1.18.3"\n'
            'MSG:5021,131332,1,"This application version is too old.  '
            'Please download the latest version at http://www.makemkv.com/ '
            'or enter a registration key to continue using the current version.",'
            '"This application version is too old.  Please download the latest '
            'version at %1 or enter a registration key to continue using the '
            'current version.","http://www.makemkv.com/"\n'
        )
        fatal = parse_fatal_message(output)
        assert fatal is not None
        code, message = fatal
        assert code == 5021
        assert "too old" in message
        assert "makemkv.com" in message

    def test_ignores_unknown_msg_codes(self):
        output = 'MSG:9999,0,1,"some other message","%1","x"\n'
        assert parse_fatal_message(output) is None


class TestDriveListRaisesOnFatal:
    """``MakeMKV.drive_list`` should raise MakeMKVError when makemkvcon\n
    runs but emits a fatal MSG (e.g. expired beta) with zero DRV lines.\n
    """

    def test_raises_on_expired_beta(self, tmp_path):
        from riplex.disc.makemkv import MakeMKV

        fake_exe = tmp_path / "makemkvcon.exe"
        fake_exe.write_text("")
        mk = MakeMKV(fake_exe)

        fatal_output = (
            'MSG:1005,0,1,"MakeMKV v1.18.3 started","%1","MakeMKV v1.18.3"\n'
            'MSG:5021,131332,1,"This application version is too old.",'
            '"This application version is too old.",""\n'
        )

        completed = MagicMock()
        completed.stdout = fatal_output
        completed.stderr = ""
        with patch("riplex.disc.makemkv.subprocess.run", return_value=completed):
            try:
                mk.drive_list()
            except MakeMKVError as exc:
                assert exc.code == 5021
                assert "too old" in str(exc)
                return
        raise AssertionError("MakeMKVError was not raised")

    def test_returns_empty_when_no_fatal(self, tmp_path):
        from riplex.disc.makemkv import MakeMKV

        fake_exe = tmp_path / "makemkvcon.exe"
        fake_exe.write_text("")
        mk = MakeMKV(fake_exe)

        completed = MagicMock()
        completed.stdout = 'MSG:1005,0,1,"started","%1","x"\n'
        completed.stderr = ""
        with patch("riplex.disc.makemkv.subprocess.run", return_value=completed):
            assert mk.drive_list() == []


class TestMakemkvPreflight:
    def test_no_executable_found(self):
        with patch("riplex.disc.makemkv.find_makemkvcon", return_value=None):
            result = makemkv_preflight()
        assert isinstance(result, MakeMKVPreflight)
        assert result.available is False
        assert result.exe is None
        assert "not found" in result.error

    def test_executable_present_is_available(self):
        # Preflight is intentionally a path-only check now: invoking
        # makemkvcon for a banner could enumerate drives and block on a
        # spinning-up disc, falsely flagging a working install as broken.
        result = makemkv_preflight(Path("fake_makemkvcon"))
        assert result.available is True
        assert result.exe == Path("fake_makemkvcon")
        assert result.error == ""


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
    """Verify that success/failure is determined by exit code only."""

    def _make_mock_proc(self, lines, returncode=0):
        """Create a mock Popen that yields the given lines from stdout."""
        proc = MagicMock()
        proc.stdout = iter(lines)
        proc.returncode = returncode
        proc.wait = MagicMock()
        proc.kill = MagicMock()
        return proc

    @patch("riplex.disc.makemkv.subprocess.Popen")
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

    @patch("riplex.disc.makemkv.subprocess.Popen")
    def test_msg3_info_with_zero_exit_is_success(self, mock_popen, tmp_path):
        """MSG:3xxx informational messages with exit code 0 should succeed."""
        lines = [
            'MSG:3007,0,0,"Using direct disc access mode","",""',
            'MSG:3307,0,2,"File 00026.mpls was added as title #0","",""',
            'MSG:3025,0,3,"Title #00005.m2ts has length of 6 seconds","",""',
            'MSG:5011,0,0,"Operation successfully completed","",""',
            'MSG:5036,0,1,"Copy complete. 1 titles saved.","",""',
        ]
        mock_popen.return_value = self._make_mock_proc(lines, returncode=0)

        fake_mkv = tmp_path / "title_t00.mkv"
        fake_mkv.write_bytes(b"\x00" * 100)

        result = run_rip(0, 0, tmp_path, makemkvcon=Path("fake_makemkvcon"))
        assert result.success is True
        assert result.error_message == ""

    @patch("riplex.disc.makemkv.subprocess.Popen")
    def test_nonzero_exit_is_failure(self, mock_popen, tmp_path):
        """Non-zero exit code should report failure regardless of MSG codes."""
        lines = [
            'MSG:3025,0,3,"Error Scsi error - MEDIUM ERROR:NO SEEK COMPLETE","",""',
        ]
        mock_popen.return_value = self._make_mock_proc(lines, returncode=1)

        result = run_rip(0, 0, tmp_path, makemkvcon=Path("fake_makemkvcon"))
        assert result.success is False
        assert "exited with code 1" in result.error_message

    @patch("riplex.disc.makemkv.subprocess.Popen")
    def test_nonzero_exit_no_msg(self, mock_popen, tmp_path):
        """Non-zero exit with no MSG errors should still report failure."""
        lines = ['MSG:1005,0,1,"MakeMKV started","",""']
        mock_popen.return_value = self._make_mock_proc(lines, returncode=1)

        result = run_rip(0, 0, tmp_path, makemkvcon=Path("fake_makemkvcon"))
        assert result.success is False
        assert "exited with code 1" in result.error_message

    @patch("riplex.disc.makemkv.subprocess.Popen")
    def test_rip_log_written(self, mock_popen, tmp_path):
        """Per-title makemkvcon log should be written to output dir."""
        lines = [
            'MSG:1005,0,1,"MakeMKV started","",""',
            'MSG:5036,0,1,"Copy complete. 1 titles saved.","",""',
        ]
        mock_popen.return_value = self._make_mock_proc(lines, returncode=0)

        fake_mkv = tmp_path / "title_t00.mkv"
        fake_mkv.write_bytes(b"\x00" * 100)

        run_rip(0, 0, tmp_path, makemkvcon=Path("fake_makemkvcon"))

        log_file = tmp_path / "_makemkvcon_t00.log"
        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert "MakeMKV started" in content
        assert "Copy complete" in content


class TestBuildStreamFingerprint:
    def _make_title(self, **kwargs):
        defaults = dict(
            index=0, name="Test", duration_seconds=3600, chapters=10,
            size_bytes=1000000, filename="title00.mkv", playlist="00001.mpls",
            resolution="3840x2160", video_codec="MpegH",
            audio_tracks=[], subtitle_tracks=[], stream_count=1,
        )
        defaults.update(kwargs)
        return DiscTitle(**defaults)

    def test_video_only(self):
        t = self._make_title()
        assert build_stream_fingerprint(t) == "hevc:3840x2160"

    def test_with_audio_tracks(self):
        t = self._make_title(
            audio_tracks=["TrueHD English 7.1", "AC3 Spanish 5.1"],
        )
        fp = build_stream_fingerprint(t)
        assert fp.startswith("hevc:3840x2160|")
        assert "truehd:eng:8ch" in fp
        assert "ac3:spa:6ch" in fp

    def test_with_subtitles(self):
        t = self._make_title(
            subtitle_tracks=["English", "Spanish (Forced)"],
        )
        fp = build_stream_fingerprint(t)
        assert "sub:eng" in fp
        assert "sub:spa" in fp

    def test_h264_codec_mapping(self):
        t = self._make_title(video_codec="Mpeg4", resolution="1920x1080")
        fp = build_stream_fingerprint(t)
        assert fp.startswith("h264:1920x1080")

    def test_full_fingerprint(self):
        t = self._make_title(
            audio_tracks=["DTS-HD MA English 7.1"],
            subtitle_tracks=["English"],
        )
        fp = build_stream_fingerprint(t)
        parts = fp.split("|")
        assert parts[0] == "hevc:3840x2160"
        assert len(parts) == 3  # video + audio + subtitle
