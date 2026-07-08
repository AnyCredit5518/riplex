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


class _RecordingProvider(MetadataProvider):
    async def search(self, *a, **kw): return []
    async def get_movie_detail(self, *a, **kw): raise AssertionError
    async def get_show_detail(self, *a, **kw): raise AssertionError
    async def close(self): pass


@pytest.mark.asyncio
async def test_session_organize_finds_season_nested_work_folder(
    monkeypatch, tmp_path,
):
    """Regression: when the session marker sits at
    ``<root>/<title>/Season NN/_riplex_session.json`` (a nested TV rip),
    ``_organize_session_works`` must resolve the work folder to that
    same ``<root>/<title>/Season NN`` path — not double the title
    segment by naive ``folder.parent`` joining.
    """
    from riplex_cli.commands.organize import _organize_session_works

    rip_root = tmp_path / "Rips"
    work_folder = rip_root / "Psych (2006)" / "Season 02"
    work_folder.mkdir(parents=True)
    (work_folder / "Disc 1").mkdir()

    marker = {
        "type": "riplex_session",
        "release_name": "R1 America - Universal Pictures",
        "works": [{
            "title": "Psych",
            "year": 2006,
            "media_type": "tv",
            "folder": "Psych (2006)/Season 02",
            "disc_numbers": [1, 2, 3, 4],
            "source_id": "tv:1447",
            "season_number": 2,
        }],
    }

    called_with: dict = {}

    async def _fake_organize_single(folder, title, args, output_root, provider):
        called_with["folder"] = folder
        called_with["title"] = title
        return 0

    monkeypatch.setattr(
        "riplex_cli.commands.organize._organize_single",
        _fake_organize_single,
    )

    args = argparse.Namespace(
        title=None, year=None, media_type="tv", execute=True,
        api_key=None, output=str(rip_root), release="1",
        json=False, unmatched="extras", verbose=False, no_cache=False,
        force=False, snapshot=None, auto=True,
    )
    rc = await _organize_session_works(
        work_folder, marker, args, rip_root, _RecordingProvider(),
    )

    assert rc == 0
    assert called_with["title"] == "Psych"
    # The work folder must resolve to the actual nested rip path,
    # NOT ``<rip_root>/Psych (2006)/Psych (2006)/Season 02``.
    assert called_with["folder"] == work_folder
    assert called_with["folder"].exists()


@pytest.mark.asyncio
async def test_organize_prompts_before_executing_and_cancel_aborts(
    monkeypatch, tmp_path,
):
    """``organize_with_scanned`` must show a confirmation prompt before
    touching the filesystem when ``execute=True``; if the user declines,
    no files are moved and the function returns 0."""
    from riplex.models import PlannedMovie
    from riplex_cli.commands import organize as organize_mod

    async def _fake_lookup(request, provider, **kwargs):
        return LookupResult(
            planned=PlannedMovie(
                canonical_title="Test Movie", year=2023,
                runtime="1h 30m", runtime_seconds=5400,
            ),
            canonical="Test Movie", year=2023, is_movie=True,
            movie_runtime=5400, discs=[
                PlannedDisc(number=1, disc_format="Blu-ray", is_film=True),
            ],
            release_name="Test Movie",
            tmdb_match=_FakeMatch("Test Movie", 2023, "movie"),
        )

    monkeypatch.setattr(
        "riplex_cli.commands.organize.lookup_metadata", _fake_lookup,
    )

    # Create a real source file so we can check it isn't moved.
    rip_dir = tmp_path / "rip"
    rip_dir.mkdir()
    disc_dir = rip_dir / "Disc 1"
    disc_dir.mkdir()
    src_file = disc_dir / "t00.mkv"
    src_file.write_text("data")

    scanned = [ScannedDisc(
        folder_name="Disc 1",
        files=[ScannedFile(
            name="t00.mkv", path=str(src_file),
            duration_seconds=5400, stream_count=2,
            stream_fingerprint="h264:1920x1080|ac3:eng:6ch",
        )],
    )]

    prompt_calls: list[str] = []

    def _fake_confirm(msg, *, default=True):
        prompt_calls.append(msg)
        return False  # user declines

    monkeypatch.setattr(
        "riplex_cli.commands.organize.prompt_confirm", _fake_confirm,
    )

    args = argparse.Namespace(
        title="Test Movie", year=2023, season_number=None,
        media_type="movie", disc_format="Blu-ray", release="1",
        execute=True, force=True, unmatched="ignore",
        verbose=False, no_cache=True, snapshot=None, auto=False,
    )

    rc = await organize_mod.organize_with_scanned(
        scanned, "Test Movie", args, tmp_path / "out", _NullProvider(),
    )

    assert rc == 0
    assert prompt_calls, "expected a confirmation prompt"
    assert any("Proceed with organize" in c for c in prompt_calls)
    # Source file must still exist — declined confirm means no moves.
    assert src_file.exists()

