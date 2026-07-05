"""TMDb + dvdcompare metadata lookup pipeline.

Provides a single entry point for the common pattern of:
1. Look up canonical metadata from TMDb (via pick_match + _plan_movie/_plan_show)
2. Optionally fetch per-disc content breakdowns from dvdcompare
3. Return normalized fields used by all downstream commands

Also exposes :func:`resolve_disc_groups` — the CLI-side counterpart to the
GUI's Disc Overview auto-fill loop for multi-work releases.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field

from riplex.disc.analysis import group_release_discs
from riplex.disc.provider import DiscProvider, select_dvdcompare_release
from riplex.metadata.autosearch import best_guess, strip_boxset_suffix
from riplex.metadata.planner import _plan_movie, _plan_show, pick_match
from riplex.metadata.provider import MetadataProvider, MetadataSearchResult
from riplex.models import DiscGroup, PlannedDisc, PlannedMovie, SearchRequest
from riplex.ui import is_interactive, prompt_choice

log = logging.getLogger(__name__)


@dataclass
class LookupResult:
    """Normalized TMDb + dvdcompare metadata lookup result."""

    planned: PlannedMovie  # PlannedMovie | PlannedShow (union not expressible cleanly)
    canonical: str
    year: int
    is_movie: bool
    movie_runtime: int | None
    discs: list[PlannedDisc] = field(default_factory=list)
    release_name: str = ""
    dvdcompare_error: Exception | None = field(default=None, repr=False)
    # The MetadataSearchResult that seeded ``planned``. Kept so
    # downstream group routing can re-plan each work in a multi-work
    # release without re-doing the top-level TMDb search.
    tmdb_match: MetadataSearchResult | None = None
    # dvdcompare film id (``fid``) of the selected release's film.
    # Persisted into ``_rip_manifest.json`` so the organize screen can
    # skip the release picker on a re-visit.
    dvdcompare_film_id: int | None = None


async def lookup_metadata(
    request: SearchRequest,
    provider: MetadataProvider,
    *,
    disc_format: str | None = None,
    disc_info: object | None = None,
    preferred_release: str | None = None,
    skip_dvdcompare: bool = False,
) -> LookupResult:
    """Run TMDb metadata lookup, optionally followed by dvdcompare disc lookup.

    The TMDb ``plan()`` call is always performed.  The dvdcompare
    ``fetch_and_select_release()`` call is performed unless
    *skip_dvdcompare* is ``True``.

    When dvdcompare lookup fails, the error is captured in
    :attr:`LookupResult.dvdcompare_error` rather than raised, so the
    TMDb result is always available.  Callers decide whether to treat
    a dvdcompare failure as a warning or a fatal error.
    """
    match = await pick_match(request, provider)
    if match.media_type == "movie":
        result = await _plan_movie(match, provider, request)
    else:
        result = await _plan_show(match, provider, request)

    is_movie = isinstance(result, PlannedMovie)
    canonical = result.canonical_title
    year = result.year
    movie_runtime = result.runtime_seconds if is_movie else None

    discs: list[PlannedDisc] = []
    release_name = ""
    dvdcompare_error: Exception | None = None
    dvdcompare_film_id: int | None = None

    if not skip_dvdcompare:
        try:
            dvdcompare_title = canonical
            if not is_movie and request.season_number is not None:
                dvdcompare_title = f"{canonical}: Season {request.season_number}"
            # Split fetch + select so we can capture film.film_id
            # alongside the release. Kept as one code path (was one
            # call to ``fetch_and_select_release``) but broken out to
            # expose the film identity for downstream manifest writes.
            provider_dc = DiscProvider()
            film = await provider_dc.fetch_film(
                dvdcompare_title, disc_format, year=year,
            )
            discs, release_name = select_dvdcompare_release(
                film, disc_info=disc_info, preferred=preferred_release,
            )
            dvdcompare_film_id = getattr(film, "film_id", None)
        except SystemExit:
            raise
        except Exception as exc:
            dvdcompare_error = exc

    return LookupResult(
        planned=result,
        canonical=canonical,
        year=year,
        is_movie=is_movie,
        movie_runtime=movie_runtime,
        discs=discs,
        release_name=release_name,
        dvdcompare_error=dvdcompare_error,
        tmdb_match=match,
        dvdcompare_film_id=dvdcompare_film_id,
    )


async def resolve_disc_groups(
    meta: LookupResult,
    provider: MetadataProvider,
    *,
    interactive: bool | None = None,
) -> list[DiscGroup]:
    """Split ``meta.discs`` into per-work groups and resolve TMDb matches.

    Mirrors the GUI's Disc Overview auto-fill flow for CLI callers. The
    seed TMDb match on ``meta.tmdb_match`` is attached to the group whose
    kind matches its media type; every remaining unfilled group / film
    slot is filled by :func:`~riplex.metadata.autosearch.best_guess`. In
    interactive mode we then prompt the user to confirm each auto-fill
    (or override it via a numbered search). In non-interactive mode
    auto-fills stand and unresolved slots surface as
    ``skipped_reason='no TMDb match assigned'`` at organize time.

    Returns an empty list when there's only one group and it already has
    a match — callers should fall back to the legacy single-plan path in
    that case (no behavior change for single-work releases).
    """
    if interactive is None:
        interactive = is_interactive()

    groups = group_release_discs(meta.discs, meta.tmdb_match)
    if len(groups) <= 1:
        # Single-work release: caller uses the existing single-plan path.
        return []

    # Pass 1: eager auto-fill. Never blocks; failures leave slots empty
    # and the interactive pass (or non-interactive fallback) handles them.
    await _autofill_groups(
        groups, provider,
        seed_title=meta.canonical,
        release_name=meta.release_name,
    )

    _print_group_overview(groups)

    if not interactive:
        _log_unresolved(groups)
        return groups

    # Pass 2: interactive confirm/override. We only prompt for slots that
    # weren't set by the seed match (source == 'user'); auto-fills default
    # to confirm, and empty slots require a search-and-pick.
    await _interactive_confirm(groups, provider)
    return groups


async def _autofill_groups(
    groups: list[DiscGroup],
    provider: MetadataProvider,
    *,
    seed_title: str,
    release_name: str,
) -> None:
    """Fill every unassigned group / film slot via ``best_guess``.

    Same fallback query chain as the GUI's ``_autofill_worker``:
    default_search_title → seed_title (canonical from top-level match) →
    release_name → ``""``. Boxset markers are stripped so TMDb sees a
    bare title.
    """
    for g in groups:
        if g.films:
            for idx, film in enumerate(g.films):
                if film.tmdb_match is not None:
                    continue
                got = await best_guess(provider, film.title, media_type="movie")
                if got is None:
                    log.info("Auto-fill: %s films[%d] '%s' no confident guess",
                             g.id, idx, film.title)
                    continue
                match, _score = got
                film.tmdb_match = match
                film.source = "auto"
                log.info("Auto-fill: %s films[%d] '%s' -> '%s (%s)'",
                         g.id, idx, film.title, match.title, match.year)
        else:
            if g.tmdb_match is not None:
                continue
            raw_query = (
                g.default_search_title or seed_title or release_name or ""
            )
            query = strip_boxset_suffix(raw_query)
            if not query.strip():
                log.info("Auto-fill: %s skipped (empty query)", g.id)
                continue
            got = await best_guess(provider, query, media_type="auto")
            if got is None:
                log.info("Auto-fill: %s no confident guess for %r",
                         g.id, query)
                continue
            match, _score = got
            g.tmdb_match = match
            g.source = "auto"
            log.info("Auto-fill: %s '%s' -> '%s (%s)'",
                     g.id, query, match.title, match.year)


def _print_group_overview(groups: list[DiscGroup]) -> None:
    """Human-readable group summary printed once, before any prompts.

    The user sees the whole shape of the release (which discs belong to
    which work, what auto-fill guessed for each) before being asked to
    confirm anything.
    """
    print("\nThis release contains multiple works or multi-film discs:",
          file=sys.stderr)
    for g in groups:
        print(f"  * {g.label}", file=sys.stderr)
        if g.films:
            for idx, f in enumerate(g.films, 1):
                match_str = _format_match(f.tmdb_match, f.source)
                print(f"      Film {idx}: {f.title!r} -> {match_str}",
                      file=sys.stderr)
        else:
            match_str = _format_match(g.tmdb_match, g.source)
            print(f"      -> {match_str}", file=sys.stderr)
    print("", file=sys.stderr)


def _format_match(match, source) -> str:
    if match is None:
        return "(no match — needs assignment)"
    label = f"{match.title} ({match.year or '?'}) [{match.media_type}]"
    if source == "user":
        return f"{label}  [confirmed]"
    if source == "auto":
        return f"{label}  [auto-filled — needs confirm]"
    return label


def _log_unresolved(groups: list[DiscGroup]) -> None:
    for g in groups:
        if not g.is_complete():
            print(f"Warning: group {g.label!r} has no TMDb match assigned; "
                  f"its discs will be skipped at organize time.",
                  file=sys.stderr)


async def _interactive_confirm(
    groups: list[DiscGroup],
    provider: MetadataProvider,
) -> None:
    """Walk groups, confirming or overriding each unresolved slot.

    User-source matches (from the top-level metadata pick) are treated as
    already confirmed and skipped. Auto-fills and empty slots trigger a
    single prompt per slot with three choices: accept, search, or skip.
    """
    for g in groups:
        if g.films:
            for idx, film in enumerate(g.films):
                if film.source == "user":
                    continue
                new_match = await _prompt_slot_match(
                    provider,
                    slot_label=f"{g.label} — film {idx + 1}: {film.title!r}",
                    current_match=film.tmdb_match,
                    current_source=film.source,
                    default_query=film.title,
                    media_type="movie",
                )
                if new_match is not None:
                    film.tmdb_match = new_match
                    film.source = "user"
        else:
            if g.source == "user":
                continue
            new_match = await _prompt_slot_match(
                provider,
                slot_label=g.label,
                current_match=g.tmdb_match,
                current_source=g.source,
                default_query=g.default_search_title,
                media_type="auto",
            )
            if new_match is not None:
                g.tmdb_match = new_match
                g.source = "user"


async def _prompt_slot_match(
    provider: MetadataProvider,
    *,
    slot_label: str,
    current_match,
    current_source,
    default_query: str,
    media_type: str,
) -> MetadataSearchResult | None:
    """Show one prompt for a slot and return the picked match (or None
    to leave the slot untouched — which happens for skip and for
    accepting the existing auto-fill).
    """
    print(f"\n{slot_label}", file=sys.stderr)
    if current_match is not None:
        current_str = _format_match(current_match, current_source)
        options = [
            f"Keep auto-fill: {current_str}",
            "Search TMDb for a different match",
            "Skip this slot (won't organize)",
        ]
    else:
        options = [
            "Search TMDb for a match",
            "Skip this slot (won't organize)",
        ]
    choice = prompt_choice("How should this slot be filled?", options, default=0)

    if current_match is not None:
        if choice == 0:
            # Accept auto-fill: promote to user-confirmed by returning it.
            return current_match
        if choice == 2:
            return None
        # choice == 1: search
    else:
        if choice == 1:
            return None
        # choice == 0: search

    return await _search_and_pick(provider, default_query, media_type)


async def _search_and_pick(
    provider: MetadataProvider,
    default_query: str,
    media_type: str,
) -> MetadataSearchResult | None:
    """Prompt for a search query, run it, and let the user pick a result."""
    from riplex.ui import prompt_text  # local import: ui is CLI-only surface

    query = prompt_text("Search query", default=default_query or "").strip()
    if not query:
        print("(empty query — leaving slot unchanged)", file=sys.stderr)
        return None
    try:
        results = await provider.search(query, media_type=media_type)
    except Exception as exc:
        print(f"Search failed: {exc}", file=sys.stderr)
        return None
    if not results:
        print("No results found.", file=sys.stderr)
        return None
    top = results[:8]
    options = [
        f"{r.title} ({r.year or '?'}) [{r.media_type}]"
        for r in top
    ]
    options.append("(none of these — skip slot)")
    choice = prompt_choice("Pick a match:", options, default=0)
    if choice == len(top):
        return None
    return top[choice]
