"""Tests for disc analysis using real disc fixtures.

Uses JSON fixtures that capture disc info + dvdcompare data to test
the full classification pipeline without needing a physical disc.
"""

import pytest

from riplex.disc.analysis import analyze_disc, collect_tmdb_episodes_for_disc
from tests.support.disc_fixtures import load_disc_fixture as _load_disc_fixture
from tests.support.disc_fixtures import load_show_detail


class TestChernobylDisc1:
    """Test classification against Chernobyl Disc 1 data.

    Disc 1 has:
    - 3 episodes: "1:23:45" (58:54), "Please Remain Calm" (1:04:56),
      "Open Wide, O Earth" (1:01:47) — each in 4K + duplicate 4K
    - "Meet the Key Players" play-all (5:40, 4K) — 3 actor featurettes
    - "Inside the Episodes" play-all (7:20, 1080p) — 3 episode featurettes
    - 3 individual 1080p featurettes (~2 min each)
    - Duplicates of most titles
    """

    @pytest.fixture()
    def disc_data(self):
        return _load_disc_fixture("chernobyl_disc1.json")

    def test_episodes_are_episodes(self, disc_data):
        """The 3 actual episodes should be classified as episodes, not extras."""
        disc_info, planned_discs, expected = disc_data

        # Check conversion: disc 1 should have 3 real episodes
        disc1 = next(d for d in planned_discs if d.number == 1)
        episode_runtimes = sorted(ep.runtime_seconds for ep in disc1.episodes)

        # The actual episodes are 3534s, 3707s, 3896s
        assert any(r > 3000 for r in episode_runtimes), (
            f"No substantial episodes found. Got runtimes: {episode_runtimes}. "
            "The converter is likely misclassifying the actual episodes as extras."
        )

    def test_featurettes_are_extras(self, disc_data):
        """Children of play-all featurette groups should be extras, not episodes."""
        disc_info, planned_discs, expected = disc_data
        disc1 = next(d for d in planned_discs if d.number == 1)

        # Short featurettes (< 300s) should not be in episodes list
        short_episodes = [ep for ep in disc1.episodes if ep.runtime_seconds < 300]
        assert not short_episodes, (
            f"Short featurettes misclassified as episodes: "
            f"{[(ep.title, ep.runtime_seconds) for ep in short_episodes]}"
        )

    def test_rip_only_4k_episodes(self, disc_data):
        """Only the 3 4K episodes should be recommended for ripping."""
        disc_info, planned_discs, expected = disc_data

        analysis = analyze_disc(
            disc_info, planned_discs,
            disc_number=1,
            is_movie=False,
            movie_runtime=None,
        )

        rip_indices = sorted(t.index for t in analysis.rippable_titles)
        expected_rip = expected.get("rip_indices", [0, 3, 4])

        assert rip_indices == expected_rip, (
            f"Expected rip indices {expected_rip}, got {rip_indices}.\n"
            f"Classifications:\n" +
            "\n".join(
                f"  #{idx}: {analysis.classifications[idx]}"
                for idx in sorted(analysis.classifications)
            )
        )

    def test_duplicates_are_skipped(self, disc_data):
        """Titles with same duration+size+resolution as earlier titles should be skipped."""
        disc_info, planned_discs, expected = disc_data

        analysis = analyze_disc(
            disc_info, planned_discs,
            disc_number=1,
            is_movie=False,
            movie_runtime=None,
        )

        # #6, #7, #8, #9 are same-resolution duplicates
        for idx in [6, 7, 8, 9]:
            assert "Duplicate" in analysis.classifications[idx] or "skip" in analysis.classifications[idx].lower(), (
                f"Title #{idx} should be a duplicate: {analysis.classifications[idx]}"
            )

    def test_episodes_are_named(self, disc_data):
        """Each ripped episode should have its dvdcompare name."""
        disc_info, planned_discs, expected = disc_data

        analysis = analyze_disc(
            disc_info, planned_discs,
            disc_number=1,
            is_movie=False,
            movie_runtime=None,
        )

        expected_names = expected.get("episode_names", {})
        for idx_str, expected_name in expected_names.items():
            idx = int(idx_str)
            classification = analysis.classifications[idx]
            assert expected_name in classification, (
                f"Title #{idx} should contain '{expected_name}': {classification}"
            )

    def test_featurette_play_alls_ripped(self, disc_data):
        """Play-all compilations of short featurettes should be ripped."""
        disc_info, planned_discs, expected = disc_data

        analysis = analyze_disc(
            disc_info, planned_discs,
            disc_number=1,
            is_movie=False,
            movie_runtime=None,
        )

        # #1 (5:40, 4K) = Meet the Key Players play-all
        # #2 (7:20, 1080p) = Inside the Episodes play-all
        rip_indices = [t.index for t in analysis.rippable_titles]
        for idx in [1, 2]:
            assert idx in rip_indices, (
                f"Title #{idx} is a featurette play-all and should be ripped: "
                f"{analysis.classifications[idx]}"
            )

    def test_1080p_skipped_when_4k_exists(self, disc_data):
        """1080p titles should be skipped only when a 4K version exists on
        the same disc. 1080p-only extras (no 4K counterpart) must be kept."""
        disc_info, planned_discs, expected = disc_data

        analysis = analyze_disc(
            disc_info, planned_discs,
            disc_number=1,
            is_movie=False,
            movie_runtime=None,
        )

        rip_indices = [t.index for t in analysis.rippable_titles]
        # #5 (1080p version of #1, 4K counterpart exists) should be skipped.
        # #10, #11, #12 (1080p featurette children with no 4K counterpart)
        # must NOT be skipped — they're the only copy of that content.
        assert 5 not in rip_indices, (
            f"Title #5 (1080p dup of 4K #1) should be skipped: "
            f"{analysis.classifications[5]}"
        )
        for idx in [10, 11, 12]:
            assert idx in rip_indices, (
                f"Title #{idx} (1080p featurette with no 4K counterpart) "
                f"should NOT be skipped: {analysis.classifications[idx]}"
            )


