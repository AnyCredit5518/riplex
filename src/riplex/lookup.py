"""TMDb + dvdcompare metadata lookup pipeline.

Provides a single entry point for the common pattern of:
1. Look up canonical metadata from TMDb (via plan())
2. Optionally fetch per-disc content breakdowns from dvdcompare
3. Return normalized fields used by all downstream commands
"""

from __future__ import annotations

from dataclasses import dataclass, field

from riplex.disc.provider import fetch_and_select_release
from riplex.metadata.planner import plan
from riplex.metadata.provider import MetadataProvider
from riplex.models import PlannedDisc, PlannedMovie, SearchRequest


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
    result = await plan(request, provider)

    is_movie = isinstance(result, PlannedMovie)
    canonical = result.canonical_title
    year = result.year
    movie_runtime = result.runtime_seconds if is_movie else None

    discs: list[PlannedDisc] = []
    release_name = ""
    dvdcompare_error: Exception | None = None

    if not skip_dvdcompare:
        try:
            discs, release_name = await fetch_and_select_release(
                canonical,
                disc_format=disc_format,
                disc_info=disc_info,
                preferred=preferred_release,
                year=year,
            )
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
    )
