"""Tests for makemkv module (makemkvcon output parser)."""

from pathlib import Path

from plex_planner.makemkv import parse_disc_info, parse_drive_list

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
