"""Title and label string parsing utilities.

Pure string manipulation — no I/O, no external dependencies.
"""

from __future__ import annotations

import re

_TRAILING_YEAR_RE = re.compile(r"\s*\(\d{4}\)\s*$")
_TRAILING_DISC_RE = re.compile(
    r"\s*[-_]?\s*(?:D(?:isc)?\s*\d+)\s*$", re.IGNORECASE,
)


def strip_year_from_title(name: str) -> tuple[str, int | None]:
    """Strip a trailing ``(YYYY)`` from a folder name.

    Returns ``(clean_title, year)`` where *year* is the extracted value
    or ``None`` if no trailing year was found.
    """
    m = _TRAILING_YEAR_RE.search(name)
    if m:
        year = int(m.group().strip().strip("()"))
        return name[: m.start()].strip(), year
    return name, None


def infer_title_from_scanned(scanned: list) -> str | None:
    """Derive a clean title from MKV title_tag metadata.

    Picks the title_tag of the longest file (most likely the main feature).
    Returns ``None`` when no useful title_tag is present.
    """
    all_files = [f for d in scanned for f in d.files]
    if not all_files:
        return None
    longest = max(all_files, key=lambda f: f.duration_seconds)
    tag = longest.title_tag
    if not tag or not tag.strip():
        return None
    # Strip trailing disc label (e.g. "SEVEN WORLDS ONE PLANET D1")
    clean = _TRAILING_DISC_RE.sub("", tag.strip())
    # Strip trailing year if embedded, e.g. "Waterworld (1995)"
    clean, _ = strip_year_from_title(clean)
    return clean or None


def parse_volume_label(label: str) -> str | None:
    """Extract a human-readable title from a disc volume label.

    Examples:
        "FROZEN_PLANET_II_D2" -> "Frozen Planet II"
        "PLANET_EARTH_III-Disc3" -> "Planet Earth III"
        "BLADE_RUNNER_2049" -> "Blade Runner 2049"
        "TGUN2" -> None (too short/ambiguous)
    """
    if not label or len(label) < 2:
        return None

    # Strip disc number suffix including its leading separator.
    cleaned = re.sub(r"[\s_-]+D(?:isc[\s_]*)?\d+\s*$", "", label, flags=re.IGNORECASE)

    # Replace underscores with spaces
    cleaned = cleaned.replace("_", " ").strip()

    if len(cleaned) < 2:
        return None

    # Title-case, preserving roman numerals
    words = cleaned.split()
    result = []
    for w in words:
        if re.fullmatch(r"[IVXLCDM]+", w, re.IGNORECASE):
            result.append(w.upper())
        else:
            result.append(w.capitalize())
    return " ".join(result)
