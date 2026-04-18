"""Abstract metadata provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class MetadataSearchResult:
    """A single search result from the metadata source."""

    source_id: str  # provider-specific ID
    title: str
    year: int | None
    media_type: Literal["movie", "tv"]
    overview: str = ""


@dataclass
class EpisodeMetadata:
    """Metadata for a single episode."""

    season_number: int
    episode_number: int
    title: str
    runtime_seconds: int = 0
    overview: str = ""


@dataclass
class SeasonMetadata:
    """Metadata for a single season."""

    season_number: int
    episodes: list[EpisodeMetadata] = field(default_factory=list)


@dataclass
class MovieDetail:
    """Full movie metadata."""

    source_id: str
    title: str
    year: int
    runtime_seconds: int = 0
    overview: str = ""


@dataclass
class ShowDetail:
    """Full TV show metadata."""

    source_id: str
    title: str
    year: int
    seasons: list[SeasonMetadata] = field(default_factory=list)
    overview: str = ""


class MetadataProvider(ABC):
    """Interface for fetching media metadata.

    Implementations can wrap TMDb, TheTVDB, or any other source.
    """

    @abstractmethod
    async def search(
        self,
        query: str,
        *,
        year: int | None = None,
        media_type: Literal["movie", "tv", "auto"] = "auto",
    ) -> list[MetadataSearchResult]:
        """Search for titles matching the query."""

    @abstractmethod
    async def get_movie_detail(self, source_id: str) -> MovieDetail:
        """Fetch full metadata for a movie."""

    @abstractmethod
    async def get_show_detail(
        self, source_id: str, *, include_specials: bool = True
    ) -> ShowDetail:
        """Fetch full metadata for a TV show, including episode lists."""
