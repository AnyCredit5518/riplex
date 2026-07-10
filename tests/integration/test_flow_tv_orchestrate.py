"""TV orchestrate flow: metadata (TV match) -> season_select -> release ->
disc_overview, with a real multi-disc archived scenario (Chernobyl).

season_select auto-skips for single-season / mini-series shows, so the happy
path lands on disc_overview showing the release's discs. The season_select and
disc_swap screens themselves are build-checked in the smoke matrix.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def tv(gui):
    return gui("chernobyl-2019")


def test_tv_match_routes_through_to_disc_overview(tv):
    tv.click("Rip Disc")
    assert tv.current == "metadata"

    tv.click("Next")  # accept recommended TV match

    match = tv.state.get("tmdb_match")
    assert match is not None and match.media_type == "tv"
    assert tv.state.get("release") is not None
    assert tv.state.get("dvdcompare_discs")
    assert tv.current == "disc_overview"
    assert not tv.crashed()


def test_tv_disc_overview_lists_multiple_discs(tv):
    tv.click("Rip Disc")
    tv.click("Next")

    # Chernobyl's release spans two discs.
    assert len(tv.state["dvdcompare_discs"]) == 2
    assert tv.has_text("Disc 1")
    assert tv.has_text("Disc 2")
    assert not tv.crashed()


def test_tv_start_ripping_advances_without_crash(tv):
    tv.click("Rip Disc")
    tv.click("Next")
    assert tv.current == "disc_overview"

    tv.click("Start Ripping")

    assert tv.current in {"disc_swap", "selection", "progress"}
    assert not tv.crashed()
