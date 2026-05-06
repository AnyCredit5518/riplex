"""Tests for disc_analysis module."""

from riplex.disc.analysis import (
    _detect_edition_name,
    analyze_disc,
    build_dvd_entries,
    classify_title,
    detect_cross_res_play_all,
    detect_play_all,
    find_duration_match,
    format_seconds,
    is_skip_title,
)
from riplex.disc.provider import detect_disc_number as _detect_disc_number
from riplex.disc.makemkv import DiscInfo, DiscTitle


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


class TestDetectEditionName:
    def test_theatrical_cut_from_dvdcompare(self):
        entries = [("The Film - Theatrical Cut (2160p)", 0, "film"), ("The Film - Extended Cut (2160p)", 0, "film")]
        result = _detect_edition_name(7200, entries, edition_hint="theatrical")
        assert result == "Theatrical Cut"

    def test_extended_cut_from_dvdcompare(self):
        entries = [("The Film - Theatrical Cut (2160p)", 0, "film"), ("The Film - Extended Cut (2160p)", 0, "film")]
        result = _detect_edition_name(8000, entries, edition_hint="extended")
        assert result == "Extended Cut"

    def test_directors_cut(self):
        entries = [("The Film - Director's Cut", 0, "film")]
        result = _detect_edition_name(7200, entries)
        assert result == "Director's Cut"

    def test_no_edition_entries(self):
        entries = [("Behind the Scenes", 1200, "featurette")]
        result = _detect_edition_name(7200, entries)
        assert result is None

    def test_runtime_mismatch_skipped(self):
        entries = [("The Film - Extended Cut (2160p)", 5000, "film")]
        result = _detect_edition_name(7200, entries)
        assert result is None

    def test_zero_runtime_matches(self):
        entries = [("The Film - Extended Cut (2160p)", 0, "film")]
        result = _detect_edition_name(7200, entries)
        assert result == "Extended Cut"


class TestClassifyTitleEditions:
    def test_main_film_theatrical_edition(self):
        t = _make_title(0, 7200)
        entries = [("The Film - Theatrical Cut (2160p)", 0, "film"), ("The Film - Extended Cut (2160p)", 0, "film")]
        result = classify_title(t, [t], entries, True, 7200, 0, 0)
        assert "Theatrical Cut" in result
        assert "rip this" in result

    def test_extended_cut_detected(self):
        theatrical = _make_title(0, 7200)
        extended = _make_title(1, 7900)
        entries = [("The Film - Theatrical Cut (2160p)", 0, "film"), ("The Film - Extended Cut (2160p)", 0, "film")]
        result = classify_title(extended, [theatrical, extended], entries, True, 7200, 0, 0)
        assert "Extended Cut" in result
        assert "rip this" in result

    def test_extended_cut_fallback_no_dvdcompare(self):
        theatrical = _make_title(0, 7200)
        extended = _make_title(1, 7900)
        result = classify_title(extended, [theatrical, extended], [], True, 7200, 0, 0)
        assert "Extended Cut" in result
        assert "rip this" in result

    def test_not_extended_if_too_long(self):
        """A title >60min longer than theatrical should not be labeled extended."""
        theatrical = _make_title(0, 7200)
        too_long = _make_title(1, 11000)  # 3800s longer, > 3600 limit
        result = classify_title(too_long, [theatrical, too_long], [], True, 7200, 0, 0)
        assert "Extended Cut" not in result


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


