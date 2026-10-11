"""Tests for shared title-selection policies."""

from types import SimpleNamespace

import pytest

from riplex.disc.analysis import analyze_disc
from riplex.disc.makemkv import DiscInfo, DiscTitle
from riplex.title_selection import select_title_indices


def _title(index: int):
    return SimpleNamespace(index=index)


def _disc_title(index: int, duration: int) -> DiscTitle:
    return DiscTitle(
        index=index,
        name=f"Title {index}",
        duration_seconds=duration,
        chapters=6,
        size_bytes=(index + 1) * 1024 ** 3,
        filename=f"title_t{index:02d}.mkv",
        playlist=f"000{index:02d}.mpls",
        resolution="1920x1080",
        video_codec="Mpeg4",
        segment_count=1,
    )


def _planned_disc(*, episodes=(), extras=(), is_film=False):
    return SimpleNamespace(
        number=1,
        disc_format="Blu-ray",
        is_film=is_film,
        episodes=[
            SimpleNamespace(title=title, runtime_seconds=runtime)
            for title, runtime in episodes
        ],
        extras=[
            SimpleNamespace(
                title=title,
                runtime_seconds=runtime,
                feature_type="featurette",
            )
            for title, runtime in extras
        ],
    )


def test_select_all_titles_in_disc_order():
    titles = [_title(3), _title(1), _title(7)]
    analysis = SimpleNamespace(rippable_titles=[], primary_title_indices=set())

    assert select_title_indices(titles, analysis, "all") == [3, 1, 7]


def test_select_recommended_titles_in_disc_order():
    titles = [_title(0), _title(1), _title(2)]
    analysis = SimpleNamespace(
        rippable_titles=[titles[2], titles[0]],
        primary_title_indices={0},
    )

    assert select_title_indices(titles, analysis, "recommended") == [0, 2]


def test_select_primary_titles_without_fallback():
    titles = [_title(0), _title(1), _title(2)]
    analysis = SimpleNamespace(
        rippable_titles=titles,
        primary_title_indices={1},
    )

    assert select_title_indices(titles, analysis, "primary") == [1]

    analysis.primary_title_indices = set()
    assert select_title_indices(titles, analysis, "primary") == []


def test_reject_unknown_policy():
    with pytest.raises(ValueError, match="unknown title-selection policy"):
        select_title_indices([], SimpleNamespace(), "everything")


def test_movie_analysis_marks_feature_variants_primary():
    titles = [_disc_title(0, 7200), _disc_title(1, 7800)]
    disc_info = DiscInfo("MOVIE", "Blu-ray disc", titles)

    analysis = analyze_disc(
        disc_info,
        [],
        is_movie=True,
        movie_runtime=7200,
    )

    assert analysis.primary_title_indices == {0, 1}


def test_tv_analysis_marks_assigned_episodes_primary_but_not_extras():
    titles = [
        _disc_title(0, 2400),
        _disc_title(1, 2500),
        _disc_title(2, 600),
    ]
    disc_info = DiscInfo("SHOW_D1", "Blu-ray disc", titles)
    disc = _planned_disc(
        episodes=(("Pilot", 2400), ("Second Episode", 2500)),
        extras=(("Making Of", 600),),
    )

    analysis = analyze_disc(
        disc_info,
        [disc],
        disc_number=1,
        is_movie=False,
    )

    assert analysis.primary_title_indices == {0, 1}
    assert 2 in {title.index for title in analysis.rippable_titles}


def test_tv_analysis_does_not_guess_primary_episodes_without_metadata():
    titles = [_disc_title(0, 2400), _disc_title(1, 2500)]
    disc_info = DiscInfo("SHOW", "Blu-ray disc", titles)

    analysis = analyze_disc(disc_info, [], is_movie=False)

    assert analysis.primary_title_indices == set()
    assert [title.index for title in analysis.rippable_titles] == [0, 1]


def test_bonus_only_disc_has_no_primary_titles():
    titles = [_disc_title(0, 1200)]
    disc_info = DiscInfo("BONUS_D1", "Blu-ray disc", titles)
    disc = _planned_disc(extras=(("Documentary", 1200),))

    analysis = analyze_disc(
        disc_info,
        [disc],
        disc_number=1,
        is_movie=True,
        movie_runtime=7200,
    )

    assert analysis.primary_title_indices == set()
    assert [title.index for title in analysis.rippable_titles] == [0]