"""Shared paths for riplex log files."""

from pathlib import Path

from platformdirs import user_log_dir

_APP_NAME = "riplex"


def get_cli_log_path() -> Path:
    """Return the current user's CLI debug-log path."""
    return Path(user_log_dir(_APP_NAME)) / "riplex.log"