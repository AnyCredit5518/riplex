"""Tests for disc analysis using real disc fixtures.

Uses JSON fixtures that capture disc info + dvdcompare data to test
the full classification pipeline without needing a physical disc.
"""

import json
from pathlib import Path

import pytest

from riplex.disc.analysis import analyze_disc, format_seconds
from riplex.disc.makemkv import DiscInfo, DiscTitle
from riplex.disc.provider import _convert_release
from riplex.models import PlannedDisc, PlannedEpisode, PlannedExtra


FIXTURES = Path(__file__).parent / "fixtures"


def _load_disc_fixture(name: str):
    """Load a disc fixture JSON and return (DiscInfo, dvdcompare_discs, expected).

    The fixture contains:
    - disc_info: raw DiscInfo with titles from makemkvcon
    - dvdcompare: raw dvdcompare feature tree (pre-conversion)
    - expected: expected classification results
    """
    path = FIXTURES / name
    data = json.loads(path.read_text(encoding="utf-8"))

    # Build DiscInfo
    titles = []
    for t in data["titles"]:
        titles.append(DiscTitle(
            index=t["index"],
            name=t.get("name", f"Title {t['index']}"),
            duration_seconds=t["duration_seconds"],
            chapters=t.get("chapters", 1),
            size_bytes=t["size_bytes"],
            filename=t.get("filename", f"title_t{t['index']:02d}.mkv"),
            playlist=t.get("playlist", ""),
            resolution=t["resolution"],
            video_codec=t.get("video_codec", ""),
            segment_count=t.get("segment_count", 1),
            segment_map=t.get("segment_map", ""),
        ))
    disc_info = DiscInfo(
        disc_name=data.get("disc_name", ""),
        disc_type=data.get("disc_type", "Blu-ray disc"),
        titles=titles,
    )

    # Build dvdcompare PlannedDisc objects by converting raw features
    # through _convert_release (same path as the real app)
    from dvdcompare.models import Disc as DvcDisc, Feature, Release

    dvdcompare_data = data.get("dvdcompare", {})
    dvc_discs = []
    for disc_data in dvdcompare_data.get("discs", []):
        features = _build_features(disc_data.get("features", []))
        dvc_discs.append(DvcDisc(
            number=disc_data["number"],
            format=disc_data.get("format", "Blu-ray"),
            is_film=disc_data.get("is_film", False),
            features=features,
        ))

    release = Release(
        name=dvdcompare_data.get("release_name", "Test Release"),
        discs=dvc_discs,
    )
    planned_discs = _convert_release(release)

    expected = data.get("expected", {})

    return disc_info, planned_discs, expected


def _build_features(features_data: list) -> list:
    """Recursively build dvdcompare Feature objects from JSON."""
    from dvdcompare.models import Feature

    features = []
    for f in features_data:
        children = _build_features(f.get("children", []))
        features.append(Feature(
            title=f["title"],
            runtime_seconds=f.get("runtime_seconds"),
            feature_type=f.get("feature_type"),
            is_play_all=f.get("is_play_all", False),
            children=children,
        ))
    return features


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
