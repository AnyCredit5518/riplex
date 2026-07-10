"""Fixture-integrity smoke test.

Every committed scenario must load and reconstruct into the real riplex
dataclasses without error. This guards both the generator's output and the
loader against drift in the underlying dataclass shapes.
"""

from __future__ import annotations

import pytest

from tests.support.fixtures import (
    ALL_CATEGORIES,
    available_scenarios,
    category_counts,
    load_scenario,
)

SCENARIOS = available_scenarios()


def test_there_are_committed_scenarios():
    assert SCENARIOS, "no scenario fixtures found under tests/fixtures/gui/scenarios/"


@pytest.mark.parametrize("name", SCENARIOS)
def test_scenario_reconstructs_real_dataclasses(name):
    sc = load_scenario(name)

    # makemkv side: every disc rebuilds into a DiscInfo with titles.
    assert sc.disc_numbers, f"{name}: no discs"
    for n in sc.disc_numbers:
        di = sc.disc_info(n)
        assert di.titles, f"{name}: disc {n} has no titles"
        for t in di.titles:
            assert t.index is not None
            assert t.duration_seconds >= 0
        drive = sc.drive_info(n)
        assert drive.has_disc and drive.is_present

    # TMDb side.
    results = sc.search_results()
    assert results and results[0].source_id
    if sc.is_tv:
        show = sc.show_detail()
        assert show.source_id
    else:
        movie = sc.movie_detail()
        assert movie.source_id

    # dvdcompare side.
    for disc in sc.planned_discs():
        assert disc.number >= 1


@pytest.mark.parametrize("name", SCENARIOS)
def test_scenario_preflight_is_available(name):
    sc = load_scenario(name)
    pf = sc.preflight()
    assert pf.available


@pytest.mark.parametrize("name", SCENARIOS)
def test_scenario_has_valid_category(name):
    sc = load_scenario(name)
    assert sc.category in ALL_CATEGORIES, f"{name}: unexpected category {sc.category!r}"


def test_category_counts_cover_every_scenario():
    counts = category_counts()
    assert sum(counts.values()) == len(SCENARIOS)
    # At minimum the corpus carries the media types the flows target.
    assert counts["movie"] > 0
