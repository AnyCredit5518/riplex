"""Focused regressions for title identity and recommendation evidence."""

from riplex.disc.analysis import _resolution_label, assess_title, classify_title
from riplex.disc.makemkv import DiscTitle


def _make_title(index: int, duration: int, resolution: str = "720x480") -> DiscTitle:
    return DiscTitle(
        index=index,
        name=f"Title {index}",
        duration_seconds=duration,
        chapters=6,
        size_bytes=2_000_000_000,
        filename=f"title_t{index:02d}.mkv",
        playlist=f"000{index:02d}.mpls",
        resolution=resolution,
        video_codec="Mpeg2",
        segment_count=1,
    )


def test_dvd_resolution_is_not_labeled_1080p():
    assert _resolution_label("720x480") == "480p"


def test_unclaimed_episode_slot_requires_plausible_runtime():
    """Psych title #9 is far too short to fill the 53:11 episode slot."""
    matched = [_make_title(i, runtime) for i, runtime in enumerate((2588, 2566, 2542))]
    title_nine = _make_title(9, 17 * 60 + 3)
    dvd_entries = [
        ("Spellingg Bee", 2588, "episode"),
        ("Speak Now or Forever Hold Your Piece", 2566, "episode"),
        ("Woman Seeking Dead Husband", 2542, "episode"),
        ("100 Clues", 53 * 60 + 11, "episode"),
    ]

    result = classify_title(
        title_nine,
        [*matched, title_nine],
        dvd_entries,
        False,
        None,
        sum(runtime for _, runtime, _ in dvd_entries),
        4,
    )

    assert result == "Unmatched content (480p, 17:03)"
    assessment = assess_title(result, is_rippable=False)
    assert assessment.recommendation == "skip"
    assert assessment.identification == "Unmatched"
    assert assessment.name == "Unknown"


def test_uncertain_episode_is_reviewed_and_kept_selected():
    assessment = assess_title("Episode (480p)", is_rippable=True)

    assert assessment.recommendation == "review"
    assert assessment.identification == "Possible episode"
    assert assessment.name == "Unknown"


def test_matched_episode_separates_identity_from_name():
    assessment = assess_title(
        "S03E02 - Murder? ... Anyone? ... Anyone? ... Bueller? (480p)",
        is_rippable=True,
    )

    assert assessment.recommendation == "rip"
    assert assessment.identification == "Matched episode"
    assert assessment.name == "Murder? ... Anyone? ... Anyone? ... Bueller?"
