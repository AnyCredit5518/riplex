"""Tests for disc_analysis module."""

from riplex.disc.analysis import (
    _detect_edition_name,
    analyze_disc,
    build_dvd_entries,
    build_season_labels,
    classify_title,
    collect_tmdb_episodes_for_disc,
    detect_bonus_films,
    detect_cross_res_play_all,
    detect_play_all,
    enrich_dvd_entries_with_tmdb,
    find_duration_match,
    format_seconds,
    group_for_disc,
    group_release_discs,
    is_skip_title,
    parse_season_number,
)
from riplex.disc.provider import detect_disc_number as _detect_disc_number
from riplex.disc.makemkv import DiscInfo, DiscTitle
from riplex.models import DiscGroup, FilmSlot, PlannedDisc, PlannedEpisode, PlannedExtra


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

    def test_unmatched_when_longer_than_longest_episode(self):
        """Psych S1 D2 pattern: a ~85 min title with no dvdcompare
        match is a partial-season play-all (2 episodes concatenated),
        NOT a normal ~43 min episode. Must not fall through to the
        "Episode" fallback since dvdcompare has no per-play-all
        duration to match it against.
        """
        # Five ~43 min episodes on the disc.
        episodes = [_make_title(i, 2590) for i in range(5)]
        # The mystery ~85 min title (episodes 1+2 back-to-back).
        partial_play_all = _make_title(5, 5103)
        dvd_entries = [
            ("Spellingg Bee", 2588, "episode"),
            ("Speak Now or Forever Hold Your Piece", 2566, "episode"),
            ("Woman Seeking Dead Husband", 2542, "episode"),
            ("9 Lives", 2591, "episode"),
            ("Weekend Warriors", 2587, "episode"),
        ]
        total = sum(rt for _, rt, _ in dvd_entries)
        result = classify_title(
            partial_play_all, [*episodes, partial_play_all],
            dvd_entries, False, None, total, 5,
        )
        assert "Unmatched content" in result
        assert "Episode" not in result

    def test_still_labeled_episode_when_within_bounds(self):
        """Regression guard: a title whose duration is within the
        episode range must still fall through to the "Episode" label,
        even when there's no direct dvdcompare match (some episodes
        may have small runtime discrepancies that miss the 30s
        find_duration_match window).
        """
        episodes = [_make_title(i, 2590) for i in range(4)]
        # Slightly off from every entry but still within episode range.
        odd_one = _make_title(5, 2700)
        dvd_entries = [
            (f"Episode {i}", 2590, "episode") for i in range(4)
        ]
        result = classify_title(
            odd_one, [*episodes, odd_one],
            dvd_entries, False, None, 4 * 2590, 4,
        )
        assert "Episode" in result

    def test_sequential_walk_assigns_episodes_in_dvdcompare_order(self):
        """Psych S1 D2 mis-assignment case: with pure duration matching
        the 5 near-identical episodes get labeled by whichever
        dvdcompare entry happens to be nearest in seconds, so the same
        episode name can appear on two different disc titles and the
        actual disc-order ("Spellingg Bee" first) is lost. The
        sequential walk consumes each dvdcompare episode exactly once,
        in dvdcompare order.
        """
        # Real Psych S1 D2 runtimes reported by MakeMKV.
        # Distinct sizes to defeat the same-resolution duplicate check.
        t0 = _make_title(0, 2586, size=6_100_000_000)  # Spellingg Bee
        t1 = _make_title(1, 2563, size=6_050_000_000)  # Speak Now
        t2 = _make_title(2, 2540, size=6_000_000_000)  # Woman Seeking Dead Husband
        t3 = _make_title(3, 5103, size=12_000_000_000) # partial play-all (unmatched)
        t4 = _make_title(4, 2588, size=6_150_000_000)  # 9 Lives
        t5 = _make_title(5, 6374, size=15_000_000_000) # partial play-all (unmatched)
        t6 = _make_title(6, 2586, size=6_090_000_000)  # Weekend Warriors
        all_titles = [t0, t1, t2, t3, t4, t5, t6]
        dvd_entries = [
            ("Spellingg Bee", 2588, "episode"),
            ("Speak Now or Forever Hold Your Piece", 2566, "episode"),
            ("Woman Seeking Dead Husband", 2542, "episode"),
            ("9 Lives", 2591, "episode"),
            ("Weekend Warriors", 2587, "episode"),
        ]
        total = sum(rt for _, rt, _ in dvd_entries)

        def _classify(t):
            return classify_title(
                t, all_titles, dvd_entries, False, None, total, 5,
            )

        # Disc titles are labeled in dvdcompare order, not
        # nearest-neighbor order.
        assert "Spellingg Bee" in _classify(t0)
        assert "Speak Now" in _classify(t1)
        assert "Woman Seeking Dead Husband" in _classify(t2)
        assert "9 Lives" in _classify(t4)
        assert "Weekend Warriors" in _classify(t6)
        # No episode name appears on more than one disc title.
        labels = [_classify(t) for t in (t0, t1, t2, t4, t6)]
        assert len(set(labels)) == 5
        # Partial play-alls are still labeled Unmatched (didn't
        # consume any episode slot).
        assert "Unmatched content" in _classify(t3)
        assert "Unmatched content" in _classify(t5)

    def test_sequential_walk_skips_missing_dvdcompare_slot(self):
        """dvdcompare occasionally lists an episode that isn't on the
        physical disc, or lists episodes in a different order than the
        disc's physical layout (Chernobyl S1 D1: dvdcompare lists
        Please Remain Calm before Open Wide, O Earth, but the disc
        plays Open Wide first). The walk should first-fit against the
        remaining unconsumed dvdcompare entries so a runtime that
        doesn't fit the next-expected slot can still claim a later
        slot without stalling the walker or double-consuming.
        """
        # 3 disc titles, dvdcompare lists 4 episodes with the second
        # one absent from the disc (very different runtime).
        t0 = _make_title(0, 2588, size=6_100_000_000)
        t1 = _make_title(1, 2542, size=6_000_000_000)
        t2 = _make_title(2, 2587, size=6_090_000_000)
        all_titles = [t0, t1, t2]
        dvd_entries = [
            ("Ep A", 2588, "episode"),
            ("Ep B (deleted)", 5400, "episode"),  # not on disc
            ("Ep C", 2542, "episode"),
            ("Ep D", 2587, "episode"),
        ]

        def _classify(t):
            return classify_title(
                t, all_titles, dvd_entries, False, None,
                sum(rt for _, rt, _ in dvd_entries), 4,
            )

        assert "Ep A" in _classify(t0)
        assert "Ep C" in _classify(t1)
        assert "Ep D" in _classify(t2)

    def test_sequential_walk_handles_disc_order_not_matching_dvdcompare(self):
        """Chernobyl S1 D1 case: dvdcompare lists episodes as
        [1:23:45 (3534s), Please Remain Calm (3896s), Open Wide (3707s)]
        but the disc plays them as [1:23:45, Open Wide, Please Remain
        Calm]. First-fit lets t3=3707 claim Open Wide (skipping the
        out-of-tolerance Please Remain Calm) and t4=3896 then claims
        Please Remain Calm from the still-unconsumed pool.
        """
        t0 = _make_title(0, 3534, size=28_672_335_052)
        t3 = _make_title(3, 3707, size=30_278_874_521)
        t4 = _make_title(4, 3896, size=31_784_629_658)
        all_titles = [t0, t3, t4]
        dvd_entries = [
            ("1:23:45", 3534, "episode"),
            ("Please Remain Calm", 3896, "episode"),
            ("Open Wide, O Earth", 3707, "episode"),
        ]

        def _classify(t):
            return classify_title(
                t, all_titles, dvd_entries, False, None,
                sum(rt for _, rt, _ in dvd_entries), 3,
            )

        assert "1:23:45" in _classify(t0)
        assert "Open Wide, O Earth" in _classify(t3)
        assert "Please Remain Calm" in _classify(t4)


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

    def test_extended_cut_detected(self):
        theatrical = _make_title(0, 7200)
        extended = _make_title(1, 7900)
        entries = [("The Film - Theatrical Cut (2160p)", 0, "film"), ("The Film - Extended Cut (2160p)", 0, "film")]
        result = classify_title(extended, [theatrical, extended], entries, True, 7200, 0, 0)
        assert "Extended Cut" in result

    def test_extended_cut_fallback_no_dvdcompare(self):
        theatrical = _make_title(0, 7200)
        extended = _make_title(1, 7900)
        result = classify_title(extended, [theatrical, extended], [], True, 7200, 0, 0)
        assert "Extended Cut" in result

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

    def test_skip_dvdcompare_play_all(self):
        """Titles matching a dvdcompare 'Play All' entry should be skipped."""
        play_all_title = _make_title(0, 3050)  # 3050s on disc
        individual = _make_title(1, 1500)
        dvd_entries = [
            ("Section A: Play All", 3050, "extra"),
            ("Feature 1", 1500, "extra"),
            ("Feature 2", 1550, "extra"),
        ]
        assert is_skip_title(
            play_all_title, [play_all_title, individual],
            False, None, 0, 0, dvd_entries,
        ) is True

    def test_keep_non_play_all_dvdcompare_match(self):
        """Titles matching a normal dvdcompare entry should NOT be skipped."""
        feature = _make_title(0, 1500)
        dvd_entries = [
            ("Making Of Documentary", 1500, "extra"),
            ("Play All", 3050, "extra"),
        ]
        assert is_skip_title(
            feature, [feature],
            False, None, 0, 0, dvd_entries,
        ) is False

    def test_keep_1080p_extra_on_4k_disc_without_4k_counterpart(self):
        """On a 4K disc with 1080p-only extras (Universal BttF 40th Anniversary
        pattern), the 1080p extras should NOT be skipped just because a 4K
        main film exists on the same disc. They're the only copy."""
        # 4K main film (movie length) so the disc qualifies as "has_4k"
        main_4k = _make_title(0, 7098, resolution="3840x2160")
        # 1080p featurette with a dvdcompare entry but NO 4K counterpart
        feat_1080 = _make_title(1, 1027, resolution="1920x1080")
        dvd_entries = [
            ("Tales from the Future: Third Time's the Charm", 1027, "featurette"),
        ]
        assert is_skip_title(
            feat_1080, [main_4k, feat_1080],
            True, 7098, 0, 0, dvd_entries,
        ) is False

    def test_skip_1080p_extra_when_4k_counterpart_exists(self):
        """When the same extra exists in both 4K and 1080p on the disc
        (true duplicate), keep the 4K version and skip the 1080p."""
        main_4k = _make_title(0, 7098, resolution="3840x2160")
        # Same featurette, both resolutions, same duration
        feat_4k = _make_title(1, 248, resolution="3840x2160")
        feat_1080 = _make_title(2, 248, resolution="1920x1080")
        dvd_entries = [
            ("Music Video by ZZ Top: Doubleback", 248, "extra"),
        ]
        # 1080p version should be skipped (4K duplicate exists)
        assert is_skip_title(
            feat_1080, [main_4k, feat_4k, feat_1080],
            True, 7098, 0, 0, dvd_entries,
        ) is True
        # 4K version should be kept
        assert is_skip_title(
            feat_4k, [main_4k, feat_4k, feat_1080],
            True, 7098, 0, 0, dvd_entries,
        ) is False

    def test_main_feature_not_skipped_when_extras_sum_matches(self):
        """Independence Day 4K disc 1 pattern: the main feature runs
        8688s; the disc's 14 short extras happen to sum to 8610s (78s
        off, well inside detect_play_all's ~210s tolerance). Without a
        main-feature guard the theatrical version got mis-skipped as a
        play-all of the extras."""
        main = _make_title(0, 8688, resolution="3840x2160")
        extended = _make_title(1, 9213, resolution="3840x2160")
        extra_durations = [
            366, 377, 1208, 139, 135, 792, 505,
            175, 495, 1193, 1555, 1295, 156, 219,
        ]
        assert sum(extra_durations) == 8610  # sanity: still within tolerance
        extras = [
            _make_title(i + 2, d, resolution="3840x2160")
            for i, d in enumerate(extra_durations)
        ]
        all_titles = [main, extended] + extras
        assert is_skip_title(
            main, all_titles, True, 8688, 0, 0, [],
        ) is False

    def test_extended_cut_not_skipped_when_extras_sum_matches(self):
        """Same protection extended to a plausible extended cut: extras
        summing near an extended runtime shouldn't kill the cut."""
        main = _make_title(0, 7200, resolution="3840x2160")
        extended = _make_title(1, 8000, resolution="3840x2160")
        # Ten ~800s extras — sum 8000, exactly the extended runtime.
        extras = [
            _make_title(i + 2, 800, resolution="3840x2160")
            for i in range(10)
        ]
        all_titles = [main, extended] + extras
        assert is_skip_title(
            extended, all_titles, True, 7200, 0, 0, [],
        ) is False

    def test_skip_unmatched_partial_play_all_on_tv_disc(self):
        """Psych S1 D2 pattern: 5 ~43 min episodes plus a mystery
        ~85 min title (episodes 1+2 concatenated). The play-all has no
        dvdcompare match and no play-all detector catches it because
        dvdcompare only lists ``Episodes (with Play All option)``
        without per-play-all durations. Default: skip (unchecked) so
        the user doesn't rip a 2.9 GB duplicate of the individual
        episodes.
        """
        episodes = [_make_title(i, 2590) for i in range(5)]
        partial_play_all = _make_title(5, 5103)
        dvd_entries = [
            ("Spellingg Bee", 2588, "episode"),
            ("Speak Now or Forever Hold Your Piece", 2566, "episode"),
            ("Woman Seeking Dead Husband", 2542, "episode"),
            ("9 Lives", 2591, "episode"),
            ("Weekend Warriors", 2587, "episode"),
        ]
        total = sum(rt for _, rt, _ in dvd_entries)
        assert is_skip_title(
            partial_play_all, [*episodes, partial_play_all],
            False, None, total, 5, dvd_entries,
        ) is True

    def test_keep_episode_slightly_longer_than_dvdcompare_runtime(self):
        """Regression guard for the partial-play-all skip: an episode
        whose MakeMKV runtime is slightly higher than every dvdcompare
        entry (encoding differences, extended finale) must still be
        kept, not skipped as unmatched.
        """
        episodes = [_make_title(i, 2590) for i in range(4)]
        odd_one = _make_title(5, 2700)  # 110s over max
        dvd_entries = [
            (f"Episode {i}", 2590, "episode") for i in range(4)
        ]
        assert is_skip_title(
            odd_one, [*episodes, odd_one],
            False, None, 4 * 2590, 4, dvd_entries,
        ) is False


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


