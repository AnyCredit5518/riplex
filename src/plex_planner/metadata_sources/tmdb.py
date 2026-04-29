"""TMDb (The Movie Database) metadata provider.

TMDb is the primary metadata agent Plex uses for movies and is well-supported
for TV shows as well. This provider queries the TMDb API v3.

Requires a TMDb API key, provided via the TMDB_API_KEY environment variable
or passed directly to the constructor.
"""

from __future__ import annotations

import os
from typing import Literal

import httpx

from plex_planner import cache
from plex_planner.metadata_provider import (
    EpisodeMetadata,
    MetadataProvider,
    MetadataSearchResult,
    MovieDetail,
    SeasonMetadata,
    ShowDetail,
)

TMDB_BASE_URL = "https://api.themoviedb.org/3"
_TMDB_TTL_DAYS = 7


class TmdbProvider(MetadataProvider):
    """Metadata provider backed by TMDb API v3."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("TMDB_API_KEY", "")
        if not self._api_key:
            raise ValueError(
                "TMDb API key is required. Pass --api-key, set the "
                "TMDB_API_KEY environment variable, or add tmdb_api_key "
                "to your config file."
            )
        self._client = httpx.AsyncClient(
            base_url=TMDB_BASE_URL,
            params={"api_key": self._api_key},
            timeout=30.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _get_json(
        self,
        path: str,
        params: dict | None = None,
        cache_ns: str | None = None,
        cache_key: str | None = None,
    ) -> dict:
        """GET a TMDb endpoint, with optional caching."""
        if cache_ns and cache_key:
            cached = cache.cache_get(cache_ns, cache_key, ttl_days=_TMDB_TTL_DAYS)
            if cached is not None:
                return cached
        resp = await self._client.get(path, params=params)
        resp.raise_for_status()
        data = resp.json()
        if cache_ns and cache_key:
            cache.cache_set(cache_ns, cache_key, data)
        return data

    # -- search ---------------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        year: int | None = None,
        media_type: Literal["movie", "tv", "auto"] = "auto",
    ) -> list[MetadataSearchResult]:
        results: list[MetadataSearchResult] = []

        if media_type in ("movie", "auto"):
            results.extend(await self._search_movies(query, year))

        if media_type in ("tv", "auto"):
            results.extend(await self._search_tv(query, year))

        # Sort by descending popularity (TMDb returns popularity-ordered, but
        # we merged two lists).
        results.sort(key=lambda r: r.popularity, reverse=True)
        return results

    async def _search_movies(
        self, query: str, year: int | None
    ) -> list[MetadataSearchResult]:
        params: dict[str, str | int] = {"query": query}
        if year:
            params["year"] = year
        ck = cache.hash_key(f"movie|{query}|{year}")
        data = await self._get_json("/search/movie", params=params,
                                    cache_ns="tmdb/search", cache_key=ck)
        out: list[MetadataSearchResult] = []
        for item in data.get("results", []):
            release = item.get("release_date", "") or ""
            item_year = int(release[:4]) if len(release) >= 4 else None
            out.append(
                MetadataSearchResult(
                    source_id=f"movie:{item['id']}",
                    title=item.get("title", ""),
                    year=item_year,
                    media_type="movie",
                    overview=item.get("overview", ""),
                    popularity=item.get("popularity", 0.0),
                )
            )
        return out

    async def _search_tv(
        self, query: str, year: int | None
    ) -> list[MetadataSearchResult]:
        params: dict[str, str | int] = {"query": query}
        if year:
            params["first_air_date_year"] = year
        ck = cache.hash_key(f"tv|{query}|{year}")
        data = await self._get_json("/search/tv", params=params,
                                    cache_ns="tmdb/search", cache_key=ck)
        out: list[MetadataSearchResult] = []
        for item in data.get("results", []):
            air_date = item.get("first_air_date", "") or ""
            item_year = int(air_date[:4]) if len(air_date) >= 4 else None
            out.append(
                MetadataSearchResult(
                    source_id=f"tv:{item['id']}",
                    title=item.get("name", ""),
                    year=item_year,
                    media_type="tv",
                    overview=item.get("overview", ""),
                    popularity=item.get("popularity", 0.0),
                )
            )
        return out

    # -- movie detail ---------------------------------------------------------

    async def get_movie_detail(self, source_id: str) -> MovieDetail:
        _, tmdb_id = source_id.split(":", 1)
        data = await self._get_json(f"/movie/{tmdb_id}",
                                    cache_ns="tmdb/movies", cache_key=tmdb_id)
        release = data.get("release_date", "") or ""
        year = int(release[:4]) if len(release) >= 4 else 0
        runtime_minutes = data.get("runtime") or 0
        return MovieDetail(
            source_id=source_id,
            title=data.get("title", ""),
            year=year,
            runtime_seconds=runtime_minutes * 60,
            overview=data.get("overview", ""),
        )

    # -- show detail ----------------------------------------------------------

    async def get_show_detail(
        self, source_id: str, *, include_specials: bool = True
    ) -> ShowDetail:
        _, tmdb_id = source_id.split(":", 1)
        data = await self._get_json(f"/tv/{tmdb_id}",
                                    cache_ns="tmdb/shows", cache_key=tmdb_id)

        air_date = data.get("first_air_date", "") or ""
        year = int(air_date[:4]) if len(air_date) >= 4 else 0

        season_list: list[SeasonMetadata] = []
        for s in data.get("seasons", []):
            sn = s.get("season_number", 0)
            if sn == 0 and not include_specials:
                continue
            season_detail = await self._fetch_season(tmdb_id, sn)
            season_list.append(season_detail)

        return ShowDetail(
            source_id=source_id,
            title=data.get("name", ""),
            year=year,
            seasons=season_list,
            overview=data.get("overview", ""),
        )

    async def _fetch_season(
        self, tmdb_id: str, season_number: int
    ) -> SeasonMetadata:
        ck = f"{tmdb_id}_s{season_number}"
        data = await self._get_json(
            f"/tv/{tmdb_id}/season/{season_number}",
            cache_ns="tmdb/seasons", cache_key=ck,
        )

        episodes: list[EpisodeMetadata] = []
        for ep in data.get("episodes", []):
            runtime_min = ep.get("runtime") or 0
            episodes.append(
                EpisodeMetadata(
                    season_number=season_number,
                    episode_number=ep.get("episode_number", 0),
                    title=ep.get("name", ""),
                    runtime_seconds=runtime_min * 60,
                    overview=ep.get("overview", ""),
                )
            )
        return SeasonMetadata(season_number=season_number, episodes=episodes)
