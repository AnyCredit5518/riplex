"""Disc metadata provider using dvdcompare-scraper."""

from __future__ import annotations

import dataclasses
import logging

from dvdcompare.cli import select_releases
from dvdcompare.models import FilmComparison
from dvdcompare.scraper import find_film

from plex_planner import cache
from plex_planner.models import PlannedDisc, PlannedEpisode, PlannedExtra

log = logging.getLogger(__name__)

_DVDCOMPARE_TTL_DAYS = 30
_CACHE_NS = "dvdcompare"


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
) -> list[PlannedDisc]:
    """Look up disc structure from dvdcompare.net.

    *title* is the film/show title to search for.
    *disc_format* optionally filters results by format (e.g. "Blu-ray 4K").
    *release* selects the regional release (1-based index or name keyword).

    Results are cached locally for 30 days.
    """
    cache_key = cache.hash_key(f"{title}|{disc_format}|{release}")
    cached = cache.cache_get(_CACHE_NS, cache_key, ttl_days=_DVDCOMPARE_TTL_DAYS)
    if cached is not None:
        log.debug("dvdcompare cache hit for '%s' (format=%s, release=%s)",
                  title, disc_format, release)
        return _dicts_to_discs(cached)

    film = await find_film(title, disc_format)
    log.debug("dvdcompare find_film('%s', format=%s): %d release(s)",
              title, disc_format, len(film.releases) if film.releases else 0)
    discs = _convert_film(film, release)
    log.debug("Converted %d disc(s) from release '%s'", len(discs), release)

    cache.cache_set(_CACHE_NS, cache_key, _discs_to_dicts(discs))
    return discs


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


def _convert_film(
    film: FilmComparison,
    release: str = "1",
) -> list[PlannedDisc]:
    """Convert a dvdcompare FilmComparison into PlannedDisc objects."""
    if not film.releases:
        return []

    selected = select_releases(film.releases, release)
    rel = selected[0]

    discs: list[PlannedDisc] = []
    for dvc_disc in rel.discs:
        episodes: list[PlannedEpisode] = []
        extras: list[PlannedExtra] = []

        for feature in dvc_disc.features:
            if feature.is_play_all and feature.children:
                log.debug("Disc %d: play-all '%s' with %d children -> episodes",
                          dvc_disc.number, feature.title, len(feature.children))
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
            else:
                log.debug("Disc %d: extra '%s' (%ds) type='%s'",
                          dvc_disc.number, feature.title,
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
                number=dvc_disc.number,
                disc_format=dvc_disc.format,
                is_film=dvc_disc.is_film,
                episodes=episodes,
                extras=extras,
            )
        )

    return discs
