"""Write crash dump files containing traceback, app state, and recent logs.

A crash dump bundles everything a developer needs to diagnose an unhandled
exception into a single text file the user can attach to a GitHub issue.

Dumps live under the user's log directory (per platformdirs) so they survive
across sessions and don't pollute the user's CWD.
"""

from __future__ import annotations

import json
import platform as _platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from platformdirs import user_log_dir

from riplex.updater import get_current_version

_APP_NAME = "riplex"
_LOG_TAIL_BYTES = 64 * 1024  # last 64KB of the app log


def get_crash_dir() -> Path:
    """Return the directory where crash dumps and the GUI log live."""
    p = Path(user_log_dir(_APP_NAME)) / "crashes"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_log_path() -> Path:
    """Return the path the GUI should write its log file to."""
    p = Path(user_log_dir(_APP_NAME))
    p.mkdir(parents=True, exist_ok=True)
    return p / "riplex_app.log"


def write_crash_dump(
    *,
    exc_type: str,
    exc_message: str,
    traceback_text: str,
    state: dict[str, Any] | None = None,
    last_screen: str | None = None,
    log_path: Path | None = None,
) -> Path:
    """Write a timestamped crash dump and return its path.

    The dump contains a header (version, platform, exception summary), the
    full Python traceback, a JSON-ish snapshot of the app state with
    non-serialisable values rendered as their repr, and the tail of the GUI
    log file if available.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe_type = "".join(c for c in exc_type if c.isalnum() or c in "_-") or "Exception"
    dump_path = get_crash_dir() / f"crash-{timestamp}-{safe_type}.txt"

    parts: list[str] = []
    parts.append("=" * 70)
    parts.append("riplex crash dump")
    parts.append("=" * 70)
    parts.append(f"Timestamp:     {datetime.now(timezone.utc).isoformat()}")
    parts.append(f"Version:       {get_current_version()}")
    parts.append(f"Platform:      {_platform.platform()}")
    parts.append(f"Python:        {_platform.python_version()}")
    parts.append(f"Last screen:   {last_screen or '<unknown>'}")
    parts.append(f"Exception:     {exc_type}: {exc_message}")
    parts.append("")
    parts.append("-" * 70)
    parts.append("Traceback")
    parts.append("-" * 70)
    parts.append(traceback_text.rstrip())
    parts.append("")
    parts.append("-" * 70)
    parts.append("App state")
    parts.append("-" * 70)
    parts.append(_format_state(state or {}))
    parts.append("")
    parts.append("-" * 70)
    parts.append(f"Log tail (last {_LOG_TAIL_BYTES // 1024}KB)")
    parts.append("-" * 70)
    parts.append(_read_log_tail(log_path or get_log_path()))
    parts.append("")

    dump_path.write_text("\n".join(parts), encoding="utf-8")
    return dump_path


def _format_state(state: dict[str, Any]) -> str:
    """Render the app-state dict as JSON, falling back to repr for non-JSON values."""
    def default(obj: Any) -> str:
        return repr(obj)

    try:
        return json.dumps(state, indent=2, default=default, sort_keys=True)
    except Exception as exc:  # pragma: no cover — defensive
        return f"<failed to serialise state: {exc!r}>\n{state!r}"


def _read_log_tail(log_path: Path) -> str:
    """Return the tail of the log file, or a placeholder if unavailable."""
    try:
        if not log_path.exists():
            return f"<no log file at {log_path}>"
        size = log_path.stat().st_size
        with log_path.open("rb") as f:
            if size > _LOG_TAIL_BYTES:
                f.seek(-_LOG_TAIL_BYTES, 2)
                # Drop the partial first line.
                f.readline()
            data = f.read()
        return data.decode("utf-8", errors="replace")
    except OSError as exc:
        return f"<failed to read log file {log_path}: {exc}>"
