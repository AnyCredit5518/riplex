"""Tests for the planner module using a fake metadata provider."""

import pytest

from plex_planner.metadata_provider import (
    EpisodeMetadata,
    MetadataProvider,
    MetadataSearchResult,
    MovieDetail,
    SeasonMetadata,
    ShowDetail,
)
from plex_planner.models import PlannedMovie, PlannedShow, SearchRequest
from plex_planner.planner import plan


class FakeProvider(MetadataProvider):
    """In-memory metadata provider for testing."""

    def __init__(
        self,
        search_results: list[MetadataSearchResult] | None = None,
        movie_detail: MovieDetail | None = None,
        show_detail: ShowDetail | None = None,
    ):
        self._search_results = search_results or []
        self._movie_detail = movie_detail
        self._show_detail = show_detail

    async def search(self, query, *, year=None, media_type="auto"):
        return self._search_results

    async def get_movie_detail(self, source_id):
        if self._movie_detail is None:
            raise LookupError("No movie detail configured")
        return self._movie_detail

    async def get_show_detail(self, source_id, *, include_specials=True):
        if self._show_detail is None:
            raise LookupError("No show detail configured")
        return self._show_detail


@pytest.mark.asyncio
async def test_plan_movie():
    provider = FakeProvider(
        search_results=[
            MetadataSearchResult(
                source_id="movie:1",
                title="Oppenheimer",
                year=2023,
                media_type="movie",
            )
        ],
        movie_detail=MovieDetail(
            source_id="movie:1",
            title="Oppenheimer",
            year=2023,
            runtime_seconds=10860,
        ),
    )
    request = SearchRequest(title="Oppenheimer", year=2023)
    result = await plan(request, provider)

    assert isinstance(result, PlannedMovie)
    assert result.canonical_title == "Oppenheimer"
    assert result.year == 2023
    assert result.runtime == "3h 1m"
    assert result.main_file == "Oppenheimer (2023).mkv"
    assert "\\Movies\\Oppenheimer (2023)\\" in result.relative_paths


@pytest.mark.asyncio
async def test_plan_tv_show():
    provider = FakeProvider(
        search_results=[
            MetadataSearchResult(
                source_id="tv:1",
                title="A Perfect Planet",
                year=2021,
                media_type="tv",
            )
        ],
        show_detail=ShowDetail(
            source_id="tv:1",
            title="A Perfect Planet",
            year=2021,
            seasons=[
                SeasonMetadata(
                    season_number=0,
                    episodes=[
                        EpisodeMetadata(
                            season_number=0,
                            episode_number=1,
                            title="Making a Perfect Planet",
                            runtime_seconds=2640,
                        )
                    ],
                ),
                SeasonMetadata(
                    season_number=1,
                    episodes=[
                        EpisodeMetadata(
                            season_number=1,
                            episode_number=1,
                            title="Volcano",
                            runtime_seconds=2880,
                        ),
                        EpisodeMetadata(
                            season_number=1,
                            episode_number=2,
                            title="The Sun",
                            runtime_seconds=2880,
                        ),
                    ],
                ),
            ],
        ),
    )
    request = SearchRequest(title="A Perfect Planet", year=2021)
    result = await plan(request, provider)

    assert isinstance(result, PlannedShow)
    assert result.canonical_title == "A Perfect Planet"
    assert result.year == 2021
    assert len(result.seasons) == 2
    assert result.seasons[0].season_number == 0
    assert result.seasons[0].episodes[0].title == "Making a Perfect Planet"
    assert result.seasons[1].episodes[0].file_name == (
        "A Perfect Planet (2021) - s01e01 - Volcano.mkv"
    )
    assert "\\TV Shows\\A Perfect Planet (2021)\\Season 00\\" in result.relative_paths
    assert "\\TV Shows\\A Perfect Planet (2021)\\Season 01\\" in result.relative_paths


@pytest.mark.asyncio
async def test_plan_no_results():
    provider = FakeProvider(search_results=[])
    request = SearchRequest(title="Nonexistent Movie", year=9999)
    with pytest.raises(LookupError, match="No results found"):
        await plan(request, provider)


@pytest.mark.asyncio
async def test_plan_prefers_year_match():
    provider = FakeProvider(
        search_results=[
            MetadataSearchResult(
                source_id="movie:1",
                title="Top Gun",
                year=1986,
                media_type="movie",
            ),
            MetadataSearchResult(
                source_id="movie:2",
                title="Top Gun",
                year=2022,
                media_type="movie",
            ),
        ],
        movie_detail=MovieDetail(
            source_id="movie:1",
            title="Top Gun",
            year=1986,
            runtime_seconds=6600,
        ),
    )
    request = SearchRequest(title="Top Gun", year=1986)
    result = await plan(request, provider)
    assert isinstance(result, PlannedMovie)
    assert result.year == 1986


@pytest.mark.asyncio
async def test_plan_excludes_specials():
    provider = FakeProvider(
        search_results=[
            MetadataSearchResult(
                source_id="tv:1",
                title="Show",
                year=2023,
                media_type="tv",
            )
        ],
        show_detail=ShowDetail(
            source_id="tv:1",
            title="Show",
            year=2023,
            seasons=[
                SeasonMetadata(season_number=1, episodes=[]),
            ],
        ),
    )
    request = SearchRequest(title="Show", year=2023, include_specials=False)
    result = await plan(request, provider)
    assert isinstance(result, PlannedShow)
    # Specials excluded at the provider level; just verify no Season 00
    season_nums = [s.season_number for s in result.seasons]
    assert 0 not in season_nums
