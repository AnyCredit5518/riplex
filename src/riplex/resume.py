"""Rehydrate lookup state from an existing rip session marker.

Both the CLI (``riplex_cli/commands/orchestrate.py``) and the GUI
(``riplex_app/screens/disc_detection.py``) use this to skip the
season / TMDb / release prompts when the user is resuming a partial
rip. The adapter is a plain async function that produces a fully-
populated :class:`ResumedLookup`; both surfaces then just do their
own bookkeeping (state writes for the GUI, positional variables for
the CLI). All network / matching / backfill logic lives here so the
two surfaces cannot drift.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from riplex.manifest import ExistingSession
from riplex.metadata.provider import MetadataSearchResult
from riplex.title import parse_season_number

if TYPE_CHECKING:
    from riplex.disc.provider import FilmComparison, PlannedDisc

log = logging.getLogger(__name__)


@dataclass
class ResumedLookup:
    """Lookup state rebuilt from a session marker.

    Field parity with the subset of :class:`riplex.lookup.LookupResult`
    that downstream planning / organize code reads, plus the extra
    signals (``dvdcompare_film``, ``dvdcompare_film_title``,
    ``season_number``) that the GUI's downstream screens copy into
    ``app.state`` on the fresh-lookup path via ``release.py``.

    ``dvdcompare_error`` is set when the film / release fetch failed;
    callers decide whether to treat that as fatal (the CLI does) or as
    a warning (the GUI does — the user can still edit the release
    later).
    """

    canonical: str
    year: int
    is_movie: bool
    media_type: str
    tmdb_match: MetadataSearchResult
    movie_runtime: int | None = None
    dvdcompare_film: "FilmComparison | None" = None
    dvdcompare_film_id: int | None = None
    dvdcompare_film_title: str = ""
    release: object | None = None  # DvdcompareRelease
    release_name: str = ""
    discs: list["PlannedDisc"] = field(default_factory=list)
    season_number: int | None = None
    disc_format: str | None = None
    # TMDb ShowDetail for TV / movie detail for movies. Downstream
    # rip-guide classification cross-references its episode list to
    # enrich labels and demote dvdcompare episode-list duplicates
    # (e.g. Psych S3 D1 lists a bonus re-edit alongside the real
    # episode); without it those duplicates masquerade as episodes.
    show_detail: object | None = field(default=None, repr=False)
    # True when the picked movie is the primary work of a multi-work
    # release and lives on the pointer disc(s) as a non-pointer main
    # feature (Psych: The Complete Series disc 31 shape). Signals to
    # ``group_release_discs`` that the picked movie needs a dedicated
    # FilmSlot prepended to the pointer group rather than overwriting
    # one of the pointered slots.
    primary_movie_needs_slot: bool = False
    # Disc numbers dropped by the "one pick at a time" filter (movie
    # boxset primary-work discs, or cross-season TV discs). The GUI
    # surfaces these in an informational banner so the shortened disc
    # list doesn't look like riplex lost discs.
    hidden_disc_numbers: list[int] = field(default_factory=list)
    dvdcompare_error: Exception | None = field(default=None, repr=False)


def _season_from_film_title(film, tmdb_match) -> int | None:
    """Extract season number from a dvdcompare film title on TV resumes.

    dvdcompare's per-season TV pages carry the season in the film
    title (``"Psych: Season 1 (TV) (Blu-ray)"``). On resume, the
    marker often doesn't have a season either (bare ``PSYCH`` volume
    label) so parsing the film title is our only reliable source
    before rip time. Returns ``None`` for non-TV, empty titles, or
    boxsets whose title doesn't advertise a season.
    """
    if getattr(tmdb_match, "media_type", None) != "tv":
        return None
    title = getattr(film, "title", "") or ""
    if not title:
        return None
    return parse_season_number(title)


async def _rehydrate_tmdb_match(session: ExistingSession) -> MetadataSearchResult:
    """Best-effort TMDb backfill for legacy markers without source_id.

    Sessions written before ``source_id`` was persisted leave the id
    blank; the caller can still rip, but organize would need the id to
    fetch show/movie detail. Runs a fuzzy best-guess search against
    ``session.title`` and returns a real :class:`MetadataSearchResult`
    when the top hit is confident enough, or a minimal stub with an
    empty ``source_id`` when the lookup fails or scores below the
    threshold (matches today's GUI behavior).
    """
    stub = MetadataSearchResult(
        source_id=session.source_id,
        title=session.title,
        year=session.year,
        media_type=session.media_type,  # type: ignore[arg-type]
    )
    if session.source_id:
        return stub
    try:
        from riplex.config import get_api_key
        from riplex.metadata.autosearch import best_guess
        from riplex.metadata.sources.tmdb import TmdbProvider

        provider = TmdbProvider(get_api_key())
        try:
            got = await best_guess(
                provider, session.title,
                media_type=session.media_type or "auto",  # type: ignore[arg-type]
            )
        finally:
            await provider.close()
    except Exception as exc:
        log.warning("Resume: TMDb rehydration failed: %s", exc)
        return stub
    if got is None:
        log.info("Resume: TMDb best_guess had no confident match for %r", session.title)
        return stub
    match, _score = got
    log.info(
        "Resume: legacy marker had no source_id; TMDb rehydrated %r -> %s",
        session.title, match.source_id,
    )
    return match


async def resume_from_session(
    session: ExistingSession,
    *,
    disc_info: object | None = None,
) -> ResumedLookup:
    """Rebuild a full lookup result from an existing session marker.

    Parameters
    ----------
    session:
        The marker returned by :func:`riplex.manifest.find_existing_session`.
    disc_info:
        Live disc info from ``run_disc_info``. Used only as a fallback
        source for ``disc_format`` when the marker doesn't carry one.
        Optional — callers that haven't read the disc yet (e.g. the CLI
        wants to short-circuit before ``run_disc_info``) can pass
        ``None`` and the returned ``disc_format`` will be whatever the
        marker knew.

    Returns
    -------
    ResumedLookup
        A populated result. Any dvdcompare / TMDb failure is captured
        in ``dvdcompare_error`` rather than raised, so the ``tmdb_match``
        and the ripped-disc queue are always usable even in degraded
        network conditions.
    """
    tmdb_match = await _rehydrate_tmdb_match(session)

    from riplex.disc.provider import (
        DiscProvider, _convert_release, detect_disc_format,
    )

    disc_format = session.disc_format
    if not disc_format and disc_info is not None:
        disc_format = detect_disc_format(disc_info)

    is_movie = session.media_type == "movie"
    result = ResumedLookup(
        canonical=session.title,
        year=session.year,
        is_movie=is_movie,
        media_type=session.media_type,
        tmdb_match=tmdb_match,
        disc_format=disc_format,
    )

    try:
        provider = DiscProvider()
        # If the marker recorded a season, bias the dvdcompare film
        # lookup to that season's page: dvdcompare has one "film" per
        # TV season (``"Psych: Season 2 (TV) (Blu-ray)"``) and its
        # search matches on the title string. Without the bias, resume
        # would silently rehydrate to whatever season came back first
        # (typically Season 1). Movies never carry a season.
        lookup_title = session.title
        if (
            session.media_type == "tv"
            and session.season_number is not None
        ):
            lookup_title = f"{session.title}: Season {session.season_number}"
        film = await provider._fetch_film_cached(
            lookup_title, disc_format, year=session.year,
        )
    except Exception as exc:
        log.warning("Resume: dvdcompare film lookup failed: %s", exc)
        result.dvdcompare_error = exc
        return result

    result.dvdcompare_film = film
    result.dvdcompare_film_id = getattr(film, "film_id", None)
    result.dvdcompare_film_title = getattr(film, "title", "") or ""

    releases = getattr(film, "releases", []) or []
    picked = None
    if session.release_name and releases:
        picked = next(
            (r for r in releases if r.name == session.release_name),
            None,
        )
    if picked is None and releases:
        picked = releases[0]

    if picked is not None:
        result.release = picked
        result.release_name = getattr(picked, "name", "") or session.release_name
        try:
            result.discs = _convert_release(picked)
        except Exception as exc:
            log.warning("Resume: _convert_release failed: %s", exc)
            result.discs = []
    else:
        result.release_name = session.release_name

    # Prefer the season persisted in the marker (newer field). Fall
    # back to parsing the dvdcompare film title only for legacy
    # markers written before ``season_number`` was recorded.
    if session.season_number is not None:
        result.season_number = session.season_number
    else:
        result.season_number = _season_from_film_title(film, tmdb_match)

    # Mirror the "one pick at a time" filter that lookup.py and
    # release.py apply on the fresh-lookup path. Without this, a
    # resumed session with a multi-work boxset release (e.g. Psych:
    # The Complete Series — 30 TV discs + 1 standalone-movies disc)
    # would hand the full 31-disc set to downstream group / overview
    # code and mis-attribute the picked title.
    if result.discs:
        from riplex.disc.analysis import (
            filter_discs_to_picked_movie, filter_discs_to_season,
        )

        def _record_hidden(kept: list) -> None:
            kept_numbers = {getattr(d, "number", None) for d in kept}
            result.hidden_disc_numbers = [
                n for d in result.discs
                if (n := getattr(d, "number", None)) is not None
                and n not in kept_numbers
            ]

        original_count = len(result.discs)
        if is_movie:
            filtered = filter_discs_to_picked_movie(result.discs)
            if len(filtered) < original_count:
                result.primary_movie_needs_slot = True
                _record_hidden(filtered)
            result.discs = filtered
        elif result.season_number is not None:
            filtered = filter_discs_to_season(
                result.discs, result.season_number,
                film_title=result.dvdcompare_film_title or None,
            )
            if filtered:
                _record_hidden(filtered)
                result.discs = filtered

    log.info(
        "Resume: hydrated %r (%d) -> film=%r fid=%s release=%r discs=%d season=%s",
        result.canonical, result.year,
        result.dvdcompare_film_title, result.dvdcompare_film_id,
        result.release_name, len(result.discs), result.season_number,
    )

    # Fetch TMDb ShowDetail so the rip-guide classifier can enrich
    # dvdcompare entries with canonical S/E prefixes and downgrade
    # duplicate-episode entries to extras. Non-fatal on failure —
    # classification will still work, just without the enrichment.
    if tmdb_match.source_id and session.media_type == "tv":
        result.show_detail = await _fetch_show_detail(tmdb_match.source_id)
    elif tmdb_match.source_id and is_movie:
        # Movie runtime isn't carried on MetadataSearchResult, so the
        # prepended primary-work FilmSlot would render "(unknown
        # runtime)" on resume. Fetch the movie detail to recover it,
        # mirroring the fresh-lookup path where metadata.py stashes
        # movie_runtime in app.state. Non-fatal on failure.
        runtime = await _fetch_movie_runtime(tmdb_match.source_id)
        if runtime:
            result.movie_runtime = runtime

    return result


async def _fetch_show_detail(source_id: str) -> object | None:
    """Best-effort TMDb ShowDetail fetch. Returns ``None`` on failure."""
    try:
        from riplex.config import get_api_key
        from riplex.metadata.sources.tmdb import TmdbProvider

        provider = TmdbProvider(get_api_key())
        try:
            return await provider.get_show_detail(source_id, include_specials=True)
        finally:
            await provider.close()
    except Exception as exc:
        log.warning("Resume: TMDb show_detail fetch failed: %s", exc)
        return None


async def _fetch_movie_runtime(source_id: str) -> int | None:
    """Best-effort TMDb movie runtime fetch. Returns ``None`` on failure."""
    try:
        from riplex.config import get_api_key
        from riplex.metadata.sources.tmdb import TmdbProvider

        provider = TmdbProvider(get_api_key())
        try:
            detail = await provider.get_movie_detail(source_id)
        finally:
            await provider.close()
        return int(getattr(detail, "runtime_seconds", 0) or 0) or None
    except Exception as exc:
        log.warning("Resume: TMDb movie_detail fetch failed: %s", exc)
        return None
