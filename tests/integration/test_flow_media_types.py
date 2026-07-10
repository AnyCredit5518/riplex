"""Media-type-targeted flow tests.

Each test parametrizes over exactly the fixtures whose media type it applies to
(movies, mini-series, single seasons, full series). As new fixtures of a given
type are generated from real rips, they're picked up automatically — so the
protected-scenario set grows with the media library.

The shared assertion for the orchestrate happy path is: from welcome, a single
loaded drive auto-reads and routes to the metadata picker; accepting the match
resolves the release and lands on the disc overview, with no crash.
"""

from __future__ import annotations

import pytest

from tests.support.fixtures import (
    miniseries_scenarios,
    movie_scenarios,
    season_scenarios,
    series_scenarios,
    tv_scenarios,
)


def _params(names, reason):
    """Parametrize over *names*, or a single skipped case when none exist yet."""
    if names:
        return names
    return [pytest.param("__none__", marks=pytest.mark.skip(reason=reason))]


def _drive_to_disc_overview(d):
    """Welcome -> (auto disc read) -> metadata -> accept match -> disc overview."""
    d.click("Rip Disc")
    assert d.current == "metadata", f"{d.scenario.name}: expected metadata, got {d.current}"
    d.click("Next")


def _assert_landed_on_overview(d):
    """Assert the release resolved.

    Scenarios with dvdcompare disc structure land on the disc overview; older
    rips whose snapshot recorded no dvdcompare data surface the release
    screen's "continue without" path instead. Both are valid, crash-free
    outcomes.
    """
    assert d.state.get("tmdb_match") is not None
    if d.scenario.planned_discs():
        assert d.current == "disc_overview", (
            f"{d.scenario.name} ({d.scenario.category}): expected disc_overview, got {d.current}"
        )
        assert d.state.get("release") is not None
        assert d.state.get("dvdcompare_discs")
    else:
        assert d.current == "release", (
            f"{d.scenario.name} ({d.scenario.category}): expected release, got {d.current}"
        )
        assert d.has_text("without") or d.has_text("No dvdcompare")
    assert not d.crashed()


# ---------------------------------------------------------------------------
# Movies
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", _params(movie_scenarios(), "no movie fixtures"))
def test_movie_orchestrate_reaches_disc_overview(gui, name):
    d = gui(name)
    _drive_to_disc_overview(d)
    _assert_landed_on_overview(d)
    assert d.state["tmdb_match"].media_type == "movie"


# ---------------------------------------------------------------------------
# TV — mini-series (limited / single-season)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", _params(miniseries_scenarios(), "no mini-series fixtures"))
def test_miniseries_orchestrate_reaches_disc_overview(gui, name):
    d = gui(name)
    _drive_to_disc_overview(d)
    _assert_landed_on_overview(d)
    assert d.state["tmdb_match"].media_type == "tv"


# ---------------------------------------------------------------------------
# TV — a single season of an ongoing multi-season show (a subset of the series
# fixtures, e.g. Psych Season 1).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", _params(season_scenarios(), "no single-season fixtures"))
def test_season_orchestrate_reaches_disc_overview(gui, name):
    d = gui(name)
    _drive_to_disc_overview(d)
    _assert_landed_on_overview(d)
    assert d.state["tmdb_match"].media_type == "tv"


# ---------------------------------------------------------------------------
# TV — any ongoing multi-season series (single-season rips like Psych today;
# complete-series sets automatically join as such fixtures are added).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", _params(series_scenarios(), "no TV series fixtures"))
def test_series_orchestrate_reaches_disc_overview(gui, name):
    d = gui(name)
    _drive_to_disc_overview(d)
    _assert_landed_on_overview(d)
    assert d.state["tmdb_match"].media_type == "tv"


# ---------------------------------------------------------------------------
# Every TV scenario, regardless of sub-type, must render its release's discs.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", _params(tv_scenarios(), "no TV fixtures"))
def test_tv_disc_overview_lists_discs(gui, name):
    d = gui(name)
    _drive_to_disc_overview(d)
    assert d.current == "disc_overview"
    assert d.has_text("Disc 1")
    assert not d.crashed()
