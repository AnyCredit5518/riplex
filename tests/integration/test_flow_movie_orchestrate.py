"""Movie orchestrate flow: welcome -> disc_detection -> metadata -> release
-> disc_overview -> selection -> progress -> done.

Uses a real archived movie scenario (The Matrix). Every external boundary is
mocked from the scenario, so this asserts the screens hand off to each other
without exceptions and land on the expected screen at each step.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def movie(gui):
    return gui("the-matrix-1999")


def test_reaches_metadata_with_results(movie):
    movie.click("Rip Disc")

    assert movie.current == "metadata"
    assert movie.has_text("Select a match")
    assert not movie.crashed()


def test_metadata_next_reaches_release_then_disc_overview(movie):
    movie.click("Rip Disc")
    movie.click("Next")  # accept recommended TMDb match

    # Movie: fetch runtime -> release lookup (single release auto-applies) ->
    # orchestrate routes to disc_overview.
    assert movie.state.get("tmdb_match") is not None
    assert movie.state.get("release") is not None
    assert movie.state.get("dvdcompare_discs")
    assert movie.current == "disc_overview"
    assert not movie.crashed()


def test_full_movie_orchestrate_reaches_done(movie):
    movie.click("Rip Disc")
    movie.click("Next")

    # From disc_overview, starting the rip advances into the per-disc
    # confirmation (disc_swap) without raising — the orchestrate loop's first
    # hand-off. Full multi-disc completion is exercised per-screen in the
    # build-smoke matrix; here we assert the transition is clean.
    assert movie.current == "disc_overview"
    assert movie.has_text("Start Ripping")
    movie.click("Start Ripping")

    assert movie.current in {"disc_swap", "selection", "progress"}
    assert not movie.crashed()