class _FakeTmdbEpisode:
    def __init__(self, season, ep, title, runtime_seconds=0):
        self.season_number = season
        self.episode_number = ep
        self.title = title
        self.runtime_seconds = runtime_seconds


class _FakeSeason:
    def __init__(self, season_number, episodes):
        self.season_number = season_number
        self.episodes = episodes


class _FakeShowDetail:
    def __init__(self, seasons):
        self.seasons = seasons


class TestEnrichDvdEntriesWithTmdb:
    def test_prepends_se_prefix_to_matched_episodes(self):
        """Psych S1 D2 pattern: dvdcompare titles get canonical S01E0N
        prefixes when they match TMDb episode names."""
        entries = [
            ("Spellingg Bee", 2588, "episode"),
            ("Speak Now or Forever Hold Your Piece", 2566, "episode"),
        ]
        tmdb = [
            _FakeTmdbEpisode(1, 1, "Spellingg Bee"),
            _FakeTmdbEpisode(1, 2, "Speak Now or Forever Hold Your Piece"),
        ]
        enriched, total, count = enrich_dvd_entries_with_tmdb(entries, tmdb)
        assert count == 2
        assert enriched[0][0].startswith("S01E01 - Spellingg Bee")
        assert enriched[1][0].startswith("S01E02 - Speak Now")

    def test_substring_match_still_matches(self):
        """dvdcompare frequently truncates or extends episode titles
        relative to TMDb — normalized substring should still match."""
        entries = [("Woman Seeking Dead Husband", 2542, "episode")]
        tmdb = [_FakeTmdbEpisode(
            1, 3, "Woman Seeking Dead Husband: Smokers Okay, No Pets",
        )]
        enriched, _, _ = enrich_dvd_entries_with_tmdb(entries, tmdb)
        assert enriched[0][0].startswith("S01E03 - ")

    def test_promotes_untyped_feature_matching_episode_name(self):
        """An entry dvdcompare didn't flag as ``episode`` (empty
        feature_type) that fuzzy-matches a TMDb episode by name AND
        exceeds the runtime floor gets promoted to ``episode`` so the
        sequential walker will consider it."""
        entries = [("Pilot", 2600, "")]  # no feature_type
        tmdb = [_FakeTmdbEpisode(1, 1, "Pilot")]
        enriched, total, count = enrich_dvd_entries_with_tmdb(entries, tmdb)
        assert enriched[0][2] == "episode"
        assert count == 1
        assert total == 2600

    def test_short_extra_with_matching_name_not_promoted(self):
        """Psych S1 D3 gotcha: the disc has both a 43-min episode
        ("Shawn vs. the Red Phantom") and a 52-second deleted scene of
        the same name. The deleted scene must NOT be promoted to an
        episode just because the name matches."""
        entries = [
            ("Shawn vs. the Red Phantom", 2592, "episode"),
            ("Shawn vs. the Red Phantom", 52, "extra"),  # deleted scene
        ]
        tmdb = [_FakeTmdbEpisode(1, 8, "Shawn vs. the Red Phantom")]
        enriched, total, count = enrich_dvd_entries_with_tmdb(entries, tmdb)
        # Long entry claims the TMDb match; short one keeps "extra".
        assert enriched[0][2] == "episode"
        assert enriched[0][0].startswith("S01E08 - ")
        assert enriched[1][2] == "extra"
        assert enriched[1][0] == "Shawn vs. the Red Phantom"
        assert count == 1

    def test_each_tmdb_episode_matched_at_most_once(self):
        """If dvdcompare lists a title twice (rare — bad scrape or
        genuine duplicate), only the first match consumes the TMDb
        episode; the second falls through unmatched."""
        entries = [
            ("Pilot", 2600, "episode"),
            ("Pilot", 2600, "episode"),
        ]
        tmdb = [_FakeTmdbEpisode(1, 1, "Pilot")]
        enriched, _, count = enrich_dvd_entries_with_tmdb(entries, tmdb)
        assert enriched[0][0].startswith("S01E01 - ")
        assert enriched[1][0] == "Pilot"  # no prefix — unmatched
        # Both still typed "episode" because the input said so; the
        # walker will only enrich the label.
        assert count == 2

    def test_no_match_leaves_entries_untouched(self):
        entries = [
            ("Behind the Scenes", 900, "featurette"),
            ("Bloopers", 300, "extra"),
        ]
        tmdb = [_FakeTmdbEpisode(1, 1, "Pilot")]
        enriched, total, count = enrich_dvd_entries_with_tmdb(entries, tmdb)
        assert enriched == entries
        assert count == 0
        assert total == 0

    def test_empty_inputs_return_unchanged(self):
        assert enrich_dvd_entries_with_tmdb([], []) == ([], 0, 0)
        assert enrich_dvd_entries_with_tmdb(
            [("Foo", 100, "extra")], []
        ) == ([("Foo", 100, "extra")], 0, 0)

    def test_analyze_disc_wires_tmdb_enrichment(self):
        """End-to-end via analyze_disc: TV show, TMDb episodes passed
        in, classification labels come back with S/E prefixes."""
        t0 = _make_title(0, 2588, size=6_100_000_000, resolution="720x480")
        t1 = _make_title(1, 2566, size=6_050_000_000, resolution="720x480")

        class _Ep:
            def __init__(self, title, rt):
                self.title = title
                self.runtime_seconds = rt

        class _Disc:
            number = 1
            is_film = False
            title = ""
            episodes = [
                _Ep("Spellingg Bee", 2588),
                _Ep("Speak Now or Forever Hold Your Piece", 2566),
            ]
            extras = []

        class _DiscInfo:
            disc_name = "PSYCH_S1_D1"
            titles = [t0, t1]

        tmdb = [
            _FakeTmdbEpisode(1, 1, "Spellingg Bee"),
            _FakeTmdbEpisode(1, 2, "Speak Now or Forever Hold Your Piece"),
        ]
        analysis = analyze_disc(
            _DiscInfo(), [_Disc()],
            disc_number=1, is_movie=False, movie_runtime=None,
            tmdb_episodes=tmdb,
        )
        assert "S01E01" in analysis.classifications[0]
        assert "S01E02" in analysis.classifications[1]


