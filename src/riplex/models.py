"""Data models for riplex."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class SearchRequest:
    """User-provided search parameters."""

    title: str
    year: int | None = None
    season_number: int | None = None
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
    classification: str = ""  # rip-time classification from manifest


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
    # dvdcompare fid this extra's title was hyperlinked to on the source
    # page. dvdcompare wraps a bonus title in an anchor when that item is
    # actually the main feature of a different film page (e.g. disc-31 of
    # a Complete Series set linking each standalone TV-movie sequel to its
    # own dvdcompare entry). ``group_release_discs`` uses this to split a
    # bonus-films disc into its own DiscGroup even when the source page
    # doesn't flag the disc as a film disc.
    pointer_fid: int | None = None


@dataclass
class PlannedDisc:
    """A physical disc in a release."""

    number: int
    disc_format: str  # e.g. "Blu-ray 4K", "Blu-ray"
    is_film: bool = False
    episodes: list[PlannedEpisode] = field(default_factory=list)
    extras: list[PlannedExtra] = field(default_factory=list)
    # Optional label from dvdcompare (e.g. "Season 1") — set when the
    # outer release used a placeholder like "DISCS ONE - FOUR: Season 1"
    # that pointed at a per-season subpage. Empty when unavailable.
    title: str = ""


@dataclass
class FilmSlot:
    """One feature-length film on a bonus-films disc.

    Multi-film discs (e.g. disc 31 of *Psych: The Complete Series* holding
    three standalone TV-movies) need a separate TMDb match per film so each
    ripped MKV can organize into its own ``Title (Year)/`` folder. A
    ``FilmSlot`` pairs the dvdcompare-supplied film title and runtime with
    its assigned TMDb match. ``source`` records provenance so the UI can
    distinguish user-confirmed picks from auto-filled best guesses.
    """

    title: str
    runtime_seconds: int = 0
    tmdb_match: object | None = None
    source: Literal["user", "auto"] | None = None
    # dvdcompare fid this film links to on the parent release page, when
    # the slot was seeded from a hyperlinked feature. Autofill can fetch
    # this fid to get the canonical film title/year for a high-confidence
    # TMDb search instead of relying on the free-text bonus label.
    dvdcompare_fid: int | None = None


@dataclass
class DiscGroup:
    """A subset of a release's discs that maps to a single organize target.

    Some multi-disc releases (e.g. Psych: The Complete Series) bundle
    multiple distinct works — a TV show plus standalone films — that must
    each organize into their own folder. A ``DiscGroup`` pairs a set of disc
    numbers with the TMDb match those discs should organize under.

    When ``films`` is empty the group represents a single work — a movie
    (possibly spread across format discs), a TV series, or a movie with
    its bonus platter — and the group-level ``tmdb_match`` slot is used.
    When ``films`` is non-empty the group holds one ``FilmSlot`` per
    distinct linked work (dvdcompare hyperlinked each item to its own
    film page), each carrying its own TMDb match; the top-level
    ``tmdb_match`` is unused. ``source`` records how the top-level match
    got there so the UI can differentiate user-confirmed picks from
    auto-filled best guesses. ``tmdb_match`` is typed loosely (kept as
    ``object``) so this pure data module doesn't need to import from
    ``riplex.metadata``.
    """

    id: str
    label: str
    disc_numbers: list[int]
    tmdb_match: object | None = None
    source: Literal["user", "auto"] | None = None
    default_search_title: str = ""
    films: list[FilmSlot] = field(default_factory=list)

    def is_complete(self) -> bool:
        """Return True when every slot in the group has a confirmed (or
        auto-filled) match. Used to gate Start Ripping and to color the
        group's border in the Disc Overview."""
        if self.films:
            return all(f.tmdb_match is not None for f in self.films)
        return self.tmdb_match is not None


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
    organized_tag: str | None = None  # riplex organized marker
    perceptual_hash: int | None = None  # 64-bit dhash for duplicate detection
    classification: str = ""  # rip-time classification from manifest


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
