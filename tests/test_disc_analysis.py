"""Tests for disc_analysis module."""

from plex_planner.disc_analysis import (
    build_dvd_entries,
    classify_title,
    detect_cross_res_play_all,
    detect_play_all,
    find_duration_match,
    format_seconds,
    is_skip_title,
)
from plex_planner.cli import _detect_disc_number
from plex_planner.makemkv import DiscInfo, DiscTitle


def _make_title(index, duration, resolution="3840x2160", chapters=6, size=20_000_000_000, segments=1):
    return DiscTitle(
        index=index,
        name=f"Title {index}",
        duration_seconds=duration,
        chapters=chapters,
        size_bytes=size,
        filename=f"title_t{index:02d}.mkv",
        playlist=f"000{index:02d}.mpls",
        resolution=resolution,
        video_codec="MpegH" if "3840" in resolution else "Mpeg4",
        segment_count=segments,
    )


class TestFormatSeconds:
    def test_minutes_only(self):
        assert format_seconds(125) == "2:05"

    def test_hours(self):
        assert format_seconds(3661) == "1:01:01"

    def test_zero(self):
        assert format_seconds(0) == "0:00"


class TestFindDurationMatch:
    def test_exact_match(self):
        entries = [("Ep 1", 3000, "episode"), ("Ep 2", 3100, "episode")]
        result = find_duration_match(3000, entries)
        assert result == ("Ep 1", 3000, "episode")

    def test_within_tolerance(self):
        entries = [("Ep 1", 3000, "episode")]
        result = find_duration_match(3020, entries)
        assert result == ("Ep 1", 3000, "episode")

    def test_beyond_tolerance(self):
        entries = [("Ep 1", 3000, "episode")]
        result = find_duration_match(3050, entries)
        assert result is None

    def test_empty_entries(self):
        assert find_duration_match(3000, []) is None


class TestDetectPlayAll:
    def test_detects_play_all(self):
        t1 = _make_title(1, 3000)
        t2 = _make_title(2, 3100)
        t3 = _make_title(3, 3050)
        play_all = _make_title(4, 9150, chapters=18, segments=3)
        result = detect_play_all(play_all, [t1, t2, t3, play_all])
        assert result is not None
        assert len(result) == 3

    def test_not_play_all_when_short(self):
        t1 = _make_title(1, 100)
        result = detect_play_all(t1, [t1])
        assert result is None

    def test_not_play_all_different_res(self):
        t1 = _make_title(1, 3000, resolution="1920x1080")
        t2 = _make_title(2, 3100, resolution="1920x1080")
        play_all = _make_title(3, 6100, resolution="3840x2160")
        result = detect_play_all(play_all, [t1, t2, play_all])
        assert result is None  # different resolution


class TestDetectCrossResPlayAll:
    def test_detects_cross_res(self):
        t1 = _make_title(1, 3000, resolution="3840x2160")
        t2 = _make_title(2, 3100, resolution="3840x2160")
        play_all = _make_title(3, 6100, resolution="1920x1080")
        result = detect_cross_res_play_all(play_all, [t1, t2, play_all])
        assert result is not None
        assert len(result) == 2


class TestClassifyTitle:
    def test_main_film(self):
        t = _make_title(0, 7200)
        result = classify_title(t, [t], [], True, 7200, 0, 0)
        assert "MAIN FILM" in result

    def test_episode_fallback(self):
        t1 = _make_title(1, 3000)
        t2 = _make_title(2, 3100)
        result = classify_title(t1, [t1, t2], [], False, None, 0, 0)
        assert "Episode" in result

    def test_short_skip(self):
        t = _make_title(0, 60)
        result = classify_title(t, [t], [], False, None, 0, 0)
        assert "Very short" in result

    def test_dvdcompare_match(self):
        t = _make_title(0, 3000)
        entries = [("Frozen Worlds", 3000, "episode")]
        result = classify_title(t, [t], entries, False, None, 0, 0)
        assert "Frozen Worlds" in result

    def test_play_all_internal(self):
        t1 = _make_title(1, 3000)
        t2 = _make_title(2, 3100)
        play_all = _make_title(3, 6100, chapters=12, segments=2)
        result = classify_title(play_all, [t1, t2, play_all], [], False, None, 0, 0)
        assert "Play-all" in result
        assert "skip" in result.lower()


