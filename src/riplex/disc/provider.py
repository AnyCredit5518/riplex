"""Disc metadata provider using dvdcompare-scraper.

Handles all dvdcompare interaction: fetching, caching, release conversion,
scoring, selection, format detection, disc number detection, and content
summaries.
"""

from __future__ import annotations

import dataclasses
import logging
import re

from dvdcompare.cli import select_releases
from dvdcompare.models import FilmComparison
from dvdcompare.scraper import find_film

from riplex import cache
from riplex.models import PlannedDisc, PlannedEpisode, PlannedExtra

log = logging.getLogger(__name__)

_DVDCOMPARE_TTL_DAYS = 30
_CACHE_NS = "dvdcompare"


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
    ) -> None:
        self.cache_ns = cache_ns
        self.ttl_days = ttl_days

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

        film = await find_film(title, disc_format, year=year)
        log.debug("dvdcompare find_film('%s', format=%s, year=%s): %d release(s)",
                  title, disc_format, year, len(film.releases) if film.releases else 0)
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
        fetch, scoring, interactive prompt, and release conversion.
        """
        film = await find_film(title, disc_format, year=year)
        return select_dvdcompare_release(film, disc_info=disc_info, preferred=preferred)


def _clean_feature_type(raw: str) -> str:
    """Strip quality and playback annotations from a feature type string.

    ``"featurettes (with Play All)  (1080p)"`` becomes ``"featurettes"``.
    """
    idx = raw.find("(")
    if idx > 0:
        return raw[:idx].strip()
    return raw.strip()


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


def _convert_release(rel: object, disc_offset: int = 0) -> list[PlannedDisc]:
    """Convert a single dvdcompare Release into PlannedDisc objects.

    Used for movies and TV mini-series where one release maps to the full
    disc set.  Play-All groups become episodes; everything else is extras.
    """
    discs: list[PlannedDisc] = []
    for dvc_disc in rel.discs:
        episodes: list[PlannedEpisode] = []
        extras: list[PlannedExtra] = []

        for feature in dvc_disc.features:
            if feature.is_play_all and feature.children:
                log.debug("Disc %d: play-all '%s' with %d children -> episodes",
                          disc_offset + dvc_disc.number, feature.title, len(feature.children))
                # Group with children = episodes or multi-part content
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
            else:
                log.debug("Disc %d: extra '%s' (%ds) type='%s'",
                          disc_offset + dvc_disc.number, feature.title,
                          feature.runtime_seconds or 0,
                          _clean_feature_type(feature.feature_type or ""))
                extras.append(
                    PlannedExtra(
                        title=feature.title,
                        runtime_seconds=feature.runtime_seconds or 0,
                        feature_type=_clean_feature_type(feature.feature_type or ""),
                    )
                )

        discs.append(
            PlannedDisc(
                number=disc_offset + dvc_disc.number,
                disc_format=dvc_disc.format,
                is_film=dvc_disc.is_film,
                episodes=episodes,
                extras=extras,
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
                    log.debug("Disc %d: extra '%s' (%ds) type='%s'",
                              offset + dvc_disc.number, feature.title,
                              feature.runtime_seconds or 0,
                              _clean_feature_type(feature.feature_type or ""))
                    extras.append(
                        PlannedExtra(
                            title=feature.title,
                            runtime_seconds=feature.runtime_seconds or 0,
                            feature_type=_clean_feature_type(feature.feature_type or ""),
                        )
                    )

            discs.append(
                PlannedDisc(
                    number=offset + dvc_disc.number,
                    disc_format=dvc_disc.format,
                    is_film=dvc_disc.is_film,
                    episodes=episodes,
                    extras=extras,
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
            "Select a dvdcompare release:", options, default=0,
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

    Returns "Blu-ray 4K" if any title is 3840-wide, else "Blu-ray".
    """
    if not disc_info.titles:
        return None
    for t in disc_info.titles:
        if t.resolution and "3840" in t.resolution:
            return "Blu-ray 4K"
    return "Blu-ray"


# ---------------------------------------------------------------------------
# Disc number detection
# ---------------------------------------------------------------------------


def detect_disc_number(
    disc_info,
    dvdcompare_discs: list,
) -> int | None:
    """Auto-detect which dvdcompare disc number the physical disc corresponds to.

    Tries three strategies:
    1. Parse the volume label for a disc number (e.g. "FROZEN_PLANET_II_D2" -> 2)
    2. Match live title durations against each dvdcompare disc's episodes.
    3. For movies, match by disc format/resolution.

    Returns the disc number (1-based) or None if detection fails.
    """
    # Strategy 1: volume label
    label = disc_info.disc_name or ""
    match = re.search(r"[_\s-]D(?:isc\s*)?(\d+)\b", label, re.IGNORECASE)
    if match:
        return int(match.group(1))

    # Strategy 2: duration matching against dvdcompare discs
    if not dvdcompare_discs or not disc_info.titles:
        return None

    # Collect substantial title durations from the live disc
    live_durations = sorted(
        [t.duration_seconds for t in disc_info.titles if t.duration_seconds > 120],
        reverse=True,
    )
    if not live_durations:
        return None

    best_disc = None
    best_score = -1

    for disc in dvdcompare_discs:
        ep_durations = sorted(
            [ep.runtime_seconds for ep in disc.episodes if ep.runtime_seconds > 0],
            reverse=True,
        )
        if not ep_durations:
            continue

        # Count how many live titles match an episode within 60 seconds
        matched = 0
        used = set()
        for live_dur in live_durations:
            for i, ep_dur in enumerate(ep_durations):
                if i not in used and abs(live_dur - ep_dur) < 60:
                    matched += 1
                    used.add(i)
                    break

        # Score: fraction of episodes matched
        score = matched / len(ep_durations) if ep_durations else 0
        if score > best_score:
            best_score = score
            best_disc = disc.number

    # Require at least 50% of episodes to match
    if best_score >= 0.5:
        return best_disc

    # Strategy 3: for movies, match by disc format/resolution
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