class TestParseSeasonNumber:
    def test_typical_label(self):
        assert parse_season_number("Season 1, Disc 2") == 1

    def test_multi_digit(self):
        assert parse_season_number("Season 12, Disc 3") == 12

    def test_empty(self):
        assert parse_season_number("") is None

    def test_no_season_word(self):
        assert parse_season_number("Disc 3") is None


class TestCollectTmdbEpisodesForDisc:
    def _make_show(self):
        return _FakeShowDetail([
            _FakeSeason(1, [_FakeTmdbEpisode(1, 1, "Pilot")]),
            _FakeSeason(2, [_FakeTmdbEpisode(2, 1, "Return")]),
        ])

    def _make_discs(self, labels):
        class _D:
            def __init__(self, number, title):
                self.number = number
                self.title = title
        return [_D(i + 1, t) for i, t in enumerate(labels)]

    def test_no_show_detail_returns_empty(self):
        assert collect_tmdb_episodes_for_disc(None, [], 1) == []

    def test_matching_season_label_returns_that_season(self):
        show = self._make_show()
        discs = self._make_discs(["Season 2", "Season 2"])
        eps = collect_tmdb_episodes_for_disc(show, discs, 1)
        assert len(eps) == 1
        assert eps[0].title == "Return"

    def test_no_matching_label_falls_back_to_all_seasons(self):
        show = self._make_show()
        discs = self._make_discs(["", ""])
        eps = collect_tmdb_episodes_for_disc(show, discs, 1)
        assert len(eps) == 2

    def test_film_title_backfills_leading_untitled_run(self):
        show = self._make_show()
        discs = self._make_discs(["", ""])
        eps = collect_tmdb_episodes_for_disc(
            show, discs, 1, film_title="Psych: Season 1 (Blu-ray)",
        )
        assert len(eps) == 1
        assert eps[0].title == "Pilot"


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

    def test_extras_only_disc_matching(self):
        """Extras-only disc (like bonus features) should match via extras durations."""
        class FakeEp:
            def __init__(self, runtime):
                self.title = "Ep"
                self.runtime_seconds = runtime

        class FakeExtra:
            def __init__(self, runtime):
                self.title = "Extra"
                self.runtime_seconds = runtime
                self.feature_type = "extra"

        class FakeDisc:
            def __init__(self, number, ep_runtimes, extra_runtimes=None):
                self.number = number
                self.episodes = [FakeEp(rt) for rt in ep_runtimes]
                self.extras = [FakeExtra(rt) for rt in (extra_runtimes or [])]
                self.disc_format = "Blu-ray"

        # Disc 1: main film (episodes)
        disc1 = FakeDisc(1, [7200])
        # Disc 3: bonus features only (no episodes, just extras)
        disc3 = FakeDisc(3, [], extra_runtimes=[250, 300, 280, 260, 310])

        # Live disc has titles matching disc 3's extras
        titles = [
            _make_title(0, 255),
            _make_title(1, 305),
            _make_title(2, 275),
            _make_title(3, 265),
            _make_title(4, 315),
        ]
        info = DiscInfo(disc_name="BONUS_DISC", disc_type="Blu-ray disc", titles=titles)
        assert _detect_disc_number(info, [disc1, disc3]) == 3

    def test_extras_only_disc_no_match_short_extras(self):
        """Extras under 120s are excluded from matching (too short to be reliable)."""
        class FakeExtra:
            def __init__(self, runtime):
                self.title = "Extra"
                self.runtime_seconds = runtime
                self.feature_type = "extra"

        class FakeDisc:
            def __init__(self, number, extra_runtimes):
                self.number = number
                self.episodes = []
                self.extras = [FakeExtra(rt) for rt in extra_runtimes]
                self.disc_format = "Blu-ray"

        # All extras are very short — shouldn't be used for matching
        disc1 = FakeDisc(1, [60, 90, 100])
        titles = [_make_title(0, 65), _make_title(1, 95)]
        info = DiscInfo(disc_name="DISC", disc_type="Blu-ray disc", titles=titles)
        assert _detect_disc_number(info, [disc1]) is None

    def test_4k_disc_matched_by_format_not_duration(self):
        """A 4K movie disc whose feature has no listed runtime must still be
        detected as the 4K disc via resolution — not mis-detected as the
        Blu-ray disc that happens to list the same film's runtime.

        Regression for the multi-format movie release case (issue: a 4K disc
        was detected as disc 2 because disc 1's 4K feature had no runtime and
        the inserted disc's film matched disc 2's listed 2D/3D runtimes).
        """
        class FakeEp:
            def __init__(self, runtime):
                self.title = "The Film"
                self.runtime_seconds = runtime

        class FakeDisc:
            def __init__(self, number, fmt, ep_runtimes):
                self.number = number
                self.disc_format = fmt
                self.episodes = [FakeEp(rt) for rt in ep_runtimes]
                self.extras = []

        # Disc 1 = 4K disc, but dvdcompare lists no runtime for its feature.
        disc1 = FakeDisc(1, "Blu-ray 4K", [])
        # Disc 2 = 3D Blu-ray, lists the 2D + 3D film runtimes (~ same length).
        disc2 = FakeDisc(2, "3D Blu-ray", [2880, 2880])

        # Inserted disc is the 4K disc: its single film title is 2160p and its
        # runtime matches disc 2's listed film runtime.
        titles = [_make_title(0, 2885, resolution="3840x2160")]
        info = DiscInfo(disc_name="THE_LAST_REEF", disc_type="Blu-ray disc", titles=titles)
        assert _detect_disc_number(info, [disc1, disc2]) == 1

    def test_format_match_skipped_for_same_format_set(self):
        """A multi-disc set where every disc is the same format must not be
        resolved by format — it falls through to duration matching."""
        class FakeEp:
            def __init__(self, runtime):
                self.title = "Ep"
                self.runtime_seconds = runtime

        class FakeDisc:
            def __init__(self, number, runtimes):
                self.number = number
                self.disc_format = "Blu-ray 4K"
                self.episodes = [FakeEp(rt) for rt in runtimes]
                self.extras = []

        # Both discs are 4K, so resolution can't distinguish them.
        disc1 = FakeDisc(1, [3000, 3100, 3050])
        disc2 = FakeDisc(2, [2800, 2900, 2950])
        titles = [
            _make_title(0, 2810, resolution="3840x2160"),
            _make_title(1, 2910, resolution="3840x2160"),
            _make_title(2, 2960, resolution="3840x2160"),
        ]
        info = DiscInfo(disc_name="MYSTERY_DISC", disc_type="Blu-ray disc", titles=titles)
        assert _detect_disc_number(info, [disc1, disc2]) == 2

    def test_single_live_title_matches_multi_film_bonus_disc(self):
        """A physical disc that exposes just one title (e.g. a bonus disc
        where MakeMKV surfaces only the main feature) should still match a
        dvdcompare disc that lists several films as long as the exposed
        runtime lines up with one of them.

        Regression for the Psych: The Movie case (Complete Series release,
        disc 31 lists three feature films; the physical disc showed only
        one title at 5282s but the old scoring divided by len(candidates)=3
        and rejected the match at 0.33 < 0.50).
        """
        class FakeExtra:
            def __init__(self, runtime):
                self.title = "Film"
                self.runtime_seconds = runtime
                self.feature_type = ""

        class FakeDisc:
            def __init__(self, number, ep_runtimes, extra_runtimes=None):
                self.number = number
                self.disc_format = ""
                self.episodes = []
                for rt in ep_runtimes:
                    ep = type("Ep", (), {})()
                    ep.title = "Ep"
                    ep.runtime_seconds = rt
                    self.episodes.append(ep)
                self.extras = [FakeExtra(rt) for rt in (extra_runtimes or [])]

        # Series discs 1..3 hold episodes; disc 4 is a bonus disc listing
        # three movies as extras (like Psych's disc 31).
        disc1 = FakeDisc(1, [2588, 2589, 2587])
        disc2 = FakeDisc(2, [2588, 2589, 2587])
        disc3 = FakeDisc(3, [2588, 2589, 2587])
        disc4 = FakeDisc(4, [], extra_runtimes=[5290, 5310, 5782])

        titles = [_make_title(0, 5282)]
        info = DiscInfo(disc_name="PSYCH_THE_MOVIE", disc_type="Blu-ray disc", titles=titles)
        assert _detect_disc_number(info, [disc1, disc2, disc3, disc4]) == 4



