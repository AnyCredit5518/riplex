"""Filename and path normalization for Windows-safe, Plex-compatible output."""

from __future__ import annotations

import re

# Characters illegal in Windows file/folder names
_WINDOWS_ILLEGAL = re.compile(r'[<>:"/\\|?*]')

# Collapse multiple spaces into one
_MULTI_SPACE = re.compile(r" {2,}")

# Plex-supported extras folder names (canonical casing)
EXTRAS_FOLDERS: list[str] = [
    "Behind The Scenes",
    "Deleted Scenes",
    "Featurettes",
    "Interviews",
    "Scenes",
    "Shorts",
    "Trailers",
    "Other",
]

# Default extras folders included in skeleton output
DEFAULT_MOVIE_EXTRAS: list[str] = [
    "Featurettes",
    "Interviews",
    "Behind The Scenes",
    "Deleted Scenes",
    "Trailers",
    "Other",
]

DEFAULT_TV_EXTRAS: list[str] = [
    "Featurettes",
    "Behind The Scenes",
    "Interviews",
]


def sanitize_filename(name: str) -> str:
    """Remove or replace characters that are illegal in Windows filenames.

    Colons are removed (with surrounding space collapsed) to keep titles
    readable. Other illegal characters are stripped outright. Leading
    dash prefixes (e.g. ``---- "Title"``) from dvdcompare child entries
    are stripped along with surrounding quotes.
    """
    # Strip leading dashes used as dvdcompare child-entry markers
    name = name.lstrip("-").strip()
    # Strip surrounding quotes
    if len(name) >= 2 and name[0] == '"' and name[-1] == '"':
        name = name[1:-1]
    # Handle colon specifically: "Title: Subtitle" -> "Title Subtitle"
    name = name.replace(": ", " ").replace(":", "")
    # Strip remaining illegal chars
    name = _WINDOWS_ILLEGAL.sub("", name)
    # Collapse whitespace
    name = _MULTI_SPACE.sub(" ", name).strip()
    return name


def format_runtime(total_seconds: int) -> str:
    """Format seconds into a human-friendly runtime string.

    Examples: 180 -> "3h 0m", 2820 -> "47m", 10920 -> "3h 2m"
    """
    if total_seconds <= 0:
        return "unknown"
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def movie_folder_name(title: str, year: int) -> str:
    """Build the canonical Plex movie folder name."""
    safe = sanitize_filename(title)
    return f"{safe} ({year})"


def movie_file_name(title: str, year: int, ext: str = ".mkv") -> str:
    """Build the canonical Plex movie filename."""
    safe = sanitize_filename(title)
    return f"{safe} ({year}){ext}"


def show_folder_name(title: str, year: int) -> str:
    """Build the canonical Plex TV show folder name."""
    safe = sanitize_filename(title)
    return f"{safe} ({year})"


def season_folder_name(season_number: int) -> str:
    """Build a season folder name, e.g. 'Season 01'."""
    return f"Season {season_number:02d}"


def episode_file_name(
    show_title: str,
    year: int,
    season: int,
    episode: int,
    episode_title: str,
    ext: str = ".mkv",
) -> str:
    """Build a canonical Plex episode filename."""
    safe_show = sanitize_filename(show_title)
    safe_ep = sanitize_filename(episode_title)
    return f"{safe_show} ({year}) - s{season:02d}e{episode:02d} - {safe_ep}{ext}"


def build_movie_paths(
    title: str,
    year: int,
    include_extras: bool = True,
    extras_list: list[str] | None = None,
) -> list[str]:
    """Build the list of relative Plex paths for a movie."""
    folder = movie_folder_name(title, year)
    base = f"\\Movies\\{folder}\\"
    paths = [base]
    if include_extras:
        for extra in extras_list or DEFAULT_MOVIE_EXTRAS:
            paths.append(f"{base}{extra}\\")
    return paths


def build_show_paths(
    title: str,
    year: int,
    season_numbers: list[int],
    include_extras: bool = True,
    extras_list: list[str] | None = None,
) -> list[str]:
    """Build the list of relative Plex paths for a TV show."""
    folder = show_folder_name(title, year)
    base = f"\\TV Shows\\{folder}\\"
    paths: list[str] = []
    for sn in sorted(season_numbers):
        paths.append(f"{base}{season_folder_name(sn)}\\")
    if include_extras:
        for extra in extras_list or DEFAULT_TV_EXTRAS:
            paths.append(f"{base}{extra}\\")
    return paths
