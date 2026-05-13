"""Build a pre-filled GitHub bug report URL from current app state."""

from __future__ import annotations

import platform
import urllib.parse
from pathlib import Path

from riplex.updater import GITHUB_REPO, get_current_version

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

    # MakeMKV diagnostics captured by the disc detection screen
    diag = state.get("makemkv_diag")
    if diag:
        diag_lines = [
            f"- exe: `{diag.get('exe') or '<not found>'}`",
            f"- version: `{diag.get('version') or '<unknown>'}`",
            f"- available: `{diag.get('available')}`",
        ]
        if diag.get("error"):
            diag_lines.append(f"- error: {diag.get('error')}")
        params["makemkv-diag"] = "\n".join(diag_lines)

    # Debug files hint
    debug_paths = _find_debug_paths(state)
    if debug_paths:
        params["debug-files"] = (
            "Debug folder found at:\n"
            + "\n".join(f"`{p}`" for p in debug_paths)
            + "\n\nPlease zip and attach."
        )

    return _NEW_ISSUE_BASE + "?" + urllib.parse.urlencode(params)


def build_crash_report_url(
    state: dict,
    *,
    exc_type: str,
    exc_message: str,
    traceback_text: str,
    last_screen: str | None = None,
    dump_path: str | None = None,
) -> str:
    """Return a GitHub new-issue URL pre-filled with crash details.

    Targets the crash_report.yml template. GitHub limits URL length to ~8KB,
    so the traceback is truncated if necessary.
    """
    params: dict[str, str] = {
        "template": "crash_report.yml",
        "labels": "bug,crash",
    }

    params["version"] = get_current_version()
    params["platform"] = platform.platform()
    params["frontend"] = "GUI"
    params["exception-type"] = exc_type
    if exc_message:
        params["exception-message"] = exc_message[:500]
    if last_screen:
        params["last-screen"] = last_screen

    # Truncate traceback to keep URL under GitHub's ~8KB limit.
    max_tb_len = 6000
    if len(traceback_text) > max_tb_len:
        traceback_text = (
            traceback_text[:max_tb_len]
            + "\n... [truncated, see attached crash dump for full trace]"
        )
    params["traceback"] = traceback_text

    debug_lines: list[str] = []
    if dump_path:
        debug_lines.append(
            "**Crash dump (please attach this file):**\n"
            f"`{dump_path}`\n\n"
            "It contains the full traceback, app state, and recent logs."
        )
    debug_paths = _find_debug_paths(state)
    if debug_paths:
        debug_lines.append(
            "Additional debug folders:\n"
            + "\n".join(f"`{p}`" for p in debug_paths)
            + "\n\nPlease zip and attach."
        )
    if debug_lines:
        params["debug-files"] = "\n\n".join(debug_lines)

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
