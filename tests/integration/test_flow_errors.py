"""Error / degraded-path flows.

Each external failure must surface a friendly in-screen message and must NOT
escape as an unhandled exception (which would trip the crash dialog). These
guard the try/except handling that historically regressed.
"""

from __future__ import annotations

import pytest

from riplex.disc.makemkv import RipResult
from tests.support.seed import populate_state


def test_makemkv_unavailable_shows_error_not_crash(gui):
    d = gui("the-matrix-1999", preflight_available=False)

    d.click("Rip Disc")

    # Stays on disc detection with an error panel; no crash dialog.
    assert d.current == "disc_detection"
    assert d.has_text("MakeMKV") and d.has_text("available")
    assert not d.crashed()


def test_tmdb_empty_results_shows_no_results(gui):
    d = gui("the-matrix-1999", tmdb_results=[])

    d.click("Rip Disc")

    assert d.current == "metadata"
    assert d.has_text("No results")
    assert not d.crashed()


def test_tmdb_error_shows_error_view(gui):
    d = gui("the-matrix-1999", tmdb_error=RuntimeError("tmdb boom"))

    d.click("Rip Disc")

    assert d.current == "metadata"
    # Error view offers to rip without metadata.
    assert d.has_text("without metadata") or d.has_text("tmdb boom")
    assert not d.crashed()


def test_dvdcompare_error_shows_no_releases(gui):
    d = gui("the-matrix-1999", dvdcompare_error=RuntimeError("dvdc boom"))

    d.click("Rip Disc")
    d.click("Next")  # accept TMDb match -> release lookup fails

    assert d.current == "release"
    assert d.has_text("without") or d.has_text("No dvdcompare")
    assert not d.crashed()


def test_rip_failure_records_error_without_crash(gui, tmp_path):
    d = gui("the-matrix-1999", rip_success=False)

    out_dir = tmp_path / "Movie (1999)" / "Disc 1"
    out_dir.mkdir(parents=True)
    d.state.update({
        "workflow": "rip",  # non-orchestrate: progress -> done at the end
        "drive": d.scenario.drive_info(),
        "disc_info": d.scenario.disc_info(),
        "selected_titles": [0],
        "output_dir": out_dir,
        "makemkvcon": None,
        "dvdcompare_discs": d.scenario.planned_discs(),
        "tmdb_match": d.scenario.search_result(),
    })

    d.navigate("progress")

    results = d.state.get("rip_results")
    assert results and all(not r.success for r in results)
    assert isinstance(results[0], RipResult)
    assert not d.crashed()


def test_orchestrate_rip_failure_returns_to_same_disc_with_error(gui, tmp_path):
    d = gui("the-matrix-1999", rip_success=False)
    scenario = d.scenario
    out_dir = tmp_path / "Movie (1999)" / "Disc 1"
    out_dir.mkdir(parents=True)
    d.state.update({
        "workflow": "orchestrate",
        "drive": scenario.drive_info(),
        "disc_info": scenario.disc_info(),
        "selected_titles": [0],
        "output_dir": out_dir,
        "makemkvcon": None,
        "dvdcompare_discs": scenario.planned_discs(),
        "tmdb_match": scenario.search_result(),
        "disc_queue": [1, 2],
        "current_disc_idx": 0,
        "_orchestrate_disc_number": 1,
        "all_rip_results": {},
        "ripped_discs": set(),
    })

    d.navigate("progress")

    assert d.current == "disc_swap"
    assert d.state["current_disc_idx"] == 0
    assert d.state["_orchestrate_disc_number"] == 1
    assert d.has_text("not ripped")
    assert d.has_text("retry")
    assert not d.crashed()


def test_orchestrate_done_does_not_claim_full_success_after_partial_failure(
    gui, tmp_path,
):
    d = gui("the-matrix-1999")
    populate_state(d.state, d.scenario, tmp_path)
    d.state["all_rip_results"] = {
        1: [
            RipResult(0, True, str(tmp_path / "title.mkv")),
            RipResult(1, False, "", "read failed"),
        ],
    }

    d.navigate("orchestrate_done")

    assert d.has_text("Ripping finished with failures")
    assert not d.has_text("All selected discs have been ripped")
    assert not d.crashed()
