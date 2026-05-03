"""Configuration file support for riplex.

Loads settings from a TOML config file. Checked locations (first match wins):
  1. ./riplex.toml  (project-local)
  2. %APPDATA%\\riplex\\config.toml  (Windows user)
  3. ~/.config/riplex/config.toml    (Unix/fallback)
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

_FILE_NAME = "config.toml"
_LOCAL_FILE_NAME = "riplex.toml"


def _candidate_paths() -> list[Path]:
    paths: list[Path] = [
        Path.cwd() / _LOCAL_FILE_NAME,
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(Path(appdata) / "riplex" / _FILE_NAME)
    paths.append(Path.home() / ".config" / "riplex" / _FILE_NAME)
    return paths


def load_config() -> dict[str, Any]:
    """Load and return the first config file found, or an empty dict."""
    for path in _candidate_paths():
        if path.is_file():
            with open(path, "rb") as f:
                try:
                    return tomllib.load(f)
                except tomllib.TOMLDecodeError as exc:
                    raise SystemExit(
                        f"Error: invalid config file {path}\n  {exc}\n"
                        f"Run 'riplex setup --force' to delete it and start fresh."
                    ) from None
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


def _config_write_path() -> Path:
    """Determine the writable config path (user-scoped)."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "riplex" / _FILE_NAME
    return Path.home() / ".config" / "riplex" / _FILE_NAME


def save_config(
    *,
    tmdb_api_key: str = "",
    output_root: str = "",
    rip_output: str = "",
    archive_root: str = "",
) -> Path:
    """Write a TOML config file with the given values.

    Only non-empty values are written. Backslashes in paths are
    normalized to forward slashes.  Returns the path written.
    """
    config_path = _config_write_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    if tmdb_api_key:
        lines.append(f'tmdb_api_key = "{tmdb_api_key}"')
    if output_root:
        lines.append(f'output_root = "{output_root.replace(chr(92), "/")}"')
    if rip_output:
        lines.append(f'rip_output = "{rip_output.replace(chr(92), "/")}"')
    if archive_root:
        lines.append(f'archive_root = "{archive_root.replace(chr(92), "/")}"')

    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return config_path