class TestAnalyzeDisc:
    """Tests for the analyze_disc() shared entry point."""

    def _make_fake_disc(self, number, ep_runtimes, extra_runtimes=None, extra_titles=None, is_film=False):
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
                self.is_film = is_film

        eps = [FakeEp(f"Ep {i+1}", rt) for i, rt in enumerate(ep_runtimes)]
        if extra_titles is None:
            extras = [FakeExtra(f"Extra {i+1}", rt) for i, rt in enumerate(extra_runtimes or [])]
        else:
            extras = [
                FakeExtra(title, runtime)
                for title, runtime in zip(extra_titles, extra_runtimes or [])
            ]
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

    def test_3d_2d_movie_variants_are_labeled_by_size(self):
        disc = self._make_fake_disc(
            2,
            [],
            extra_runtimes=[0, 0],
            extra_titles=["The Film (3D) (1080p)", "The Film (2D) (1080p)"],
            is_film=True,
        )
        titles = [
            _make_title(
                0, 2653, resolution="1920x1080",
                size=14_494_550_016,
            ),
            _make_title(
                3, 2653, resolution="1920x1080",
                size=13_900_886_016,
            ),
        ]
        info = DiscInfo(disc_name="MYSTERY", disc_type="Blu-ray disc", titles=titles)

        analysis = analyze_disc(
            info, [disc], disc_number=2, is_movie=True, movie_runtime=2700,
        )

        assert analysis.classifications[0] == "3D Edition (1080p)"
        assert analysis.classifications[3] == "2D Edition (1080p)"




