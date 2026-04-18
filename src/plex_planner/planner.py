"""Core planner: orchestrates metadata lookup and builds planned output."""

from __future__ import annotations

from plex_planner.metadata_provider import MetadataProvider, MetadataSearchResult
from plex_planner.models import (
    PlannedEpisode,
    PlannedMovie,
    PlannedSeason,
    PlannedShow,
    SearchRequest,
)
from plex_planner.normalize import (
    build_movie_paths,
    build_show_paths,
    episode_file_name,
    format_runtime,
    movie_file_name,
)


async def plan(
    request: SearchRequest,
    provider: MetadataProvider,
) -> PlannedMovie | PlannedShow:
    """Look up metadata and build a Plex-compatible plan.

    Returns a PlannedMovie or PlannedShow depending on what the metadata
    source identifies.
    """
    results = await provider.search(
        request.title,
        year=request.year,
        media_type=request.media_type,
    )
    if not results:
        raise LookupError(
            f"No results found for '{request.title}'"
            + (f" ({request.year})" if request.year else "")
        )

    best = _pick_best(results, request)

    if best.media_type == "movie":
        return await _plan_movie(best, provider, request)
    return await _plan_show(best, provider, request)


def _pick_best(
    results: list[MetadataSearchResult],
    request: SearchRequest,
) -> MetadataSearchResult:
    """Select the best match from search results.

    Prefers exact year match, then exact title match, then first result.
    """
    # If a year was provided, filter to matches first
    if request.year:
        year_matches = [r for r in results if r.year == request.year]
        if year_matches:
            results = year_matches

    # Prefer exact title match (case-insensitive)
    query_lower = request.title.lower()
    for r in results:
        if r.title.lower() == query_lower:
            return r

    return results[0]


async def _plan_movie(
    result: MetadataSearchResult,
    provider: MetadataProvider,
    request: SearchRequest,
) -> PlannedMovie:
    detail = await provider.get_movie_detail(result.source_id)

    paths = build_movie_paths(
        detail.title,
        detail.year,
        include_extras=request.include_extras_skeleton,
    )

    return PlannedMovie(
        canonical_title=detail.title,
        year=detail.year,
        runtime=format_runtime(detail.runtime_seconds),
        runtime_seconds=detail.runtime_seconds,
        relative_paths=paths,
        main_file=movie_file_name(detail.title, detail.year),
    )


async def _plan_show(
    result: MetadataSearchResult,
    provider: MetadataProvider,
    request: SearchRequest,
) -> PlannedShow:
    detail = await provider.get_show_detail(
        result.source_id,
        include_specials=request.include_specials,
    )

    seasons: list[PlannedSeason] = []
    for sm in detail.seasons:
        episodes: list[PlannedEpisode] = []
        for em in sm.episodes:
            fname = episode_file_name(
                detail.title,
                detail.year,
                em.season_number,
                em.episode_number,
                em.title,
            )
            episodes.append(
                PlannedEpisode(
                    season_number=em.season_number,
                    episode_number=em.episode_number,
                    title=em.title,
                    runtime=format_runtime(em.runtime_seconds),
                    runtime_seconds=em.runtime_seconds,
                    file_name=fname,
                )
            )
        seasons.append(
            PlannedSeason(season_number=sm.season_number, episodes=episodes)
        )

    season_numbers = [s.season_number for s in seasons]
    paths = build_show_paths(
        detail.title,
        detail.year,
        season_numbers,
        include_extras=request.include_extras_skeleton,
    )

    return PlannedShow(
        canonical_title=detail.title,
        year=detail.year,
        relative_paths=paths,
        seasons=seasons,
    )
