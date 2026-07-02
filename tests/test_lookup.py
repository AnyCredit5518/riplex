from types import SimpleNamespace

import pytest

from riplex.lookup import lookup_metadata
from riplex.metadata.provider import MetadataProvider
from riplex.models import PlannedSeason, PlannedShow, SearchRequest


class _StubProvider(MetadataProvider):
    async def search(self, query, *, year=None, media_type="auto"):
        return []

    async def get_movie_detail(self, source_id):
        raise AssertionError("movie detail should not be called")

    async def get_show_detail(self, source_id, *, include_specials=True):
        raise AssertionError("show detail should not be called")


@pytest.mark.asyncio
async def test_lookup_metadata_qualifies_dvdcompare_title_for_tv_season(monkeypatch):
    async def _fake_pick_match(request, provider):
        # Only .media_type is read downstream in lookup_metadata.
        return SimpleNamespace(
            title="Scrubs", year=2001, media_type="tv", source_id="tv:1",
        )

    async def _fake_plan_show(match, provider, request):
        return PlannedShow(
            canonical_title="Scrubs",
            year=2001,
            seasons=[PlannedSeason(season_number=6, episodes=[])],
        )

    recorded = {}

    async def _fake_fetch_and_select_release(title, **kwargs):
        recorded["title"] = title
        recorded["kwargs"] = kwargs
        return [], ""

    monkeypatch.setattr("riplex.lookup.pick_match", _fake_pick_match)
    monkeypatch.setattr("riplex.lookup._plan_show", _fake_plan_show)
    monkeypatch.setattr("riplex.lookup.fetch_and_select_release", _fake_fetch_and_select_release)

    result = await lookup_metadata(
        SearchRequest(title="Scrubs", year=2001, season_number=6, media_type="tv"),
        _StubProvider(),
        disc_format="Blu-ray",
    )

    assert result.canonical == "Scrubs"
    assert recorded["title"] == "Scrubs: Season 6"
    assert recorded["kwargs"]["disc_format"] == "Blu-ray"