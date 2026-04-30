"""Output formatters for text and JSON."""

from __future__ import annotations

import json
from typing import Any

from riplex.models import PlannedMovie, PlannedShow


def to_dict(planned: PlannedMovie | PlannedShow) -> dict[str, Any]:
    """Convert a planned result to a JSON-serializable dict."""
    if isinstance(planned, PlannedMovie):
        return _movie_dict(planned)
    return _show_dict(planned)


def to_json(planned: PlannedMovie | PlannedShow, indent: int = 2) -> str:
    """Render planned result as a JSON string."""
    return json.dumps(to_dict(planned), indent=indent, ensure_ascii=False)


def to_text(planned: PlannedMovie | PlannedShow) -> str:
    """Render planned result as human-readable text."""
    if isinstance(planned, PlannedMovie):
        return _movie_text(planned)
    return _show_text(planned)


# -- movie formatters ---------------------------------------------------------


def _movie_dict(m: PlannedMovie) -> dict[str, Any]:
    return {
        "type": "movie",
        "canonical_title": m.canonical_title,
        "year": m.year,
        "runtime": m.runtime,
        "runtime_seconds": m.runtime_seconds,
        "relative_paths": m.relative_paths,
        "main_file": m.main_file,
    }


def _movie_text(m: PlannedMovie) -> str:
    lines = [
        f"type: movie",
        f"canonical_title: {m.canonical_title}",
        f"year: {m.year}",
        f"runtime: {m.runtime}",
        "",
        "relative_paths:",
    ]
    for p in m.relative_paths:
        lines.append(f"  {p}")
    lines.append("")
    lines.append("main_file:")
    lines.append(f"  {m.main_file}")
    return "\n".join(lines)


# -- show formatters ----------------------------------------------------------


def _show_dict(s: PlannedShow) -> dict[str, Any]:
    seasons = []
    for season in s.seasons:
        eps = []
        for ep in season.episodes:
            eps.append(
                {
                    "season_number": ep.season_number,
                    "episode_number": ep.episode_number,
                    "title": ep.title,
                    "runtime": ep.runtime,
                    "runtime_seconds": ep.runtime_seconds,
                    "file_name": ep.file_name,
                }
            )
        seasons.append(
            {
                "season_number": season.season_number,
                "episodes": eps,
            }
        )
    return {
        "type": "tv",
        "canonical_title": s.canonical_title,
        "year": s.year,
        "relative_paths": s.relative_paths,
        "seasons": seasons,
    }


def _show_text(s: PlannedShow) -> str:
    lines = [
        f"type: tv",
        f"canonical_title: {s.canonical_title}",
        f"year: {s.year}",
        "",
        "relative_paths:",
    ]
    for p in s.relative_paths:
        lines.append(f"  {p}")
    lines.append("")
    lines.append("items:")
    for season in s.seasons:
        for ep in season.episodes:
            label = (
                f"s{ep.season_number:02d}e{ep.episode_number:02d}"
                f" - {ep.title} - {ep.runtime}"
            )
            lines.append(f"  {label}")
            lines.append(f"    file: {ep.file_name}")
    return "\n".join(lines)
