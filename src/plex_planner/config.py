"""Configuration file support for plex-planner.

Loads settings from a TOML config file. Checked locations (first match wins):
  1. ./plex-planner.toml  (project-local)
  2. %APPDATA%\\plex-planner\\config.toml  (Windows user)
  3. ~/.config/plex-planner/config.toml    (Unix/fallback)
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

_FILE_NAME = "config.toml"
_LOCAL_FILE_NAME = "plex-planner.toml"


def _candidate_paths() -> list[Path]:
    paths: list[Path] = [
        Path.cwd() / _LOCAL_FILE_NAME,
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(Path(appdata) / "plex-planner" / _FILE_NAME)
    paths.append(Path.home() / ".config" / "plex-planner" / _FILE_NAME)
    return paths


def load_config() -> dict[str, Any]:
    """Load and return the first config file found, or an empty dict."""
    for path in _candidate_paths():
        if path.is_file():
            with open(path, "rb") as f:
                return tomllib.load(f)
    return {}


def get_api_key(cli_value: str | None = None) -> str:
    """Resolve the TMDb API key from (in priority order):
    1. CLI argument
    2. TMDB_API_KEY environment variable
    3. Config file (tmdb_api_key)
    """
    if cli_value:
        return cli_value

    env_val = os.environ.get("TMDB_API_KEY", "")
    if env_val:
        return env_val

    cfg = load_config()
    return cfg.get("tmdb_api_key", "")


def get_output_root(cli_value: str | None = None) -> str:
    """Resolve the output root directory from (in priority order):
    1. CLI --output argument
    2. PLEX_ROOT environment variable
    3. Config file (output_root)

    Returns an empty string if none is set (caller decides the default).
    """
    if cli_value:
        return cli_value

    env_val = os.environ.get("PLEX_ROOT", "")
    if env_val:
        return env_val

    cfg = load_config()
    return cfg.get("output_root", "")


def get_rip_output(cli_value: str | None = None) -> str:
    """Resolve the rip output directory from (in priority order):
    1. CLI argument
    2. Config file (rip_output)
    3. Default: {output_root}/Rips

    Returns an empty string if neither rip_output nor output_root is set.
    """
    if cli_value:
        return cli_value

    cfg = load_config()
    rip_out = cfg.get("rip_output", "")
    if rip_out:
        return rip_out

    # Fall back to {output_root}/Rips
    output_root = get_output_root()
    if output_root:
        return str(Path(output_root) / "Rips")
    return ""


def get_archive_root() -> str:
    """Resolve the archive root directory from config file (archive_root).

    Returns an empty string if not set (archiving disabled).
    """
    cfg = load_config()
    return cfg.get("archive_root", "")
