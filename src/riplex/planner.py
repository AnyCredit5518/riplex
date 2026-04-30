"""Core planner: orchestrates metadata lookup and builds planned output."""

from __future__ import annotations

from riplex.metadata_provider import MetadataProvider, MetadataSearchResult
from riplex.models import (
    PlannedEpisode,
    PlannedMovie,
    PlannedSeason,
    PlannedShow,
    SearchRequest,
)
from riplex.normalize import (
    build_movie_paths,
    build_show_paths,
    episode_file_name,
    format_runtime,
    movie_file_name,
)
from riplex.ui import is_interactive, prompt_choice


_MAX_TMDB_CHOICES = 8


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


def _format_tmdb_option(r: MetadataSearchResult) -> str:
    """Format a single TMDb result for display in a numbered list."""
    year_str = str(r.year) if r.year else "?"
    overview = r.overview[:80] + "..." if len(r.overview) > 80 else r.overview
    parts = [f"{r.title} ({year_str}) [{r.media_type}]"]
    if overview:
        parts.append(f"  {overview}")
    return " - ".join(parts) if overview else parts[0]


def _pick_best(
    results: list[MetadataSearchResult],
    request: SearchRequest,
) -> MetadataSearchResult:
    """Select the best match from search results.

    In interactive mode, presents a numbered list when the match is
    ambiguous (multiple exact title matches, or no exact match at all).
    In non-interactive mode, prefers exact year match, then exact title
    match by popularity, then first result.
    """
    # If a year was provided, filter to matches first
    if request.year:
        year_matches = [r for r in results if r.year == request.year]
        if year_matches:
            results = year_matches

    # Find exact title matches (case-insensitive)
    query_lower = request.title.lower()
    exact = [r for r in results if r.title.lower() == query_lower]

    # Unambiguous: single exact match with year, or only one exact match
    if len(exact) == 1:
        return exact[0]
    if request.year and exact:
        # Year was provided and we already filtered; first exact match wins
        return exact[0]

    # Ambiguous or no exact match: prompt in interactive mode
    if is_interactive():
        candidates = results[:_MAX_TMDB_CHOICES]
        # Determine the auto-pick, then reorder so it's first
        auto_pick = exact[0] if exact else results[0]
        reordered = [auto_pick] + [r for r in candidates if r is not auto_pick]
        options = [_format_tmdb_option(r) for r in reordered]
        chosen = prompt_choice("Select a TMDb match:", options, default=0)
        return reordered[chosen]

    # Non-interactive fallback: first exact title match, then first result
    if exact:
        return exact[0]
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
