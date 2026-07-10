"""Resume / prefill fast paths.

When a folder was ripped before, the rip manifest records a stable TMDb id and
a dvdcompare film id + release name. Revisiting skips the pickers: the metadata
screen resolves the id straight to details, and the release screen fetches the
saved release by name. These paths historically drifted from the normal path;
here we assert they resolve and hand off without a picker or crash.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def base(gui):
    d = gui("the-matrix-1999")
    d.state.update({
        "workflow": "orchestrate",
        "title": d.scenario.title,
        "disc_info": d.scenario.disc_info(),
    })
    return d


def test_metadata_prefill_resolves_without_picker(base):
    base.state["_prefill_tmdb_source_id"] = "movie:603"

    base.navigate("metadata")

    match = base.state.get("tmdb_match")
    assert match is not None and match.source_id == "movie:603"
    # Resolved straight past the picker into the release lookup / overview.
    assert base.current in {"release", "disc_overview"}
    assert not base.crashed()


def test_release_prefill_resolves_saved_release(base):
    base.state.update({
        "tmdb_match": base.scenario.search_result(),
        "_prefill_dvdcompare_film_id": 12345,
        "_prefill_dvdcompare_release_name": base.scenario.release_name() or "Default Release",
    })

    base.navigate("release")

    assert base.state.get("release") is not None
    assert base.state.get("dvdcompare_discs")
    # No picker shown — went straight to the orchestrate overview.
    assert base.current == "disc_overview"
    assert not base.crashed()


def test_release_prefill_falls_back_on_name_mismatch(base):
    base.state.update({
        "tmdb_match": base.scenario.search_result(),
        "_prefill_dvdcompare_film_id": 12345,
        "_prefill_dvdcompare_release_name": "A Release That No Longer Exists",
    })

    base.navigate("release")

    # Saved release name no longer matches -> the prefill is abandoned and the
    # normal title lookup takes over, recovering gracefully with no crash.
    assert base.current == "disc_overview"
    assert base.state.get("release") is not None
    assert not base.crashed()
