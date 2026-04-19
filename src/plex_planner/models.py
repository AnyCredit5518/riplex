"""Data models for plex-planner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class SearchRequest:
    """User-provided search parameters."""

    title: str
    year: int | None = None
    media_type: Literal["movie", "tv", "auto"] = "auto"
    include_specials: bool = True
    include_extras_skeleton: bool = True


@dataclass
class PlannedEpisode:
    """A single planned episode or special."""

    season_number: int
    episode_number: int
    title: str
    runtime: str  # human-readable, e.g. "48m" or "1h 2m"
    runtime_seconds: int = 0
    file_name: str = ""


@dataclass
class PlannedSeason:
    """A single season (Season 00 = specials)."""

    season_number: int
    episodes: list[PlannedEpisode] = field(default_factory=list)


@dataclass
class PlannedMovie:
    """Planned output for a movie title."""

    canonical_title: str
    year: int
    runtime: str
    runtime_seconds: int
    relative_paths: list[str] = field(default_factory=list)
    main_file: str = ""
    extras_folders: list[str] = field(default_factory=list)
    discs: list[PlannedDisc] = field(default_factory=list)


@dataclass
class PlannedShow:
    """Planned output for a TV show title."""

    canonical_title: str
    year: int
    relative_paths: list[str] = field(default_factory=list)
    seasons: list[PlannedSeason] = field(default_factory=list)
    extras_folders: list[str] = field(default_factory=list)
    discs: list[PlannedDisc] = field(default_factory=list)


@dataclass
class MatchCandidate:
    """A possible match between a ripped file and a planned episode/movie."""

    file_name: str
    file_duration_seconds: int
    matched_label: str  # e.g. "s01e03 - Deserts and Grasslands"
    matched_runtime_seconds: int
    delta_seconds: int
    confidence: str  # "high", "medium", "low"


# ---------------------------------------------------------------------------
# Disc / extras models (populated from dvdcompare-scraper)
# ---------------------------------------------------------------------------


@dataclass
class PlannedExtra:
    """A single bonus feature on a disc (featurette, interview, etc.)."""

    title: str
    runtime_seconds: int = 0
    feature_type: str = ""  # e.g. "featurette", "documentary", "behind-the-scenes montage"
    file_name: str = ""


@dataclass
class PlannedDisc:
    """A physical disc in a release."""

    number: int
    disc_format: str  # e.g. "Blu-ray 4K", "Blu-ray"
    is_film: bool = False
    episodes: list[PlannedEpisode] = field(default_factory=list)
    extras: list[PlannedExtra] = field(default_factory=list)


@dataclass
class ScannedFile:
    """A single MKV file found in a MakeMKV rip folder."""

    name: str
    path: str  # absolute path
    duration_seconds: int = 0
    size_bytes: int = 0
    stream_count: int = 0
    stream_fingerprint: str = ""  # e.g. "h264:1920x1080|ac3:eng:2ch|sub:eng|sub:spa"
    chapter_count: int = 0
    chapter_durations: list[int] = field(default_factory=list)  # per-chapter duration in seconds
    title_tag: str | None = None  # MKV container title tag (disc label)
    max_width: int = 0  # max video stream width (e.g. 3840)
    max_height: int = 0  # max video stream height (e.g. 2160)
    organized_tag: str | None = None  # plex-planner organized marker
    perceptual_hash: int | None = None  # 64-bit dhash for duplicate detection


@dataclass
class ScannedDisc:
    """A group of MKV files from one disc (or one subfolder)."""

    folder_name: str
    files: list[ScannedFile] = field(default_factory=list)


@dataclass
class OrganizeResult:
    """Result of matching scanned files to planned content."""

    matched: list[MatchCandidate] = field(default_factory=list)
    unmatched: list[ScannedFile] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)  # labels with no file