class TestAnalyzeDisc:
    """Tests for the analyze_disc() shared entry point."""

    def _make_fake_disc(self, number, ep_runtimes, extra_runtimes=None):
        class FakeEp:
            def __init__(self, title, runtime):
                self.title = title
                self.runtime_seconds = runtime

        class FakeExtra:
            def __init__(self, title, runtime, feature_type="extra"):
                self.title = title
                self.runtime_seconds = runtime
                self.feature_type = feature_type

        class FakeDisc:
            def __init__(self, num, eps, extras):
                self.number = num
                self.episodes = eps
                self.extras = extras
                self.disc_format = "Blu-ray"

        eps = [FakeEp(f"Ep {i+1}", rt) for i, rt in enumerate(ep_runtimes)]
        extras = [FakeExtra(f"Extra {i+1}", rt) for i, rt in enumerate(extra_runtimes or [])]
        return FakeDisc(number, eps, extras)

    def test_filters_to_detected_disc(self):
        """When disc detection succeeds, only that disc's entries are used."""
        disc1 = self._make_fake_disc(1, [3600, 3700])
        disc2 = self._make_fake_disc(2, [2400, 2500])
        titles = [_make_title(0, 3600), _make_title(1, 3700)]
        info = DiscInfo(disc_name="SHOW_D1", disc_type="Blu-ray disc", titles=titles)

        analysis = analyze_disc(info, [disc1, disc2], is_movie=False)

        # Should detect disc 1 from label "SHOW_D1"
        assert analysis.disc_number == 1
        # Should only have entries from disc 1 (2 episodes)
        assert analysis.episode_count == 2
        assert analysis.total_episode_runtime == 3600 + 3700

    def test_explicit_disc_number_skips_detection(self):
        """When disc_number is provided, detection is skipped."""
        disc1 = self._make_fake_disc(1, [3600])
        disc2 = self._make_fake_disc(2, [2400, 2500])
        titles = [_make_title(0, 2400), _make_title(1, 2500)]
        info = DiscInfo(disc_name="MYSTERY", disc_type="Blu-ray disc", titles=titles)

        analysis = analyze_disc(info, [disc1, disc2], disc_number=2, is_movie=False)

        assert analysis.disc_number == 2
        assert analysis.episode_count == 2
        assert analysis.total_episode_runtime == 2400 + 2500

    def test_multi_disc_detection_fails_uses_empty(self):
        """When detection fails on multi-disc, empty entries are used (not all discs)."""
        disc1 = self._make_fake_disc(1, [3600])
        disc2 = self._make_fake_disc(2, [2400])
        disc3 = self._make_fake_disc(3, [], extra_runtimes=[300, 400])
        # Titles don't match any disc's episodes, label doesn't help
        titles = [_make_title(0, 900), _make_title(1, 1100)]
        info = DiscInfo(disc_name="BONUS_DISC", disc_type="Blu-ray disc", titles=titles)

        analysis = analyze_disc(info, [disc1, disc2, disc3], is_movie=True, movie_runtime=7200)

        # Detection should fail
        assert analysis.disc_number is None
        # Should use empty entries (not 3 discs worth of data)
        assert analysis.dvd_entries == []
        assert analysis.episode_count == 0

    def test_single_disc_detection_fails_uses_all(self):
        """When detection fails on single-disc release, all entries are used."""
        disc1 = self._make_fake_disc(1, [3600, 3700])
        titles = [_make_title(0, 7200)]  # Doesn't match episodes
        info = DiscInfo(disc_name="MYSTERY", disc_type="Blu-ray disc", titles=titles)

        analysis = analyze_disc(info, [disc1], is_movie=True, movie_runtime=7200)

        # Detection may fail but single disc => use its entries
        assert analysis.episode_count == 2

    def test_no_dvdcompare_data(self):
        """Works with empty dvdcompare_discs."""
        titles = [_make_title(0, 7200), _make_title(1, 300)]
        info = DiscInfo(disc_name="MOVIE", disc_type="Blu-ray disc", titles=titles)

        analysis = analyze_disc(info, [], is_movie=True, movie_runtime=7200)

        assert analysis.disc_number is None
        assert analysis.dvd_entries == []
        # Should still classify titles (main film detected by runtime)
        assert len(analysis.rippable_titles) >= 1
        assert len(analysis.classifications) == 2