class TestIsSkipTitle:
    def test_skip_short(self):
        t = _make_title(0, 60)
        assert is_skip_title(t, [t], False, None, 0, 0) is True

    def test_skip_lower_res_dup(self):
        t_1080 = _make_title(0, 3000, resolution="1920x1080")
        t_4k = _make_title(1, 3000, resolution="3840x2160")
        assert is_skip_title(t_1080, [t_1080, t_4k], False, None, 0, 0) is True

    def test_keep_4k(self):
        t_4k = _make_title(0, 3000, resolution="3840x2160")
        assert is_skip_title(t_4k, [t_4k], False, None, 0, 0) is False

    def test_skip_play_all(self):
        t1 = _make_title(1, 3000)
        t2 = _make_title(2, 3100)
        play_all = _make_title(3, 6100, chapters=12, segments=2)
        assert is_skip_title(play_all, [t1, t2, play_all], False, None, 0, 0) is True

    def test_keep_individual(self):
        t1 = _make_title(1, 3000)
        t2 = _make_title(2, 3100)
        play_all = _make_title(3, 6100, chapters=12, segments=2)
        assert is_skip_title(t1, [t1, t2, play_all], False, None, 0, 0) is False


class TestBuildDvdEntries:
    def test_builds_entries(self):
        class FakeEp:
            title = "Ep 1"
            runtime_seconds = 3000

        class FakeExtra:
            title = "Behind the Scenes"
            runtime_seconds = 1200
            feature_type = "featurette"

        class FakeDisc:
            episodes = [FakeEp()]
            extras = [FakeExtra()]

        entries, total_rt, ep_count = build_dvd_entries([FakeDisc()])
        assert len(entries) == 2
        assert total_rt == 3000
        assert ep_count == 1
        assert entries[0] == ("Ep 1", 3000, "episode")
        assert entries[1] == ("Behind the Scenes", 1200, "featurette")


class TestDetectDiscNumber:
    def test_volume_label_d2(self):
        info = DiscInfo(disc_name="FROZEN_PLANET_II_D2", disc_type="Blu-ray disc")
        assert _detect_disc_number(info, []) == 2

    def test_volume_label_disc_3(self):
        info = DiscInfo(disc_name="PLANET_EARTH_III-Disc3", disc_type="Blu-ray disc")
        assert _detect_disc_number(info, []) == 3

    def test_volume_label_disc_space(self):
        info = DiscInfo(disc_name="PLANET EARTH Disc 1", disc_type="Blu-ray disc")
        assert _detect_disc_number(info, []) == 1

    def test_volume_label_no_disc(self):
        info = DiscInfo(disc_name="BLADE_RUNNER_2049", disc_type="Blu-ray disc")
        assert _detect_disc_number(info, []) is None

    def test_duration_matching(self):
        class FakeEp:
            def __init__(self, runtime):
                self.title = "Ep"
                self.runtime_seconds = runtime

        class FakeDisc:
            def __init__(self, number, runtimes):
                self.number = number
                self.episodes = [FakeEp(rt) for rt in runtimes]
                self.extras = []

        disc1 = FakeDisc(1, [3000, 3100, 3050])
        disc2 = FakeDisc(2, [2800, 2900, 2950])

        titles = [
            _make_title(0, 2810),
            _make_title(1, 2910),
            _make_title(2, 2960),
        ]
        info = DiscInfo(disc_name="MYSTERY_DISC", disc_type="Blu-ray disc", titles=titles)
        assert _detect_disc_number(info, [disc1, disc2]) == 2

    def test_duration_matching_no_match(self):
        class FakeEp:
            def __init__(self, runtime):
                self.title = "Ep"
                self.runtime_seconds = runtime

        class FakeDisc:
            def __init__(self, number, runtimes):
                self.number = number
                self.episodes = [FakeEp(rt) for rt in runtimes]
                self.extras = []

        disc1 = FakeDisc(1, [3000, 3100, 3050])
        titles = [_make_title(0, 500)]  # Very different durations
        info = DiscInfo(disc_name="MYSTERY_DISC", disc_type="Blu-ray disc", titles=titles)
        assert _detect_disc_number(info, [disc1]) is None
