"""Build a pre-filled GitHub bug report URL from current app state."""

from __future__ import annotations

import platform
import urllib.parse
from pathlib import Path

from riplex_app.updater import GITHUB_REPO, get_current_version

_NEW_ISSUE_BASE = f"https://github.com/{GITHUB_REPO}/issues/new"


def build_bug_report_url(state: dict) -> str:
    """Return a GitHub new-issue URL pre-filled with available context."""
    params: dict[str, str] = {
        "template": "bug_report.yml",
        "labels": "bug",
    }

    # Version
    params["version"] = get_current_version()

    # Platform
    params["platform"] = platform.platform()

    # Frontend
    params["frontend"] = "GUI"

    # Disc name / volume label
    drive = state.get("drive")
    if drive and hasattr(drive, "disc_label") and drive.disc_label:
        params["disc-name"] = drive.disc_label
    elif state.get("title"):
        params["disc-name"] = state["title"]

    # Debug files hint
    debug_paths = _find_debug_paths(state)
    if debug_paths:
        params["debug-files"] = (
            "Debug folder found at:\n"
            + "\n".join(f"`{p}`" for p in debug_paths)
            + "\n\nPlease zip and attach."
        )

    return _NEW_ISSUE_BASE + "?" + urllib.parse.urlencode(params)


def _find_debug_paths(state: dict) -> list[str]:
    """Return paths to _riplex debug folders or snapshot files, if they exist."""
    paths: list[str] = []

    # Check rip output for _riplex debug folder
    tmdb_match = state.get("tmdb_match")
    if tmdb_match and tmdb_match.title:
        try:
            from riplex.manifest import build_rip_path
            rip_root = build_rip_path(tmdb_match.title, tmdb_match.year or 0)
            debug_dir = rip_root / "_riplex"
            if debug_dir.exists():
                paths.append(str(debug_dir))
        except Exception:
            pass

    # Check source folder for organize snapshots
    source_folder = state.get("source_folder")
    if source_folder:
        sf = Path(source_folder)
        snapshot = sf / f"{sf.name}.snapshot.json"
        if snapshot.exists():
            paths.append(str(snapshot))
        debug_dir = sf / "_riplex"
        if debug_dir.exists() and str(debug_dir) not in paths:
            paths.append(str(debug_dir))

    return paths