class TestDetectBonusFilms:
    """Tests for detect_bonus_films() — pointer-linked bonus extras."""

    def _disc(self, extras=None):
        return PlannedDisc(
            number=1, disc_format="Blu-ray",
            episodes=[], extras=extras or [],
        )

    def test_empty_disc(self):
        assert detect_bonus_films(self._disc()) == []

    def test_extras_without_pointers_ignored(self):
        # Ordinary bonus content (no hyperlink) returns nothing regardless
        # of runtime or feature_type — those heuristics are gone.
        disc = self._disc(extras=[
            PlannedExtra(title="Making Of", runtime_seconds=4500,
                         feature_type="documentary"),
            PlannedExtra(title="Standalone Bonus", runtime_seconds=6000),
            PlannedExtra(title="Trailer", runtime_seconds=150,
                         feature_type="trailer"),
        ])
        assert detect_bonus_films(disc) == []

    def test_pointer_linked_extras_returned_in_source_order(self):
        # Psych disc 31 shape: each film hyperlinks to its own film page.
        disc = self._disc(extras=[
            PlannedExtra(title="Psych: The Movie", runtime_seconds=5290,
                         pointer_fid=66239),
            PlannedExtra(title="Psych 2: Lassie Come Home",
                         runtime_seconds=5310, pointer_fid=66240),
            PlannedExtra(title="Psych 3: This Is Gus",
                         runtime_seconds=5782, pointer_fid=66241),
        ])
        films = detect_bonus_films(disc)
        assert [f.title for f in films] == [
            "Psych: The Movie",
            "Psych 2: Lassie Come Home",
            "Psych 3: This Is Gus",
        ]
        assert [f.pointer_fid for f in films] == [66239, 66240, 66241]

    def test_short_pointered_extra_still_counts(self):
        # dvdcompare hyperlinks are curated: if it's linked, it's a real
        # work. Runtime/feature_type filters no longer apply.
        disc = self._disc(extras=[
            PlannedExtra(title="Companion Short Film", runtime_seconds=2700,
                         pointer_fid=99999),
        ])
        assert [f.title for f in detect_bonus_films(disc)] == [
            "Companion Short Film",
        ]

    def test_duplicate_pointer_fids_deduped(self):
        # A Making-Of platter that hyperlinks every featurette to the
        # same movie page should produce one entry, not N.
        disc = self._disc(extras=[
            PlannedExtra(title="Featurette One", runtime_seconds=600,
                         pointer_fid=42),
            PlannedExtra(title="Featurette Two", runtime_seconds=900,
                         pointer_fid=42),
            PlannedExtra(title="Featurette Three", runtime_seconds=1200,
                         pointer_fid=42),
        ])
        films = detect_bonus_films(disc)
        assert len(films) == 1
        assert films[0].title == "Featurette One"

    def test_play_all_parent_skipped(self):
        disc = self._disc(extras=[
            PlannedExtra(title="Collection: Play All",
                         runtime_seconds=16000, pointer_fid=77),
            PlannedExtra(title="Real Film", runtime_seconds=5400,
                         pointer_fid=78),
        ])
        films = detect_bonus_films(disc)
        assert [f.title for f in films] == ["Real Film"]


