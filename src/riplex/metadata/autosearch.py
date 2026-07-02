"""Best-guess TMDb lookup for auto-filling per-group / per-film matches.

The Disc Overview screen fires one of these for every unassigned slot when
the user lands on the screen. A confident hit lands as an amber "auto-filled"
suggestion the user can promote to green with a single Confirm click; a weak
hit leaves the slot empty for manual assignment.
"""

from __future__ import annotations

import logging
from difflib import SequenceMatcher
from typing import Literal

from riplex.metadata.provider import MetadataSearchResult
from riplex.metadata.sources.tmdb import TmdbProvider

log = logging.getLogger(__name__)

# Fuzzy score below this triggers a "no confident hit" result. 0.85 is high
# enough to reject unrelated top hits (e.g. searching "Psych 2: Lassie Come
# Home" and getting a random "Psych" TV episode) but lax enough to accept
# minor punctuation / colon differences.
DEFAULT_FUZZY_THRESHOLD = 0.85


def _normalize(s: str) -> str:
    """Fold to a comparison-friendly form: lowercase, punctuation stripped,
    whitespace collapsed. Used only for the fuzzy score, never as a display
    string."""
    out = []
    prev_space = False
    for ch in s.lower():
        if ch.isalnum():
            out.append(ch)
            prev_space = False
        else:
            if not prev_space:
                out.append(" ")
            prev_space = True
    return "".join(out).strip()


def score_title(query: str, candidate: str) -> float:
    """Return a 0..1 similarity ratio between two titles."""
    a = _normalize(query)
    b = _normalize(candidate)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


async def best_guess(
    provider: TmdbProvider,
    query: str,
    *,
    media_type: Literal["movie", "tv", "auto"] = "auto",
    threshold: float = DEFAULT_FUZZY_THRESHOLD,
) -> tuple[MetadataSearchResult, float] | None:
    """Return the top TMDb hit for ``query`` if it scores at or above
    ``threshold``, else ``None``.

    Callers own the ``TmdbProvider`` lifecycle so multiple auto-searches
    can share one HTTP connection.
    """
    if not query.strip():
        return None
    try:
        results = await provider.search(query, media_type=media_type)
    except Exception as exc:  # network / API failure — treat as no guess
        log.warning("best_guess: TMDb search for %r failed: %s", query, exc)
        return None
    if not results:
        return None
    top = results[0]
    s = score_title(query, top.title)
    log.info("best_guess: query=%r top=%r (year=%s type=%s) score=%.2f threshold=%.2f",
             query, top.title, top.year, top.media_type, s, threshold)
    if s < threshold:
        return None
    return top, s
