"""Tests for lookup.resolve_disc_groups (CLI multi-work release helper)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from riplex.lookup import LookupResult, resolve_disc_groups
from riplex.metadata.provider import MetadataProvider
from riplex.models import PlannedDisc


class _FakeMatch:
    def __init__(self, title: str, year: int, media_type: str, source_id: str = "1"):
        self.title = title
        self.year = year
        self.media_type = media_type
        self.source_id = source_id


class _FakeProvider(MetadataProvider):
    """Returns canned results per query so we never hit TMDb."""

    def __init__(self, by_query: dict[str, list]):
        self._by_query = by_query
        self.searches: list[tuple[str, str]] = []

    async def search(self, query, *, year=None, media_type="auto"):
        self.searches.append((query, media_type))
        return list(self._by_query.get(query, []))

    async def get_movie_detail(self, source_id):
        raise AssertionError("not needed for these tests")

    async def get_show_detail(self, source_id, *, include_specials=True):
        raise AssertionError("not needed for these tests")


def _meta(discs: list[PlannedDisc], match, release_name: str = "") -> LookupResult:
    return LookupResult(
        planned=None,
        canonical=getattr(match, "title", "") if match else "",
        year=getattr(match, "year", None) if match else None,
        is_movie=False,
        movie_runtime=0,
        discs=discs,
        release_name=release_name,
        tmdb_match=match,
    )


class TestResolveDiscGroups:
    @pytest.mark.asyncio
    async def test_single_group_returns_empty(self):
        """Single-work releases fall through to the legacy single-plan path."""
        discs = [
            PlannedDisc(number=1, disc_format="Blu-ray", is_film=False),
            PlannedDisc(number=2, disc_format="Blu-ray", is_film=False),
        ]
        match = _FakeMatch("Show", 2010, "tv")
        provider = _FakeProvider({})

        groups = await resolve_disc_groups(
            _meta(discs, match), provider, interactive=False,
        )

        assert groups == []
        assert provider.searches == []  # no auto-fill needed

    @pytest.mark.asyncio
    async def test_multi_work_auto_fills_unassigned_groups(self):
        """Psych-shape: TV series + bonus films disc. Main group receives
        the seed match; film group's slots get best-guessed."""
        discs = [
            PlannedDisc(number=1, disc_format="Blu-ray", is_film=False),
            PlannedDisc(number=2, disc_format="Blu-ray", is_film=False),
            PlannedDisc(number=3, disc_format="Blu-ray", is_film=True),
        ]
        seed = _FakeMatch("Psych", 2006, "tv")
        provider = _FakeProvider({})  # no film-group query defined

        groups = await resolve_disc_groups(
            _meta(discs, seed, release_name="Psych: The Complete Series"),
            provider,
            interactive=False,
        )

        assert len(groups) == 2
        main = next(g for g in groups if g.kind == "main")
        film = next(g for g in groups if g.kind == "film")
        assert main.tmdb_match is seed
        assert main.source == "user"
        # Film group has no matches assigned (best_guess returned nothing).
        assert film.tmdb_match is None

    @pytest.mark.asyncio
    async def test_non_interactive_leaves_auto_fills_alone(self):
        """Without a TTY the function must not block; unresolved groups
        surface as skipped_reason at organize time."""
        discs = [
            PlannedDisc(number=1, disc_format="Blu-ray", is_film=False),
            PlannedDisc(number=2, disc_format="Blu-ray", is_film=True),
        ]
        seed = _FakeMatch("Foo", 2020, "movie")
        provider = _FakeProvider({})

        # Should not raise regardless of TTY state.
        groups = await resolve_disc_groups(
            _meta(discs, seed), provider, interactive=False,
        )
        assert len(groups) >= 1