class TestGroupReleaseDiscs:
    """Tests for group_release_discs() — the release-splitting heuristic."""

    def _disc(self, number, *, is_film=False, extras=None, episodes=None):
        return PlannedDisc(
            number=number,
            disc_format="Blu-ray",
            is_film=is_film,
            episodes=episodes or [],
            extras=extras or [],
        )

    def _fake_match(self, media_type, title="X"):
        # Simulate MetadataSearchResult duck-type; only .media_type is read.
        class M:
            pass
        m = M()
        m.media_type = media_type
        m.title = title
        return m

    def test_empty_discs_returns_empty(self):
        assert group_release_discs([], None) == []

    def test_single_group_tv_release(self):
        # A pure TV release: one group covering all discs.
        discs = [self._disc(n) for n in range(1, 5)]
        groups = group_release_discs(discs, self._fake_match("tv"))
        assert len(groups) == 1
        g = groups[0]
        assert g.films == []
        assert g.disc_numbers == [1, 2, 3, 4]
        assert g.tmdb_match is not None
        assert g.source == "user"
        assert g.label == "Discs 1-4"

    def test_single_group_single_movie_disc(self):
        # A single-disc movie release: one group with the pre-picked
        # match on the group itself (no per-film slots).
        discs = [self._disc(1, is_film=True)]
        groups = group_release_discs(discs, self._fake_match("movie", "Movie"))
        assert len(groups) == 1
        g = groups[0]
        assert g.disc_numbers == [1]
        assert g.films == []
        assert g.tmdb_match is not None
        assert g.source == "user"
        assert g.label == "Disc 1"

    def test_movie_with_bonus_disc_not_split(self):
        # Independence Day 4K shape: 4K + Blu-ray + bonus disc, no
        # pointer_fid on any extra. Must stay as one group.
        discs = [
            self._disc(1, is_film=True),  # 4K
            self._disc(2, is_film=True),  # Blu-ray
            self._disc(3, is_film=False, extras=[
                PlannedExtra(title="A Legacy Surging Forward",
                             runtime_seconds=5400),
                PlannedExtra(title="Gag Reel", runtime_seconds=300),
            ]),
        ]
        match = self._fake_match("movie", "Independence Day")
        groups = group_release_discs(discs, match)
        assert len(groups) == 1
        g = groups[0]
        assert g.disc_numbers == [1, 2, 3]
        assert g.films == []
        assert g.tmdb_match is match
        assert g.source == "user"

    def test_pointer_split_psych_complete_series(self):
        # 30 episode discs + 1 bonus-films disc with three linked
        # standalone TV-movies. The pointered disc splits off.
        discs = [self._disc(n) for n in range(1, 31)]
        discs.append(self._disc(31, extras=[
            PlannedExtra(title="Psych: The Movie", runtime_seconds=5290,
                         pointer_fid=66239),
            PlannedExtra(title="Psych 2: Lassie Come Home",
                         runtime_seconds=5310, pointer_fid=66240),
            PlannedExtra(title="Psych 3: This Is Gus",
                         runtime_seconds=5782, pointer_fid=66241),
        ]))
        match = self._fake_match("tv", "Psych")
        groups = group_release_discs(discs, match)
        assert len(groups) == 2
        main, film = groups[0], groups[1]
        assert main.disc_numbers == list(range(1, 31))
        assert main.films == []
        assert main.tmdb_match is match
        assert main.source == "user"
        assert film.disc_numbers == [31]
        assert [f.title for f in film.films] == [
            "Psych: The Movie",
            "Psych 2: Lassie Come Home",
            "Psych 3: This Is Gus",
        ]
        assert [f.dvdcompare_fid for f in film.films] == [66239, 66240, 66241]
        # Match is never pre-routed to a film group's slots; each slot
        # autofills from its own dvdcompare_fid.
        assert film.tmdb_match is None
        assert all(f.tmdb_match is None for f in film.films)

    def test_double_feature_single_disc(self):
        # One disc, two distinct linked works — two FilmSlots in one
        # group. The main-work seat has no candidates, so the user's
        # match lands on the first slot as a fallback.
        disc = self._disc(1, is_film=True, extras=[
            PlannedExtra(title="Film A", runtime_seconds=5000,
                         pointer_fid=101),
            PlannedExtra(title="Film B", runtime_seconds=5200,
                         pointer_fid=102),
        ])
        match = self._fake_match("movie", "Film A")
        groups = group_release_discs([disc], match)
        assert len(groups) == 1
        g = groups[0]
        assert [f.title for f in g.films] == ["Film A", "Film B"]
        assert [f.dvdcompare_fid for f in g.films] == [101, 102]
        assert [f.runtime_seconds for f in g.films] == [5000, 5200]
        assert g.films[0].tmdb_match is match
        assert g.films[0].source == "user"
        assert g.films[1].tmdb_match is None
        assert g.label == "Disc 1: 2 linked works"

    def test_making_of_disc_with_same_fid_across_extras(self):
        # A Making-Of Blu-ray whose 12 featurettes all hyperlink to the
        # same movie page — deduped to one slot, not fragmented.
        disc = self._disc(2, extras=[
            PlannedExtra(title=f"Featurette {i}", runtime_seconds=600,
                         pointer_fid=555)
            for i in range(1, 13)
        ])
        groups = group_release_discs([disc], None)
        assert len(groups) == 1
        g = groups[0]
        assert len(g.films) == 1
        assert g.films[0].dvdcompare_fid == 555
        assert g.label == "Disc 2: Featurette 1"

    def test_no_match_leaves_group_unassigned(self):
        discs = [self._disc(1), self._disc(2, is_film=True)]
        groups = group_release_discs(discs, None)
        assert len(groups) == 1
        assert groups[0].tmdb_match is None

    def test_alternating_pointer_boundary_creates_multiple_runs(self):
        # Disc keys: {} , {fid=1} , {} , {fid=1} — four runs.
        discs = [
            self._disc(1),
            self._disc(2, extras=[
                PlannedExtra(title="X", runtime_seconds=5000, pointer_fid=1),
            ]),
            self._disc(3),
            self._disc(4, extras=[
                PlannedExtra(title="Y", runtime_seconds=5000, pointer_fid=1),
            ]),
        ]
        groups = group_release_discs(discs, None)
        assert [g.disc_numbers for g in groups] == [[1], [2], [3], [4]]
        assert [bool(g.films) for g in groups] == [False, True, False, True]

    def test_discs_out_of_order_are_sorted(self):
        discs = [self._disc(3), self._disc(1), self._disc(2)]
        groups = group_release_discs(discs, None)
        assert len(groups) == 1
        assert groups[0].disc_numbers == [1, 2, 3]

    def test_group_ids_are_disc_number_based(self):
        discs = [
            self._disc(1),
            self._disc(2),
            self._disc(3, extras=[
                PlannedExtra(title="Z", runtime_seconds=5000, pointer_fid=9),
            ]),
        ]
        groups = group_release_discs(discs, None)
        assert [g.id for g in groups] == ["discs_1_2", "disc_3"]

    def test_all_groups_have_pointers_match_seats_on_first_slot(self):
        # Exotic release: every disc has pointered extras. There's no
        # "primary work" group to seat the user's match on; the
        # fallback is the first slot of the first group.
        discs = [
            self._disc(1, extras=[
                PlannedExtra(title="A", runtime_seconds=5000, pointer_fid=10),
            ]),
            self._disc(2, extras=[
                PlannedExtra(title="B", runtime_seconds=5000, pointer_fid=20),
            ]),
        ]
        match = self._fake_match("movie", "A")
        groups = group_release_discs(discs, match)
        assert len(groups) == 2
        assert groups[0].films[0].tmdb_match is match
        assert groups[0].films[0].source == "user"
        assert groups[1].films[0].tmdb_match is None

    def test_is_complete_group_without_slots(self):
        g = DiscGroup(id="disc_1", label="", disc_numbers=[1])
        assert not g.is_complete()
        g.tmdb_match = object()
        assert g.is_complete()

    def test_is_complete_group_with_slots(self):
        g = DiscGroup(id="disc_1", label="", disc_numbers=[1],
                      films=[FilmSlot(title="A"), FilmSlot(title="B")])
        assert not g.is_complete()
        g.films[0].tmdb_match = object()
        assert not g.is_complete()
        g.films[1].tmdb_match = object()
        assert g.is_complete()


