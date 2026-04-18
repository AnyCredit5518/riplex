"""Auto-detection helpers for batch organize mode.

Detects disc format from video resolution, identifies incomplete (still-ripping)
files, and groups subfolders by normalized title for batch processing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plex_planner.models import ScannedDisc, ScannedFile

log = logging.getLogger(__name__)

# Patterns stripped when grouping folder names into titles
_DISC_NUM_RE = re.compile(
    r"\s*[-–]\s*(?:Disc\s*\d+|D\d+)\s*$",
    re.IGNORECASE,
)
_BONUS_SUFFIX_RE = re.compile(
    r"\s*[-–]\s*(?:Special\s+Features?|Bonus|Extras?)\s*$",
    re.IGNORECASE,
)


@dataclass
class TitleGroup:
    """A group of folders that belong to the same title."""

    title: str
    folders: list[Path] = field(default_factory=list)
    detected_format: str | None = None


def detect_format(discs: list[ScannedDisc]) -> str | None:
    """Infer disc format from the maximum video resolution across all files.

    Returns a dvdcompare-compatible format string, or None if no video
    streams were found.
    """
    max_w = 0
    max_h = 0
    for disc in discs:
        for f in disc.files:
            if f.max_width > max_w:
                max_w = f.max_width
            if f.max_height > max_h:
                max_h = f.max_height

    if max_w == 0:
        return None
    if max_w >= 3840 or max_h >= 2160:
        return "Blu-ray 4K"
    if max_w >= 1920 or max_h >= 1080:
        return "Blu-ray"
    if max_w >= 1280 or max_h >= 720:
        return "Blu-ray"
    if max_w > 0:
        return "DVD"
    return None


def detect_incomplete(discs: list[ScannedDisc]) -> list[ScannedFile]:
    """Find files that appear to still be ripping (0 duration, no streams).

    Returns a list of files that should be skipped.
    """
    incomplete: list[ScannedFile] = []
    for disc in discs:
        for f in disc.files:
            if f.duration_seconds == 0 or f.stream_count == 0:
                incomplete.append(f)
    return incomplete


def _normalize_title(folder_name: str) -> str:
    """Strip disc numbers and bonus suffixes to get a base title.

    Examples:
        "Planet Earth III - Disc 1" -> "Planet Earth III"
        "Batman Begins Bonus"       -> "Batman Begins"
        "Oppenheimer"               -> "Oppenheimer"
        "BLUE PLANET II D2"         -> "BLUE PLANET II"
    """
    name = folder_name
    # Strip " - Disc N" or " - D1" style suffixes
    name = _DISC_NUM_RE.sub("", name)
    # Strip " - Special Features" / " - Bonus" / " - Extras"
    name = _BONUS_SUFFIX_RE.sub("", name)
    # Strip trailing " D1" / " D2" (no dash, as in "BLUE PLANET II D2")
    name = re.sub(r"\s+D\d+\s*$", "", name, flags=re.IGNORECASE)
    # Strip trailing "Bonus" / "Special Features" without a dash
    name = re.sub(
        r"\s+(?:Special\s+Features?|Bonus|Extras?)\s*$",
        "",
        name,
        flags=re.IGNORECASE,
    )
    return name.strip()


def group_title_folders(root: Path) -> list[TitleGroup]:
    """Group immediate subfolders of *root* by normalized title.

    Ignores folders starting with ``_`` (e.g. ``_archive``).
    Returns groups sorted by title, each containing the original folder paths.
    """
    groups: dict[str, list[Path]] = {}

    for sub in sorted(root.iterdir()):
        if not sub.is_dir():
            continue
        if sub.name.startswith("_"):
            log.debug("Skipping underscore folder: %s", sub.name)
            continue
        # Check that this folder (or its subfolders) actually contains MKVs
        has_mkvs = (
            any(sub.glob("*.mkv"))
            or any(sub.glob("*/*.mkv"))
        )
        if not has_mkvs:
            log.debug("Skipping empty folder: %s", sub.name)
            continue

        base = _normalize_title(sub.name)
        groups.setdefault(base, []).append(sub)

    result: list[TitleGroup] = []
    for title in sorted(groups):
        result.append(TitleGroup(title=title, folders=groups[title]))
    return result
