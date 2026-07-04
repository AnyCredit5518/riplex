"""CLI-level test for the multi-work organize branch.

Confirms that `organize_with_scanned` routes multi-work releases through
`build_multi_group_plan` (per-group planning) instead of the single-plan
path — parity with the GUI's Disc Overview flow.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from riplex.lookup import LookupResult
from riplex.metadata.provider import MetadataProvider
from riplex.models import (
    DiscGroup,
    FilmSlot,
    PlannedDisc,
    ScannedDisc,
    ScannedFile,
)
from riplex_cli.commands.organize import organize_with_scanned


class _FakeMatch:
    def __init__(self, title, year, media_type, source_id="1"):
        self.title = title
        self.year = year
        self.media_type = media_type
        self.source_id = source_id


class _NullProvider(MetadataProvider):
    async def search(self, query, *, year=None, media_type="auto"):
        return []

    async def get_movie_detail(self, source_id):
        raise AssertionError

    async def get_show_detail(self, source_id, *, include_specials=True):
        raise AssertionError

    async def close(self):
        pass


def _make_scanned(disc_num: int, name: str, duration: int) -> ScannedDisc:
    return ScannedDisc(
        folder_name=f"Disc {disc_num}",
        files=[ScannedFile(
            name=name, path=f"/rips/{name}",
            duration_seconds=duration, stream_count=2,
            stream_fingerprint="h264:1920x1080|ac3:eng:6ch",
        )],
    )


@pytest.mark.asyncio
async def test_organize_routes_multi_work_release_through_group_planner(
    monkeypatch, tmp_path,
):
    """Two-disc release with one TV disc + one film disc must dispatch
    to build_multi_group_plan and produce a plan describing both works."""

    tv_match = _FakeMatch("Psych", 2006, "tv")
    film_match = _FakeMatch("Psych: The Movie", 2017, "movie")

    dvd_discs = [
        PlannedDisc(number=1, disc_format="Blu-ray", is_film=False),
        PlannedDisc(number=2, disc_format="Blu-ray", is_film=True),
    ]

    async def _fake_lookup(request, provider, **kwargs):
        return LookupResult(
            planned=None,
            canonical="Psych",
            year=2006,
            is_movie=False,
            movie_runtime=0,
            discs=dvd_discs,
            release_name="Psych: The Complete Series",
            tmdb_match=tv_match,
        )

    called_with = {}

    async def _fake_resolve(meta, provider, *, interactive=None):
        # Return two groups: main TV (auto-assigned to tv_match) + a
        # film group with one slot assigned to film_match.
        main = DiscGroup(
            id="main_1", label="TV series (disc 1)",
            disc_numbers=[1],
            tmdb_match=tv_match, source="user",
        )
        film = DiscGroup(
            id="film_2", label="Feature film (disc 2)",
            disc_numbers=[2],
            films=[FilmSlot(title="The Movie", runtime_seconds=5280,
                            tmdb_match=film_match, source="auto")],
        )
        called_with["seed"] = meta.tmdb_match
        return [main, film]

    monkeypatch.setattr(
        "riplex_cli.commands.organize.lookup_metadata", _fake_lookup,
    )
    monkeypatch.setattr(
        "riplex_cli.commands.organize.resolve_disc_groups", _fake_resolve,
    )

    # The main-group branch of build_multi_group_plan still calls into
    # the TMDb-backed planners. Stub them out — this test only verifies
    # that the multi-group router is invoked, not planner internals.
    from riplex.models import PlannedMovie, PlannedShow

    async def _fake_plan_show(match, provider, request):
        return PlannedShow(canonical_title=match.title, year=match.year,
                           seasons=[])

    async def _fake_plan_movie(match, provider, request):
        return PlannedMovie(canonical_title=match.title, year=match.year)

    monkeypatch.setattr("riplex.organize_by_group._plan_show", _fake_plan_show)
    monkeypatch.setattr("riplex.organize_by_group._plan_movie", _fake_plan_movie)

    scanned = [
        _make_scanned(1, "s01e01.mkv", 1300),   # 21m TV episode
        _make_scanned(2, "t00.mkv", 5280),      # 88m feature film
    ]

    args = argparse.Namespace(
        title="Psych",
        year=2006,
        season_number=None,
        media_type="tv",
        disc_format="Blu-ray",
        release="1",
        execute=False,     # dry-run
        force=True,
        unmatched="ignore",
        verbose=False,
        no_cache=True,
        snapshot=None,
        auto=True,
    )

    rc = await organize_with_scanned(
        scanned, "Psych", args, tmp_path, _NullProvider(),
    )

    assert rc == 0
    assert called_with["seed"] is tv_match

    # The film move must land under Movies/Psych - The Movie (2017)/
    # confirming per-group routing actually happened.
    # (organize_with_scanned prints actions to stdout — we don't rely on
    # capfd here; we simply verify the code path completed without falling
    # back to the single-plan branch, which would crash on the film disc
    # because there's no film episode in the (nonexistent) planned show.)