class TestBuildSeasonLabels:
    """Tests for build_season_labels() — dvdcompare season-placeholder
    labels turned into per-disc UI hints."""

    def _disc(self, number, title=""):
        return PlannedDisc(
            number=number, disc_format="Blu-ray", title=title,
        )

    def test_empty_input_returns_empty(self):
        assert build_season_labels([]) == {}

    def test_no_titles_maps_all_to_empty(self):
        # A release without any placeholder-derived titles: every entry
        # should be present but empty so callers can skip rendering.
        discs = [self._disc(n) for n in range(1, 4)]
        labels = build_season_labels(discs)
        assert labels == {1: "", 2: "", 3: ""}

    def test_single_season_indexes_contiguous_run(self):
        discs = [self._disc(n, title="Season 1") for n in range(1, 5)]
        labels = build_season_labels(discs)
        assert labels == {
            1: "Season 1, Disc 1",
            2: "Season 1, Disc 2",
            3: "Season 1, Disc 3",
            4: "Season 1, Disc 4",
        }

    def test_multiple_seasons_restart_index(self):
        # Psych-shape: 4 discs per season, seasons back-to-back.
        discs = (
            [self._disc(n, title="Season 1") for n in range(1, 5)]
            + [self._disc(n, title="Season 2") for n in range(5, 9)]
        )
        labels = build_season_labels(discs)
        assert labels[4] == "Season 1, Disc 4"
        assert labels[5] == "Season 2, Disc 1"
        assert labels[8] == "Season 2, Disc 4"

    def test_gap_disc_without_title_resets_run(self):
        # A bonus disc between two labeled runs shouldn't get an amber
        # label, and the run after it should restart from 1 even if it
        # shares the earlier title (defensive — dvdcompare wouldn't
        # normally produce this shape, but the helper stays honest).
        discs = [
            self._disc(1, title="Season 1"),
            self._disc(2, title="Season 1"),
            self._disc(3, title=""),
            self._disc(4, title="Season 1"),
        ]
        labels = build_season_labels(discs)
        assert labels == {
            1: "Season 1, Disc 1",
            2: "Season 1, Disc 2",
            3: "",
            4: "Season 1, Disc 1",
        }

    def test_whitespace_only_title_treated_as_missing(self):
        discs = [self._disc(1, title="   ")]
        assert build_season_labels(discs) == {1: ""}

    def test_film_title_backfills_leading_untitled_run(self):
        # Psych: Season 1 (fid=66231) shape — the release's "own" discs
        # 1-4 come back untitled because dvdcompare only puts a season
        # header on the pointer runs (Seasons 2-8). The film title
        # itself tells us those leading untitled discs are Season 1.
        discs = (
            [self._disc(n) for n in range(1, 5)]
            + [self._disc(n, title="Season 2") for n in range(5, 9)]
            + [self._disc(9)]  # trailing extras disc, no season info
        )
        labels = build_season_labels(
            discs, film_title="Psych: Season 1 (TV) (Blu-ray)",
        )
        assert labels[1] == "Season 1, Disc 1"
        assert labels[4] == "Season 1, Disc 4"
        assert labels[5] == "Season 2, Disc 1"
        assert labels[8] == "Season 2, Disc 4"
        # Trailing untitled disc is not backfilled.
        assert labels[9] == ""

    def test_film_title_without_season_does_not_backfill(self):
        discs = [self._disc(n) for n in range(1, 3)]
        labels = build_season_labels(
            discs, film_title="Batman Begins",
        )
        assert labels == {1: "", 2: ""}

    def test_film_title_backfill_ignored_when_leading_run_has_title(self):
        # If dvdcompare already labeled the leading run, don't override.
        discs = [
            self._disc(1, title="Season 3"),
            self._disc(2, title="Season 3"),
        ]
        labels = build_season_labels(
            discs, film_title="Show: Season 1",
        )
        assert labels == {
            1: "Season 3, Disc 1",
            2: "Season 3, Disc 2",
        }


class TestGroupForDisc:
    """Tests for group_for_disc() — look up which DiscGroup owns a
    given disc number. Used by the selection screen to swap in the
    per-group TMDb match on multi-work releases."""

    def _group(self, gid, numbers):
        from riplex.models import DiscGroup
        return DiscGroup(id=gid, label=gid, disc_numbers=numbers)

    def test_finds_group_containing_disc(self):
        g1 = self._group("main", [1, 2, 3])
        g2 = self._group("film", [4])
        assert group_for_disc([g1, g2], 2) is g1
        assert group_for_disc([g1, g2], 4) is g2

    def test_returns_none_when_disc_not_in_any_group(self):
        g = self._group("main", [1, 2])
        assert group_for_disc([g], 99) is None

    def test_none_disc_number_returns_none(self):
        g = self._group("main", [1])
        assert group_for_disc([g], None) is None

    def test_empty_groups_returns_none(self):
        assert group_for_disc([], 1) is None
