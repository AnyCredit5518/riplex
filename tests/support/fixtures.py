"""Load normalized GUI test scenarios and rebuild the real riplex dataclasses.

A *scenario* is a committed JSON file under ``tests/fixtures/gui/scenarios/``
describing one disc-set: the disc(s) makemkv would report, the TMDb match,
and the dvdcompare release breakdown. Scenarios come from two places and
share one schema:

* hand-authored (edge/error cases), and
* generated from real archived rips by ``scripts/gen_gui_fixtures.py``.

The loader never touches the archive — it only reads the committed JSON — so
tests run anywhere. Reconstruction returns the genuine dataclasses used in
production so the provider mocks hand screens exactly what the real providers
would.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from riplex.disc.makemkv import DiscInfo, DiscTitle, DriveInfo, MakeMKVPreflight
from riplex.metadata.provider import (
    EpisodeMetadata,
    MetadataSearchResult,
    MovieDetail,
    SeasonMetadata,
    ShowDetail,
)
from riplex.models import PlannedDisc, PlannedEpisode, PlannedExtra

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "gui" / "scenarios"

SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Media-type categories
# ---------------------------------------------------------------------------
# Every scenario is classified into exactly one of these so tests can target a
# media type and automatically pick up new fixtures of that type as they're
# generated. A scenario may pin its own value via a top-level ``"category"``
# key; otherwise it's inferred from the archive folder name, release name, and
# TMDb season structure.
#
# "Seasonal series" (a single season of an ongoing show, e.g. Psych Season 1)
# is NOT a separate category — it's ``tv_series`` because it is series content.
# Use ``season_scenarios()`` to target just the single-season rips.

CATEGORY_MOVIE = "movie"                 # any theatrical / feature film release
CATEGORY_TV_MINISERIES = "tv_miniseries" # limited, self-contained series (e.g. Chernobyl)
CATEGORY_TV_SERIES = "tv_series"         # an ongoing multi-season show: a single
                                         # season rip OR a complete-series set

TV_CATEGORIES = (CATEGORY_TV_MINISERIES, CATEGORY_TV_SERIES)
ALL_CATEGORIES = (CATEGORY_MOVIE, *TV_CATEGORIES)

_SEASON_FOLDER_RE = re.compile(r"season\s+\d+", re.IGNORECASE)
_COMPLETE_SERIES_RE = re.compile(
    r"complete\s+(series|collection|seasons)|seasons?\s+\d+\s*[-–]\s*\d+", re.IGNORECASE
)


def _is_seasonal_source(raw: dict[str, Any]) -> bool:
    """True when the archive folder is a single ``Season NN`` rip."""
    source_folder = str(raw.get("source", "")).split(":", 1)[-1]
    return bool(_SEASON_FOLDER_RE.search(source_folder))


def classify(raw: dict[str, Any]) -> str:
    """Classify a scenario dict into one of the media-type categories.

    An explicit top-level ``"category"`` wins; otherwise infer from the data.
    Pure function so the generator and the loader agree on classification.
    """
    explicit = raw.get("category")
    if explicit in ALL_CATEGORIES:
        return explicit

    media = raw.get("media_type") or raw.get("tmdb", {}).get("media_type", "movie")
    if media != "tv":
        return CATEGORY_MOVIE

    # A per-season archive folder ("Season 01") is one season of an ongoing
    # multi-season show — series content, not a self-contained mini-series.
    if _is_seasonal_source(raw):
        return CATEGORY_TV_SERIES

    release = raw.get("dvdcompare", {}).get("release", "") or ""
    title = raw.get("title", "") or ""
    if _COMPLETE_SERIES_RE.search(release) or _COMPLETE_SERIES_RE.search(title):
        return CATEGORY_TV_SERIES

    # Multiple distinct TMDb seasons -> a full series; a single season with no
    # complete-series/seasonal marker -> a limited/mini-series.
    seasons = raw.get("tmdb", {}).get("seasons", []) or []
    distinct_seasons = {s.get("season_number") for s in seasons}
    if len(distinct_seasons) > 1:
        return CATEGORY_TV_SERIES
    return CATEGORY_TV_MINISERIES



def _runtime_str(seconds: int) -> str:
    """Human-readable runtime like the dvdcompare planner emits ('1h 2m')."""
    if not seconds:
        return ""
    minutes = seconds // 60
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    return f"{minutes}m"


@dataclass
class Scenario:
    """A loaded, immutable-ish view over one scenario JSON file.

    Methods rebuild the production dataclasses on demand; nothing is cached
    so tests can freely mutate returned objects.
    """

    raw: dict[str, Any]
    path: Path

    # -- top-level accessors --------------------------------------------
    @property
    def name(self) -> str:
        return self.raw.get("scenario", self.path.stem)

    @property
    def workflow(self) -> str:
        return self.raw.get("workflow", "orchestrate")

    @property
    def media_type(self) -> str:
        return self.raw.get("media_type", self.raw.get("tmdb", {}).get("media_type", "movie"))

    @property
    def title(self) -> str:
        return self.raw.get("title", self.raw.get("tmdb", {}).get("title", ""))

    @property
    def year(self) -> int | None:
        return self.raw.get("year", self.raw.get("tmdb", {}).get("year"))

    @property
    def is_tv(self) -> bool:
        return self.media_type == "tv"

    @property
    def category(self) -> str:
        """The media-type category (see ``classify``)."""
        return classify(self.raw)

    @property
    def selected_titles(self) -> list[int]:
        return list(self.raw.get("selected_titles", []))

    @property
    def ripped_titles(self) -> list[int]:
        return list(self.raw.get("ripped_titles", []))

    @property
    def disc_numbers(self) -> list[int]:
        return [d["disc_number"] for d in self.raw.get("discs", [])]

    # -- disc / makemkv -------------------------------------------------
    def _disc_raw(self, disc_number: int | None = None) -> dict[str, Any]:
        discs = self.raw.get("discs", [])
        if not discs:
            raise ValueError(f"scenario {self.name!r} has no discs")
        if disc_number is None:
            return discs[0]
        for d in discs:
            if d.get("disc_number") == disc_number:
                return d
        raise ValueError(f"scenario {self.name!r} has no disc {disc_number}")

    def disc_info(self, disc_number: int | None = None) -> DiscInfo:
        """Rebuild the ``DiscInfo`` makemkv would return for a disc."""
        d = self._disc_raw(disc_number)
        titles = [self._disc_title(t) for t in d.get("titles", [])]
        return DiscInfo(
            disc_name=d.get("disc_name", ""),
            disc_type=d.get("disc_type", "Blu-ray disc"),
            titles=titles,
        )

    @staticmethod
    def _disc_title(t: dict[str, Any]) -> DiscTitle:
        return DiscTitle(
            index=t["index"],
            name=t.get("name", ""),
            duration_seconds=t.get("duration_seconds", 0),
            chapters=t.get("chapters", 0),
            size_bytes=t.get("size_bytes", 0),
            filename=t.get("filename", ""),
            playlist=t.get("playlist", ""),
            resolution=t.get("resolution", ""),
            video_codec=t.get("video_codec", ""),
            audio_tracks=list(t.get("audio_tracks", [])),
            subtitle_tracks=list(t.get("subtitle_tracks", [])),
            stream_count=t.get("stream_count", 0),
            segment_count=t.get("segment_count", 1),
            segment_map=t.get("segment_map", ""),
        )

    def drive_info(self, disc_number: int | None = None, *, index: int = 0,
                   device: str = "D:") -> DriveInfo:
        """A loaded ``DriveInfo`` for the given disc."""
        d = self._disc_raw(disc_number)
        label = d.get("disc_label") or d.get("disc_name", "")
        return DriveInfo(
            index=index,
            name="BD-RE Drive",
            disc_label=label,
            device=device,
            has_disc=True,
            is_present=True,
            state_label=f"Disc: {label}",
        )

    @staticmethod
    def preflight() -> MakeMKVPreflight:
        return MakeMKVPreflight(
            exe=Path("makemkvcon"), version="v1.18.3", available=True, error=""
        )

    # -- TMDb -----------------------------------------------------------
    def tmdb(self) -> dict[str, Any]:
        return self.raw.get("tmdb", {})

    def search_result(self) -> MetadataSearchResult:
        t = self.tmdb()
        return MetadataSearchResult(
            source_id=t.get("source_id", f"{self.media_type}:0"),
            title=t.get("title", self.title),
            year=t.get("year", self.year),
            media_type=t.get("media_type", self.media_type),
            overview=t.get("overview", ""),
            popularity=t.get("popularity", 1.0),
        )

    def search_results(self) -> list[MetadataSearchResult]:
        """The list a TMDb search returns — the canonical match first."""
        return [self.search_result()]

    def show_detail(self) -> ShowDetail:
        t = self.tmdb()
        seasons = []
        for s in t.get("seasons", []):
            episodes = [
                EpisodeMetadata(
                    season_number=e.get("season_number", s.get("season_number", 1)),
                    episode_number=e.get("episode_number", i + 1),
                    title=e.get("title", ""),
                    runtime_seconds=e.get("runtime_seconds", 0),
                    overview=e.get("overview", ""),
                )
                for i, e in enumerate(s.get("episodes", []))
            ]
            seasons.append(
                SeasonMetadata(
                    season_number=s.get("season_number", 1),
                    episodes=episodes,
                    name=s.get("name", ""),
                )
            )
        return ShowDetail(
            source_id=t.get("source_id", "tv:0"),
            title=t.get("title", self.title),
            year=t.get("year", self.year or 0),
            seasons=seasons,
            overview=t.get("overview", ""),
        )

    def movie_detail(self) -> MovieDetail:
        t = self.tmdb()
        return MovieDetail(
            source_id=t.get("source_id", "movie:0"),
            title=t.get("title", self.title),
            year=t.get("year", self.year or 0),
            runtime_seconds=t.get("movie_runtime_seconds") or 0,
            overview=t.get("overview", ""),
        )

    # -- dvdcompare -----------------------------------------------------
    def dvdcompare(self) -> dict[str, Any]:
        return self.raw.get("dvdcompare", {})

    def release_name(self) -> str:
        return self.dvdcompare().get("release", "")

    def planned_discs(self) -> list[PlannedDisc]:
        discs = []
        for d in self.dvdcompare().get("discs", []):
            episodes = [
                PlannedEpisode(
                    season_number=e.get("season_number", 1),
                    episode_number=e.get("episode_number", i + 1),
                    title=e.get("title", ""),
                    runtime=e.get("runtime") or _runtime_str(e.get("runtime_seconds", 0)),
                    runtime_seconds=e.get("runtime_seconds", 0),
                    file_name=e.get("file_name", ""),
                )
                for i, e in enumerate(d.get("episodes", []))
            ]
            extras = [
                PlannedExtra(
                    title=x.get("title", ""),
                    runtime_seconds=x.get("runtime_seconds", 0),
                    feature_type=x.get("feature_type", ""),
                    file_name=x.get("file_name", ""),
                    pointer_fid=x.get("pointer_fid"),
                )
                for x in d.get("extras", [])
            ]
            discs.append(
                PlannedDisc(
                    number=d.get("number", 1),
                    disc_format=d.get("disc_format", ""),
                    is_film=d.get("is_film", False),
                    episodes=episodes,
                    extras=extras,
                    title=d.get("title", ""),
                )
            )
        return discs


def load_scenario(name: str) -> Scenario:
    """Load a scenario by file stem (e.g. ``"chernobyl-2019"``)."""
    path = SCENARIOS_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"No scenario fixture at {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Scenario(raw=raw, path=path)


def load_from_path(path: Path) -> Scenario:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return Scenario(raw=raw, path=Path(path))


def available_scenarios() -> list[str]:
    """Return the stems of all committed scenario fixtures."""
    if not SCENARIOS_DIR.exists():
        return []
    return sorted(p.stem for p in SCENARIOS_DIR.glob("*.json"))


# ---------------------------------------------------------------------------
# Media-type filtering — the basis for category-targeted parametrized tests
# ---------------------------------------------------------------------------

def _scenario_category(name: str) -> str:
    """Cheap classify of a scenario by stem (reads only the committed JSON)."""
    path = SCENARIOS_DIR / f"{name}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return classify(raw)


def scenarios_by_category(*categories: str) -> list[str]:
    """Return the stems of every committed scenario in *categories*.

    Used to parametrize a test over exactly the media types it applies to;
    newly generated fixtures of a matching type are picked up automatically::

        @pytest.mark.parametrize("name", scenarios_by_category(CATEGORY_MOVIE))
        def test_movie_flow(gui, name): ...
    """
    wanted = set(categories)
    return [n for n in available_scenarios() if _scenario_category(n) in wanted]


def movie_scenarios() -> list[str]:
    """Every movie scenario."""
    return scenarios_by_category(CATEGORY_MOVIE)


def tv_scenarios() -> list[str]:
    """Every TV scenario (mini-series, single season, or full series)."""
    return scenarios_by_category(*TV_CATEGORIES)


def miniseries_scenarios() -> list[str]:
    """Every limited / mini-series scenario."""
    return scenarios_by_category(CATEGORY_TV_MINISERIES)


def series_scenarios() -> list[str]:
    """Every ongoing multi-season series scenario (single seasons + full sets)."""
    return scenarios_by_category(CATEGORY_TV_SERIES)


def season_scenarios() -> list[str]:
    """The single-season-rip subset of the series scenarios (e.g. ``Season 01``).

    A view over ``tv_series`` rather than a separate category — "seasonal
    series" is series content, so it also flows through the series tests.
    """
    return [
        n for n in series_scenarios()
        if _is_seasonal_source(json.loads((SCENARIOS_DIR / f"{n}.json").read_text(encoding="utf-8")))
    ]


def category_counts() -> dict[str, int]:
    """Map each category to how many committed fixtures it has."""
    counts: dict[str, int] = {c: 0 for c in ALL_CATEGORIES}
    for name in available_scenarios():
        counts[_scenario_category(name)] = counts.get(_scenario_category(name), 0) + 1
    return counts