class TestPacificDisc1:
    """Counted, untimed episode groups from the captured six-disc HBO release."""

    def test_conversion_preserves_all_ten_untimed_episodes(self):
        _info, discs, _expected = _load_disc_fixture("pacific_disc1.json")

        assert [len(disc.episodes) for disc in discs] == [2, 2, 2, 2, 2, 0]
        assert [len(disc.extras) for disc in discs] == [3, 3, 3, 3, 3, 8]
        assert all(episode.runtime_seconds == 0 for disc in discs for episode in disc.episodes)

    def test_real_analysis_identifies_only_the_two_main_episodes(self, caplog):
        info, discs, expected = _load_disc_fixture("pacific_disc1.json")
        detail = load_show_detail("pacific_disc1.json")
        episodes = collect_tmdb_episodes_for_disc(
            detail, discs, 1, film_title="Pacific (The) (Mini-series)",
        )
        assert len(episodes) == 13
        caplog.set_level("DEBUG", logger="riplex.disc.analysis")

        analysis = analyze_disc(info, discs, is_movie=False, tmdb_episodes=episodes)

        assert analysis.disc_number == 1
        assert analysis.episode_count == 2
        assert analysis.total_episode_runtime == 6120
        assert [title.index for title in analysis.rippable_titles] == expected["rip_indices"]
        assert sorted(analysis.primary_title_indices) == expected["primary_indices"]
        for index, name in expected["episode_names"].items():
            assert analysis.classifications[int(index)] == f"{name} (1080p)"
            assert analysis.assessments[int(index)].identification == "Matched episode"
            assert analysis.assessments[int(index)].recommendation == "rip"
        for title in info.titles[2:]:
            assessment = analysis.assessments[title.index]
            assert assessment.recommendation == "skip"
            assert assessment.identification not in {"Matched episode", "Possible episode"}
        assert analysis.assessments[6].identification == "Duplicate"
        assert analysis.assessments[8].identification == "Duplicate"
        assert analysis.assessments[4].name == "Unknown"
        assert all(episode.runtime_seconds == 0 for disc in discs for episode in disc.episodes)
        assert "TMDb runtime fallback" in caplog.text
        assert "primary=[0, 1]" in caplog.text
