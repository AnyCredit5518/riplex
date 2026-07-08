"""Disc metadata provider using dvdcompare-scraper.

Handles all dvdcompare interaction: fetching, caching, release conversion,
scoring, selection, format detection, disc number detection, and content
summaries.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import re
import time
from importlib.metadata import PackageNotFoundError, version as _pkg_version

import httpx

from dvdcompare.cli import select_releases
from dvdcompare.models import FilmComparison
from dvdcompare.scraper import find_film, get_film_by_url, search

from riplex import cache
from riplex.models import PlannedDisc, PlannedEpisode, PlannedExtra

log = logging.getLogger(__name__)

_DVDCOMPARE_TTL_DAYS = 30
_DVDCOMPARE_NEG_TTL_DAYS = 7
_DVDCOMPARE_HTTP_ERROR_TTL_SECONDS = 5 * 60  # 5 minutes
_CACHE_NS = "dvdcompare"

# Global throttle: at most one dvdcompare network round-trip every N seconds
# across the entire process, regardless of how many UI threads/tasks try to
# fetch concurrently. Tunable via env var for tests.
_MIN_INTERVAL_S = float(os.environ.get("RIPLEX_DVDCOMPARE_MIN_INTERVAL_S", "3.0"))
_request_lock = asyncio.Lock()
_last_request_at: float = 0.0


def _scraper_version() -> str:
    """Return the installed ``dvdcompare-scraper`` version, or ``unknown``."""
    try:
        return _pkg_version("dvdcompare-scraper")
    except PackageNotFoundError:
        return "unknown"


def _parse_retry_after(response: httpx.Response | None) -> int | None:
    """Parse a Retry-After header value into seconds, or None.

    Per RFC 7231 Retry-After may be either a delta-seconds integer or an
    HTTP-date. We only handle the integer form here.
    """
    if response is None:
        return None
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0, int(raw.strip()))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# DiscProvider class
# ---------------------------------------------------------------------------

class DiscProvider:
    """dvdcompare.net metadata provider with caching.

    Handles network fetches, caching, release conversion, scoring,
    interactive selection, format detection, and disc number detection.
    """

    def __init__(
        self,
        cache_ns: str = _CACHE_NS,
        ttl_days: int = _DVDCOMPARE_TTL_DAYS,
        neg_ttl_days: int = _DVDCOMPARE_NEG_TTL_DAYS,
    ) -> None:
        self.cache_ns = cache_ns
        self.ttl_days = ttl_days
        self.neg_ttl_days = neg_ttl_days
        cache.ensure_ns_version(self.cache_ns, _scraper_version())

    # -- lookup -----------------------------------------------------------

    async def lookup_discs(
        self,
        title: str,
        disc_format: str | None = None,
        release: str = "1",
        year: int | None = None,
    ) -> list[PlannedDisc]:
        """Look up disc structure from dvdcompare.net (cached)."""
        cache_key = cache.hash_key(f"{title}|{disc_format}|{release}")
        cached = cache.cache_get(self.cache_ns, cache_key, ttl_days=self.ttl_days)
        if cached is not None:
            log.debug("dvdcompare cache hit for '%s' (format=%s, release=%s)",
                      title, disc_format, release)
            return _dicts_to_discs(cached)

        film = await self.fetch_film(title, disc_format, year=year)
        discs = _convert_film(film, release)
        log.debug("Converted %d disc(s) from release '%s'", len(discs), release)

        cache.cache_set(self.cache_ns, cache_key, _discs_to_dicts(discs))
        return discs

    async def fetch_and_select_release(
        self,
        title: str,
        disc_format: str | None = None,
        disc_info=None,
        preferred: str | None = None,
        year: int | None = None,
    ) -> tuple[list, str]:
        """Fetch dvdcompare data and select the best release.

        Single entry point for all dvdcompare lookups. Handles network
        fetch, caching, scoring, interactive prompt, and release conversion.
        """
        film = await self.fetch_film(title, disc_format, year=year)
        return select_dvdcompare_release(film, disc_info=disc_info, preferred=preferred)

    async def fetch_film(
        self,
        title: str,
        disc_format: str | None = None,
        year: int | None = None,
    ) -> FilmComparison:
        """Fetch a FilmComparison, returning cached data when available.

        - Successful results are cached for ``ttl_days``.
        - "No results" (LookupError) is negative-cached for ``neg_ttl_days``.
        - HTTP/network failures are negative-cached for a short period (5
          min, or longer if the server returned Retry-After). This prevents
          a transient block from being re-hit on every UI navigation.
        - All real network requests are funnelled through a process-wide
          throttle so we never burst dvdcompare with parallel calls.
        """
        cache_key = cache.hash_key(f"film|{title}|{disc_format}|{year}")

        # Check the negative cache (short, custom expiry).
        neg = _read_negative_cache(self.cache_ns, cache_key)
        if neg is not None:
            kind, message = neg
            if kind == "noresults":
                log.debug("dvdcompare negative cache hit for '%s'", title)
                raise LookupError(f"No dvdcompare results for '{title}' (cached)")
            log.debug("dvdcompare http-error cache hit for '%s': %s", title, message)
            raise LookupError(
                f"dvdcompare temporarily unavailable for '{title}' "
                f"({message or 'recent request failed'})"
            )

        # Positive cache.
        cached = cache.cache_get(self.cache_ns, cache_key, ttl_days=self.ttl_days)
        if cached is not None and not cached.get("_negative"):
            log.debug("dvdcompare film cache hit for '%s'", title)
            return _dict_to_film(cached)

        # Real fetch (throttled).
        try:
            film = await _throttled_find_film(title, disc_format, year=year)
        except LookupError:
            log.debug("dvdcompare no results for '%s', caching negative result", title)
            _write_negative_cache(
                self.cache_ns,
                cache_key,
                kind="noresults",
                message="",
                ttl_seconds=self.neg_ttl_days * 86400,
            )
            raise
        except httpx.HTTPStatusError as exc:
            retry_after = _parse_retry_after(exc.response)
            ttl_seconds = max(
                _DVDCOMPARE_HTTP_ERROR_TTL_SECONDS, retry_after or 0
            )
            status = exc.response.status_code if exc.response is not None else "?"
            log.warning(
                "dvdcompare HTTP %s for '%s', caching short-TTL block (%ds, "
                "retry_after=%s)", status, title, ttl_seconds, retry_after,
            )
            _write_negative_cache(
                self.cache_ns,
                cache_key,
                kind="http_error",
                message=f"HTTP {status}",
                ttl_seconds=ttl_seconds,
            )
            raise LookupError(
                f"dvdcompare returned HTTP {status} for '{title}'"
            ) from exc
        except httpx.RequestError as exc:
            log.warning("dvdcompare network error for '%s': %s", title, exc)
            _write_negative_cache(
                self.cache_ns,
                cache_key,
                kind="http_error",
                message=type(exc).__name__,
                ttl_seconds=_DVDCOMPARE_HTTP_ERROR_TTL_SECONDS,
            )
            raise LookupError(
                f"dvdcompare network error for '{title}': {exc}"
            ) from exc

        log.debug("dvdcompare find_film('%s', format=%s, year=%s): %d release(s)",
                  title, disc_format, year, len(film.releases) if film.releases else 0)
        cache.cache_set(self.cache_ns, cache_key, dataclasses.asdict(film))
        return film

    # Backwards-compatible alias for the previous private name. Older callers
    # in screens / external code may still use this; prefer ``fetch_film``.
    _fetch_film_cached = fetch_film

    async def fetch_film_by_id(self, film_id: int) -> FilmComparison:
        """Fetch a specific dvdcompare film page by its film id.

        Used by the UI's manual-override path when our auto-ranking picks
        the wrong film page. Cached on success; HTTP/network failures
        propagate as LookupError after caching a short-TTL negative entry.
        """
        cache_key = cache.hash_key(f"film-by-id|{film_id}")

        cached = cache.cache_get(self.cache_ns, cache_key, ttl_days=self.ttl_days)
        if cached is not None and not cached.get("_negative"):
            log.debug("dvdcompare film-by-id cache hit for %s", film_id)
            return _dict_to_film(cached)

        url = film_url(film_id)
        try:
            film = await _throttled_get_film_by_url(url)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            log.warning("dvdcompare HTTP %s fetching fid=%s", status, film_id)
            raise LookupError(
                f"dvdcompare returned HTTP {status} for fid={film_id}"
            ) from exc
        except httpx.RequestError as exc:
            log.warning("dvdcompare network error fetching fid=%s: %s", film_id, exc)
            raise LookupError(
                f"dvdcompare network error for fid={film_id}: {exc}"
            ) from exc

        if not film.releases:
            raise LookupError(f"dvdcompare film {film_id} has no releases")

        cache.cache_set(self.cache_ns, cache_key, dataclasses.asdict(film))
        return film


# ---------------------------------------------------------------------------
# Public URL / fid helpers
# ---------------------------------------------------------------------------

from dvdcompare.scraper import BASE_URL as _DVDCOMPARE_BASE_URL  # noqa: E402


def film_url(film_id: int | str) -> str:
    """Return the public dvdcompare comparison URL for a film id."""
    return f"{_DVDCOMPARE_BASE_URL}/comparisons/film.php?fid={film_id}"


_FID_RE = re.compile(r"(?:fid=|film\.php\?fid=|^)(\d+)")


def parse_film_id(value: str) -> int | None:
    """Extract a numeric film id from a bare number or a dvdcompare URL.

    Returns ``None`` if no fid can be parsed.

    Accepted forms:
      - ``"55540"``
      - ``"fid=55540"``
      - ``"https://www.dvdcompare.net/comparisons/film.php?fid=55540"``
      - ``"https://www.dvdcompare.net/comparisons/film.php?fid=55540#2"``
    """
    if not value:
        return None
    s = value.strip()
    if not s:
        return None
    # Pure digits
    if s.isdigit():
        return int(s)
    m = _FID_RE.search(s)
    if m:
        return int(m.group(1))
    return None



# ---------------------------------------------------------------------------
# Internal helpers: negative cache + throttle
# ---------------------------------------------------------------------------


def _read_negative_cache(
    cache_ns: str, cache_key: str
) -> tuple[str, str] | None:
    """Return (kind, message) from negative cache, or None if absent/expired.

    The cache entry uses an absolute ``_expires_at`` epoch so we can pin the
    expiry to wall-clock time and respect Retry-After values directly.
    """
    entry = cache.cache_get(cache_ns, cache_key, ttl_days=365)
    if not isinstance(entry, dict) or not entry.get("_negative"):
        return None
    expires_at = entry.get("_expires_at")
    if isinstance(expires_at, (int, float)) and time.time() > expires_at:
        return None  # expired; treat as miss
    return entry.get("_kind", "noresults"), entry.get("_message", "")


def _write_negative_cache(
    cache_ns: str,
    cache_key: str,
    *,
    kind: str,
    message: str,
    ttl_seconds: float,
) -> None:
    """Store a negative-cache entry with an absolute expiry."""
    cache.cache_set(
        cache_ns,
        cache_key,
        {
            "_negative": True,
            "_kind": kind,
            "_message": message,
            "_expires_at": time.time() + ttl_seconds,
        },
    )


async def _throttled_find_film(
    title: str, disc_format: str | None, *, year: int | None = None
) -> FilmComparison:
    """Call ``find_film`` under a process-wide minimum-interval lock.

    Ensures even concurrent ``fetch_film`` calls (multiple UI threads, an
    orchestrate flow, parallel boxset discs) cannot burst dvdcompare with
    back-to-back requests.

    When ``disc_format`` is provided we trust it more than ``year``:
    dvdcompare occasionally lists the re-release year for 4K editions
    (e.g. Back to the Future Part II is shown as 1990 on its 4K page even
    though the film released in 1989), which makes the upstream
    ``find_film`` prefer-year heuristic pick the DVD page over the 4K
    page. We work around that by doing the search ourselves and ranking
    format-match above year-match when a disc format is known.
    """
    global _last_request_at
    async with _request_lock:
        now = time.monotonic()
        wait = _MIN_INTERVAL_S - (now - _last_request_at)
        if wait > 0:
            log.debug("dvdcompare throttle: waiting %.2fs before request", wait)
            await asyncio.sleep(wait)
        try:
            if disc_format:
                return await _find_film_prefer_format(title, disc_format, year)
            return await find_film(
                title, disc_format, year=year, resolve_pointers=True
            )
        finally:
            _last_request_at = time.monotonic()


async def _throttled_get_film_by_url(url: str) -> FilmComparison:
    """Call ``get_film_by_url`` under the same throttle as ``find_film``."""
    global _last_request_at
    async with _request_lock:
        now = time.monotonic()
        wait = _MIN_INTERVAL_S - (now - _last_request_at)
        if wait > 0:
            log.debug("dvdcompare throttle: waiting %.2fs before request", wait)
            await asyncio.sleep(wait)
        try:
            return await get_film_by_url(url, resolve_pointers=True)
        finally:
            _last_request_at = time.monotonic()


async def _find_film_prefer_format(
    title: str, disc_format: str, year: int | None
) -> FilmComparison:
    """Search dvdcompare and pick the film page that best matches the disc
    format we have in hand, preferring format match over year match.

    Ranking (highest first, considering only *title-matched* results):
      1. title + format + year
      2. title + format
      3. title + year
      4. title (any format, any year)

    A "title match" means the leading text of the search result matches
    the query (see ``_title_lead``). This avoids picking, e.g.,
    "American Psycho (Blu-ray)" for a "Psych" query just because it's
    alphabetically first among Blu-ray results.

    If no title-matched result exists we fall back to the previous
    format+year heuristic so we still return *something*; the user can
    still correct via the manual fid override.
    """
    results = await search(title)
    if not results:
        raise LookupError(f"No dvdcompare results for '{title}'")

    fmt_norm = disc_format.strip().lower()

    def fmt_matches(sr) -> bool:
        return _result_has_format(sr, fmt_norm)

    def year_matches(sr) -> bool:
        return year is not None and sr.year == year

    query_lead = _title_lead(title)
    title_matched = [
        sr for sr in results if _title_matches_query(sr.title, query_lead)
    ] if query_lead else []

    if title_matched:
        pool = title_matched
        log.debug("dvdcompare title-lead filter kept %d/%d result(s) for %r",
                  len(pool), len(results), title)
        # Tier 1: title + format + year
        for sr in pool:
            if fmt_matches(sr) and year_matches(sr):
                log.debug("dvdcompare pick (title+format+year): %s", sr.url)
                return await get_film_by_url(sr.url, resolve_pointers=True)
        # Tier 2: title + format
        for sr in pool:
            if fmt_matches(sr):
                log.debug("dvdcompare pick (title+format): %s", sr.url)
                return await get_film_by_url(sr.url, resolve_pointers=True)
        # Tier 3: title + year
        for sr in pool:
            if year_matches(sr):
                log.debug("dvdcompare pick (title+year): %s", sr.url)
                return await get_film_by_url(sr.url, resolve_pointers=True)
        # Tier 4: title only
        log.debug("dvdcompare pick (title-only fallback): %s", pool[0].url)
        return await get_film_by_url(pool[0].url, resolve_pointers=True)

    # No title-lead match — fall back to prior format-first heuristic.
    log.warning(
        "dvdcompare: no title-lead match for %r among %d result(s); "
        "falling back to format/year heuristic",
        title, len(results),
    )
    # Tier 1: format + year
    for sr in results:
        if fmt_matches(sr) and year_matches(sr):
            log.debug("dvdcompare pick (format+year): %s", sr.url)
            return await get_film_by_url(sr.url, resolve_pointers=True)
    # Tier 2: format only
    for sr in results:
        if fmt_matches(sr):
            log.debug("dvdcompare pick (format-only, year=%s actual=%s): %s",
                      year, sr.year, sr.url)
            return await get_film_by_url(sr.url, resolve_pointers=True)
    # Tier 3: year only (no format listed on result)
    for sr in results:
        if year_matches(sr) and not sr.disc_format:
            log.debug("dvdcompare pick (year-only, no result format): %s", sr.url)
            return await get_film_by_url(sr.url, resolve_pointers=True)
    # Tier 4: first result
    log.debug("dvdcompare pick (first result fallback): %s", results[0].url)
    return await get_film_by_url(results[0].url, resolve_pointers=True)


# Regex for stripping trailing dvdcompare annotations from a result title.
# Handles the ``\t\t\t\t(YYYY)`` and ``\t\t\t\t(YYYY-YYYY)`` year suffix, and
# parenthetical format/edition markers like ``(Blu-ray)``, ``(Blu-ray 4K)``,
# ``(4K)``, ``(3D)``, ``(TV)``, ``(HD DVD)``, ``(DVD)``.
_TRAILING_ANNOTATION_RE = re.compile(
    r"\s*\((?:\d{4}(?:[-/]\d{2,4})?|Blu-ray(?:\s+[34]K)?|Blu-ray\s+3D|"
    r"4K|3D|TV|HD\s*DVD|DVD|UHD)\)\s*$",
    re.IGNORECASE,
)


def strip_dvdcompare_annotations(title: str) -> str:
    """Strip trailing dvdcompare format/year annotations from a title.

    dvdcompare stores film titles with parenthetical format markers baked
    in — ``"Psych: The Movie (TV)"``, ``"Blade Runner (Blu-ray 4K)"``,
    ``"Something (2020)"``. Those markers aren't part of the canonical
    title and confuse an external metadata search (a TMDb query for
    ``"Psych: The Movie (TV)"`` returns zero hits, whereas
    ``"Psych: The Movie"`` matches). This strips every trailing marker
    while preserving the original casing.
    """
    if not title:
        return ""
    s = title
    while True:
        new_s = _TRAILING_ANNOTATION_RE.sub("", s).rstrip()
        if new_s == s:
            return s
        s = new_s


def _result_has_format(sr, fmt_norm: str) -> bool:
    """Return True if search result ``sr`` advertises the given disc format.

    dvdcompare's search parser sometimes leaves ``SearchResult.disc_format``
    unset even when the title contains a marker like ``"(Blu-ray)"`` — so
    we also scan the raw title text as a fallback. Only whole-word
    parenthetical matches count so we don't confuse ``Blu-ray`` with
    ``Blu-ray 4K`` or ``Blu-ray 3D``.
    """
    raw_fmt = (sr.disc_format or "").strip().lower()
    if raw_fmt == fmt_norm:
        return True
    if not fmt_norm:
        return False
    # Case-insensitive whole-annotation match in the title text.
    pattern = rf"\(\s*{re.escape(fmt_norm)}\s*\)"
    return re.search(pattern, sr.title or "", re.IGNORECASE) is not None


def _title_lead(raw: str) -> str:
    """Normalize a dvdcompare title (or query) for lead-token comparison.

    - Collapses whitespace and strips any ``AKA …`` alias tail.
    - Repeatedly strips trailing annotations like ``(Blu-ray)``, ``(TV)``,
      ``(YYYY)``.
    - Returns the lowercase, whitespace-normalized remainder.
    """
    if not raw:
        return ""
    s = re.sub(r"\s+", " ", raw.replace("\t", " ")).strip()
    # Strip AKA aliases (dvdcompare pattern: "Foo AKA Bar AKA Baz")
    aka_idx = re.search(r"\bAKA\b", s, re.IGNORECASE)
    if aka_idx:
        s = s[: aka_idx.start()].rstrip()
    # Strip trailing annotations until none remain.
    while True:
        new_s = _TRAILING_ANNOTATION_RE.sub("", s).rstrip()
        if new_s == s:
            break
        s = new_s
    return s.lower()


def _title_matches_query(result_title: str, query_lead: str) -> bool:
    """Return True if ``result_title`` matches the query's lead token.

    A match holds when either:
      * the fully-normalized result equals the query, or
      * the text before the first ``:`` in the normalized result equals
        the query (handles ``"Psych: Season 1"`` for query ``"Psych"``).
    """
    if not query_lead:
        return False
    result_lead = _title_lead(result_title)
    if result_lead == query_lead:
        return True
    colon = result_lead.find(":")
    if colon > 0 and result_lead[:colon].strip() == query_lead:
        return True
    return False


def _clean_feature_type(raw: str) -> str:
    """Strip quality and playback annotations from a feature type string.

    ``"featurettes (with Play All)  (1080p)"`` becomes ``"featurettes"``.
    """
    idx = raw.find("(")
    if idx > 0:
        return raw[:idx].strip()
    return raw.strip()


_FEATURETTE_TYPES = frozenset({
    "featurette", "featurettes",
    "behind the scenes", "behind-the-scenes",
    "documentary", "interview", "interviews",
    "deleted scene", "deleted scenes",
    "trailer", "trailers",
})


def _is_featurette_type(feature_type: str | None) -> bool:
    """Return True if the feature_type indicates a featurette/bonus category."""
    if not feature_type:
        return False
    cleaned = _clean_feature_type(feature_type).lower()
    return cleaned in _FEATURETTE_TYPES


async def lookup_discs(
    title: str,
    disc_format: str | None = None,
    release: str = "1",
    year: int | None = None,
) -> list[PlannedDisc]:
    """Look up disc structure from dvdcompare.net.

    .. deprecated:: Use :pyclass:`DiscProvider` instead.
    """
    return await DiscProvider().lookup_discs(title, disc_format, release, year=year)


def _discs_to_dicts(discs: list[PlannedDisc]) -> list[dict]:
    """Serialize a list of PlannedDisc to plain dicts for caching."""
    return [dataclasses.asdict(d) for d in discs]


def _dicts_to_discs(data: list[dict]) -> list[PlannedDisc]:
    """Deserialize cached dicts back into PlannedDisc objects."""
    out: list[PlannedDisc] = []
    for d in data:
        d["episodes"] = [PlannedEpisode(**e) for e in d.get("episodes", [])]
        d["extras"] = [PlannedExtra(**e) for e in d.get("extras", [])]
        out.append(PlannedDisc(**d))
    return out


def _dict_to_film(data: dict) -> FilmComparison:
    """Deserialize a cached dict back into a FilmComparison."""
    from dvdcompare.models import Disc, Feature, Release

    def _to_feature(d: dict) -> Feature:
        d["children"] = [_to_feature(c) for c in d.get("children", [])]
        return Feature(**d)

    releases = []
    for r in data.get("releases", []):
        discs = []
        for disc in r.get("discs", []):
            disc["features"] = [_to_feature(f) for f in disc.get("features", [])]
            discs.append(Disc(**disc))
        r["discs"] = discs
        releases.append(Release(**r))
    data["releases"] = releases
    return FilmComparison(**data)


def _convert_release(rel: object, disc_offset: int = 0) -> list[PlannedDisc]:
    """Convert a single dvdcompare Release into PlannedDisc objects.

    Used for movies and TV mini-series where one release maps to the full
    disc set.

    Classification rules:
    - Play-all groups whose feature_type is a featurette category
      (e.g. "featurettes") → children become **extras**
    - Other play-all groups with children → children become **episodes**
    - Standalone features with no feature_type and runtime >= 600s on
      non-film discs → **episodes** (these are actual TV episodes listed
      outside of any group)
    - Everything else → **extras**
    """
    discs: list[PlannedDisc] = []
    for dvc_disc in rel.discs:
        episodes: list[PlannedEpisode] = []
        extras: list[PlannedExtra] = []

        for feature in dvc_disc.features:
            if feature.is_play_all and feature.children:
                # Always add the play-all parent as an extra so disc titles
                # matching the compilation runtime get identified and skipped
                if feature.runtime_seconds:
                    extras.append(
                        PlannedExtra(
                            title=f"{feature.title}: Play All",
                            runtime_seconds=feature.runtime_seconds or 0,
                            feature_type=_clean_feature_type(feature.feature_type or ""),
                        )
                    )

                # Check if this play-all is a featurette compilation
                if _is_featurette_type(feature.feature_type):
                    log.debug("Disc %d: featurette play-all '%s' with %d children -> extras",
                              disc_offset + dvc_disc.number, feature.title, len(feature.children))
                    for child in feature.children:
                        extras.append(
                            PlannedExtra(
                                title=child.title,
                                runtime_seconds=child.runtime_seconds or 0,
                                feature_type=_clean_feature_type(feature.title),
                            )
                        )
                else:
                    log.debug("Disc %d: play-all '%s' with %d children -> episodes",
                              disc_offset + dvc_disc.number, feature.title, len(feature.children))
                    for i, child in enumerate(feature.children, 1):
                        episodes.append(
                            PlannedEpisode(
                                season_number=0,
                                episode_number=i,
                                title=child.title,
                                runtime="",
                                runtime_seconds=child.runtime_seconds or 0,
                            )
                        )
            elif feature.children:
                log.debug("Disc %d: extras group '%s' with %d children",
                          disc_offset + dvc_disc.number, feature.title,
                          len(feature.children))
                # Non-play-all group: flatten children as extras
                for child in feature.children:
                    extras.append(
                        PlannedExtra(
                            title=child.title,
                            runtime_seconds=child.runtime_seconds or 0,
                            feature_type=_clean_feature_type(feature.title),
                        )
                    )
            elif (
                not dvc_disc.is_film
                and not feature.feature_type
                and (feature.runtime_seconds or 0) >= 600
                and not getattr(feature, "pointer_fid", None)
            ):
                log.debug("Disc %d: standalone episode '%s' (%ds)",
                          disc_offset + dvc_disc.number, feature.title,
                          feature.runtime_seconds or 0)
                episodes.append(
                    PlannedEpisode(
                        season_number=0,
                        episode_number=len(episodes) + 1,
                        title=feature.title,
                        runtime="",
                        runtime_seconds=feature.runtime_seconds or 0,
                    )
                )
            else:
                log.debug("Disc %d: extra '%s' (%ds) type='%s' pointer_fid=%s",
                          disc_offset + dvc_disc.number, feature.title,
                          feature.runtime_seconds or 0,
                          _clean_feature_type(feature.feature_type or ""),
                          getattr(feature, "pointer_fid", None))
                extras.append(
                    PlannedExtra(
                        title=feature.title,
                        runtime_seconds=feature.runtime_seconds or 0,
                        feature_type=_clean_feature_type(feature.feature_type or ""),
                        pointer_fid=getattr(feature, "pointer_fid", None),
                    )
                )

        discs.append(
            PlannedDisc(
                number=disc_offset + dvc_disc.number,
                disc_format=dvc_disc.format,
                is_film=dvc_disc.is_film,
                episodes=episodes,
                extras=extras,
                title=getattr(dvc_disc, "title", "") or "",
            )
        )
    return discs


def _convert_box_set(releases: list, disc_offset: int = 0) -> list[PlannedDisc]:
    """Convert multiple dvdcompare Releases (volumes) into one disc list.

    Used for multi-volume box sets (e.g. X-Men Animated Series Vol 1-4)
    where each volume is a separate release containing season discs.
    Groups titled "Episodes" become episodes; other groups and standalone
    features become extras.
    """
    discs: list[PlannedDisc] = []
    offset = disc_offset
    for rel in releases:
        for dvc_disc in rel.discs:
            episodes: list[PlannedEpisode] = []
            extras: list[PlannedExtra] = []

            for feature in dvc_disc.features:
                title_lower = feature.title.lower().strip().rstrip(":")
                if feature.children and title_lower == "episodes":
                    log.debug("Disc %d: episode group '%s' with %d children",
                              offset + dvc_disc.number, feature.title,
                              len(feature.children))
                    for i, child in enumerate(feature.children, 1):
                        episodes.append(
                            PlannedEpisode(
                                season_number=0,
                                episode_number=i,
                                title=child.title,
                                runtime="",
                                runtime_seconds=child.runtime_seconds or 0,
                            )
                        )
                elif feature.children:
                    log.debug("Disc %d: extras group '%s' with %d children",
                              offset + dvc_disc.number, feature.title,
                              len(feature.children))
                    for child in feature.children:
                        extras.append(
                            PlannedExtra(
                                title=child.title,
                                runtime_seconds=child.runtime_seconds or 0,
                                feature_type=_clean_feature_type(feature.title),
                            )
                        )
                else:
                    log.debug("Disc %d: extra '%s' (%ds) type='%s' pointer_fid=%s",
                              offset + dvc_disc.number, feature.title,
                              feature.runtime_seconds or 0,
                              _clean_feature_type(feature.feature_type or ""),
                              getattr(feature, "pointer_fid", None))
                    extras.append(
                        PlannedExtra(
                            title=feature.title,
                            runtime_seconds=feature.runtime_seconds or 0,
                            feature_type=_clean_feature_type(feature.feature_type or ""),
                            pointer_fid=getattr(feature, "pointer_fid", None),
                        )
                    )

            discs.append(
                PlannedDisc(
                    number=offset + dvc_disc.number,
                    disc_format=dvc_disc.format,
                    is_film=dvc_disc.is_film,
                    episodes=episodes,
                    extras=extras,
                    title=getattr(dvc_disc, "title", "") or "",
                )
            )
        offset += len(rel.discs)
    return discs


def _convert_film(
    film: FilmComparison,
    release: str = "1",
) -> list[PlannedDisc]:
    """Convert a dvdcompare FilmComparison into PlannedDisc objects."""
    if not film.releases:
        return []

    selected = select_releases(film.releases, release)

    if len(selected) > 1:
        log.debug("Multi-volume box set: combining %d releases", len(selected))
        return _convert_box_set(selected)

    return _convert_release(selected[0])


# ---------------------------------------------------------------------------
# Release scoring and selection
# ---------------------------------------------------------------------------


def score_releases(releases, disc_info) -> int:
    """Score releases by matching live disc durations to feature runtimes.

    Uses F1 score (harmonic mean of precision and recall) to favor releases
    that explain more of the disc's content over releases that simply list
    fewer features.

    Returns the 0-based index of the best release, or 0 if no good match.
    """
    if not disc_info or not disc_info.titles:
        return 0

    live_durations = sorted(
        [t.duration_seconds for t in disc_info.titles if t.duration_seconds > 120],
        reverse=True,
    )
    if not live_durations:
        return 0

    best_idx = 0
    best_score = -1

    for rel_idx, rel in enumerate(releases):
        ep_durations = sorted(
            [f.runtime_seconds for d in rel.discs for f in d.features
             if f.runtime_seconds and f.runtime_seconds > 120],
            reverse=True,
        )
        if not ep_durations:
            continue

        matched = 0
        used = set()
        for live_dur in live_durations:
            for i, ep_dur in enumerate(ep_durations):
                if i not in used and abs(live_dur - ep_dur) < 60:
                    matched += 1
                    used.add(i)
                    break

        # F1 score: harmonic mean of precision and recall.
        # Precision = fraction of the release's features found on disc.
        # Recall = fraction of the disc's titles explained by the release.
        precision = matched / len(ep_durations)
        recall = matched / len(live_durations)
        if precision + recall > 0:
            score = 2 * precision * recall / (precision + recall)
        else:
            score = 0.0
        if score > best_score:
            best_score = score
            best_idx = rel_idx

    if best_score >= 0.1:
        return best_idx
    return 0


def select_dvdcompare_release(
    film,
    disc_info=None,
    preferred: str | None = None,
) -> tuple[list, str]:
    """Select the best dvdcompare release for a disc.

    Selection strategy:
    1. If *preferred* keyword given, keyword-match against release names.
    2. If no *preferred*, try duration matching against *disc_info*.
    3. Fall back to first release.
    4. Reorder releases so the recommended one is first.
    5. If interactive and >1 release, let the user pick from the list.

    Returns (PlannedDisc list, release_name) or ([], "").
    """
    import sys

    from riplex.ui import is_interactive, prompt_choice

    if not film.releases:
        return [], ""

    # Show which dvdcompare film page we're picking releases from so the
    # user can spot a wrong match (e.g. season 1 page when disc is season 2)
    # before committing to a region release.
    film_label = film.title
    if getattr(film, "year", None):
        film_label = f"{film_label} ({film.year})"
    film_id = getattr(film, "film_id", None)
    if film_id:
        film_label = f"{film_label} [film #{film_id}]"
    print(f"Matched dvdcompare film: {film_label}", file=sys.stderr)

    # --- determine recommended release index ---
    rec_idx = 0  # 0-based index into film.releases

    if preferred:
        # Keyword match against release names
        try:
            selected = select_releases(film.releases, preferred)
            rec_idx = next(
                i for i, r in enumerate(film.releases) if r is selected[0]
            )
        except (LookupError, StopIteration):
            print(f"Error: no release matching '{preferred}'.", file=sys.stderr)
            print("Available releases:", file=sys.stderr)
            for i, r in enumerate(film.releases, 1):
                print(f"  {i}. {r.name}", file=sys.stderr)
            sys.exit(1)
    elif disc_info and disc_info.titles:
        # Duration matching via shared scoring function
        rec_idx = score_releases(film.releases, disc_info)

    # --- reorder releases so recommended is first ---
    releases = [film.releases[rec_idx]] + [
        r for i, r in enumerate(film.releases) if i != rec_idx
    ]

    # --- interactive selection (skip if preferred already resolved) ---
    if is_interactive() and len(releases) > 1 and not preferred:
        options = []
        for rel in releases:
            disc_count = len(rel.discs) if rel.discs else 0
            disc_word = "disc" if disc_count == 1 else "discs"
            options.append(f"{rel.name} [{disc_count} {disc_word}]")
        chosen_idx = prompt_choice(
            f"Select a dvdcompare release for {film.title}:",
            options,
            default=0,
        )
    else:
        chosen_idx = 0

    # --- convert chosen release ---
    chosen_release = releases[chosen_idx]
    # Find the 1-based index in the original film.releases for _convert_film
    orig_idx = next(i for i, r in enumerate(film.releases) if r is chosen_release)
    discs = _convert_film(film, str(orig_idx + 1))
    return discs, chosen_release.name


async def fetch_and_select_release(
    title: str,
    disc_format: str | None = None,
    disc_info=None,
    preferred: str | None = None,
    year: int | None = None,
) -> tuple[list, str]:
    """Fetch dvdcompare data and select the best release.

    .. deprecated:: Use :pyclass:`DiscProvider` instead.
    """
    return await DiscProvider().fetch_and_select_release(
        title, disc_format, disc_info, preferred, year=year,
    )


# ---------------------------------------------------------------------------
# Disc format detection
# ---------------------------------------------------------------------------


def detect_disc_format(disc_info) -> str | None:
    """Auto-detect dvdcompare format string from disc title resolutions.

    Uses the same width/height thresholds as ``riplex.detect.detect_format``
    so that live disc reads and post-rip scans classify identically:

    * >= 3840 wide (or >= 2160 tall) -> ``"Blu-ray 4K"``
    * >= 1280 wide (or >=  720 tall) -> ``"Blu-ray"``
    * anything smaller with a known resolution -> ``"DVD"``

    Returns ``None`` when no title advertises a resolution at all.
    """
    if not disc_info.titles:
        return None
    max_w = 0
    max_h = 0
    for t in disc_info.titles:
        if not t.resolution or "x" not in t.resolution:
            continue
        w_str, _, h_str = t.resolution.partition("x")
        try:
            w = int(w_str)
            h = int(h_str)
        except ValueError:
            continue
        if w > max_w:
            max_w = w
        if h > max_h:
            max_h = h
    if max_w == 0 and max_h == 0:
        return None
    if max_w >= 3840 or max_h >= 2160:
        return "Blu-ray 4K"
    if max_w >= 1280 or max_h >= 720:
        return "Blu-ray"
    return "DVD"


# ---------------------------------------------------------------------------
# Disc number detection
# ---------------------------------------------------------------------------


def detect_disc_number(
    disc_info,
    dvdcompare_discs: list,
) -> int | None:
    """Auto-detect which dvdcompare disc number the physical disc corresponds to.

    Tries three strategies in order:
    1. Parse the volume label for a disc number (e.g. "FROZEN_PLANET_II_D2" -> 2)
    2. For multi-format releases, match by disc format/resolution (4K vs Blu-ray).
    3. Match live title durations against each dvdcompare disc's episodes and extras.

    Strategy 2 runs before duration matching because a movie released across
    several format discs (4K + Blu-ray + 3D) carries the *same* main feature on
    every disc, so its runtime cannot distinguish them — and duration matching
    can actively pick the wrong disc when one disc lacks listed runtimes. The
    resolution is the only reliable distinguishing signal in that case.

    Returns the disc number (1-based) or None if detection fails.
    """
    log.info("detect_disc_number: label=%r n_dvdcompare_discs=%d n_live_titles=%d",
             disc_info.disc_name, len(dvdcompare_discs) if dvdcompare_discs else 0,
             len(disc_info.titles) if disc_info.titles else 0)

    # Strategy 1: volume label
    label = disc_info.disc_name or ""
    match = re.search(r"[_\s-]D(?:isc\s*)?(\d+)\b", label, re.IGNORECASE)
    if match:
        n = int(match.group(1))
        log.info("detect_disc_number: strategy1 (volume label) matched disc %d", n)
        return n

    # Strategy 2: format/resolution match (authoritative for multi-format
    # movie releases, where every disc shares the same main feature runtime).
    format_disc = _match_disc_by_format(disc_info, dvdcompare_discs)
    if format_disc is not None:
        log.info("detect_disc_number: strategy2 (format) matched disc %d", format_disc)
        return format_disc

    # Strategy 3: duration matching against dvdcompare discs
    if not dvdcompare_discs or not disc_info.titles:
        log.info("detect_disc_number: strategy3 skipped (no dvdcompare_discs or no titles)")
        return None

    # Collect substantial title durations from the live disc
    live_durations = sorted(
        [t.duration_seconds for t in disc_info.titles if t.duration_seconds > 120],
        reverse=True,
    )
    log.info("detect_disc_number: strategy3 live_durations=%s", live_durations)
    if not live_durations:
        return None

    best_disc = None
    best_score = -1
    runner_up_score = -1

    for disc in dvdcompare_discs:
        # Gather all content durations: episodes first, then extras
        ep_durations = sorted(
            [ep.runtime_seconds for ep in disc.episodes if ep.runtime_seconds > 0],
            reverse=True,
        )
        extra_durations = sorted(
            [ex.runtime_seconds for ex in disc.extras if ex.runtime_seconds > 120],
            reverse=True,
        )

        # Try episodes first (stronger signal), fall back to extras
        candidates = ep_durations if ep_durations else extra_durations
        if not candidates:
            continue

        # Count how many live titles match a candidate within 60 seconds
        matched = 0
        used = set()
        for live_dur in live_durations:
            for i, cand_dur in enumerate(candidates):
                if i not in used and abs(live_dur - cand_dur) < 60:
                    matched += 1
                    used.add(i)
                    break

        # Score: fraction of the smaller set matched. Using min(len) so a
        # physical disc that only exposes one title (e.g. a bonus disc where
        # MakeMKV surfaces just the main film) can still match a dvdcompare
        # disc that lists several bonus films — as long as the exposed title
        # lines up with one of them.
        denom = min(len(candidates), len(live_durations)) or 1
        score = matched / denom
        log.info("detect_disc_number: disc %d candidates=%s matched=%d/%d score=%.2f",
                 disc.number, candidates[:6], matched, denom, score)
        if score > best_score:
            runner_up_score = best_score
            best_score = score
            best_disc = disc.number
        elif score > runner_up_score:
            runner_up_score = score

    # Require at least 50% of entries to match AND a meaningful margin over
    # the runner-up. TV box sets are the motivating case: every disc holds
    # ~4-6 episodes of the same runtime, so a disc that lists 4 episodes
    # trivially scores 1.0 against 4 matched live titles while a disc that
    # lists 5 episodes scores 0.8 — even when the *5-episode* disc is the
    # one physically inserted. Without the margin check we'd silently pick
    # the smaller disc and re-prompt for the wrong one on resume. Requiring
    # a 0.25 margin makes the caller fall back to prompting the user in the
    # ambiguous case, which is the honest answer.
    runner_up = max(runner_up_score, 0.0)
    if best_score >= 0.5 and (best_score - runner_up) >= 0.25:
        log.info(
            "detect_disc_number: WINNER disc %d (score=%.2f, runner_up=%.2f)",
            best_disc, best_score, runner_up,
        )
        return best_disc

    log.info(
        "detect_disc_number: no confident winner "
        "(best=%.2f runner_up=%.2f; need best>=0.50 and margin>=0.25)",
        best_score, runner_up,
    )
    return None


def _match_disc_by_format(disc_info, dvdcompare_discs: list) -> int | None:
    """Match the live disc to a dvdcompare disc by format/resolution.

    Only returns a result when exactly one disc matches the live disc's
    resolution, i.e. when the format is genuinely distinguishing (e.g. a single
    4K disc among standard Blu-rays). Same-format multi-disc sets (TV box sets)
    yield multiple candidates and fall through to duration matching.
    """
    if not dvdcompare_discs:
        return None

    live_resolutions = {t.resolution for t in disc_info.titles if t.resolution}
    has_4k = any("2160" in r for r in live_resolutions)
    has_1080 = any("1080" in r for r in live_resolutions)

    format_candidates = []
    for disc in dvdcompare_discs:
        fmt = (getattr(disc, "disc_format", "") or "").lower()
        if has_4k and ("4k" in fmt or "uhd" in fmt):
            format_candidates.append(disc.number)
        elif has_1080 and not has_4k and "4k" not in fmt and "uhd" not in fmt and "blu" in fmt:
            format_candidates.append(disc.number)

    if len(format_candidates) == 1:
        return format_candidates[0]

    return None



# ---------------------------------------------------------------------------
# Disc content summary
# ---------------------------------------------------------------------------


def disc_content_summary(disc) -> str:
    """Return a short comma-separated summary of a dvdcompare disc's content."""
    titles = []
    for ep in disc.episodes:
        titles.append(ep.title)
    for ex in disc.extras:
        titles.append(ex.title)
    if not titles:
        return "(no content listed)"
    # Truncate if too many items
    if len(titles) > 4:
        return ", ".join(titles[:4]) + f", ... ({len(titles)} items)"
    return ", ".join(titles)
