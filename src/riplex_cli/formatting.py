"""Terminal formatting utilities for the riplex CLI."""

from __future__ import annotations

import logging
import random
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable


LOG_DIR = Path(tempfile.gettempdir()) / "riplex"


_BAR_STYLES = [
    {"fill": "=", "head": ">", "empty": " ", "left": "[", "right": "]"},
    {"fill": "\u2588", "head": "\u2589", "empty": "\u2591", "left": "\u2595", "right": "\u258f"},
    {"fill": "#", "head": ">", "empty": "-", "left": "[", "right": "]"},
    {"fill": "\u2593", "head": "\u2592", "empty": "\u2591", "left": "|", "right": "|"},
    {"fill": "*", "head": "o", "empty": ".", "left": "<", "right": ">"},
    {"fill": "\u25a0", "head": "\u25a1", "empty": "\u00b7", "left": "\u2595", "right": "\u258f"},
    {"fill": "/", "head": "|", "empty": " ", "left": "[", "right": "]"},
    {"fill": "\u2501", "head": "\u254b", "empty": "\u2500", "left": "\u2523", "right": "\u252b"},
    {"fill": "~", "head": "\u2248", "empty": " ", "left": "{", "right": "}"},
    {"fill": "\u2580", "head": "\u2584", "empty": "_", "left": "|", "right": "|"},
]


def random_bar_style() -> dict[str, str]:
    """Pick a random progress bar style for visual variety."""
    return random.choice(_BAR_STYLES)


def build_execute_command() -> str:
    """Reconstruct the current CLI invocation with ``--execute`` appended.

    Strips any ``--dry-run`` / ``-n`` flags and quotes arguments that
    contain spaces so the result is safe to copy/paste.
    """
    raw = sys.argv[:]
    cleaned = [a for a in raw if a not in ("--dry-run", "-n")]
    if "--execute" not in cleaned:
        cleaned.append("--execute")
    if cleaned:
        cleaned[0] = Path(cleaned[0]).stem
    parts = [f'"{a}"' if " " in a else a for a in cleaned]
    return " ".join(parts)


def dry_run_banner(verb: str) -> str:
    """Return the banner printed at the start of a dry-run."""
    return f"--- DRY RUN (pass --execute to {verb}) ---"


def execute_hint(subcommand: str) -> str:
    """Return the end-of-run hint with a copy-pasteable command."""
    verb = "apply these changes" if subcommand == "organize" else "rip"
    return f"Re-run with --execute to {verb}:\n  {build_execute_command()}"


def setup_logging(verbose: bool = False) -> Path:
    """Configure file-based debug logging for the entire package.

    Always writes DEBUG-level output to a log file in the temp directory.
    When *verbose* is True, also prints DEBUG messages to stderr.

    Returns the path to the log file.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "riplex.log"

    root = logging.getLogger("riplex")
    root.setLevel(logging.DEBUG)

    # File handler: always DEBUG
    fh = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(fh)

    # Console handler: only when verbose
    if verbose:
        ch = logging.StreamHandler(sys.stderr)
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        root.addHandler(ch)

    return log_file


def make_progress_callback(
    start_time: float,
    total_bytes: int,
    bar_style: dict[str, str] | None = None,
    format_time: Callable[[int], str] | None = None,
) -> Callable:
    """Create a progress callback for makemkvcon rip operations.

    Returns a callback compatible with ``makemkv.run_rip(progress_callback=...)``.
    """
    if bar_style is None:
        bar_style = random_bar_style()
    if format_time is None:
        from riplex.disc.analysis import format_seconds
        format_time = format_seconds

    last_pct = [-1]
    style = bar_style
    start = start_time
    total = total_bytes

    def _progress_cb(progress):
        if progress.max_val > 0:
            pct = progress.current * 100 // progress.max_val
            if pct != last_pct[0]:
                last_pct[0] = pct
                bar_width = 30
                filled = bar_width * pct // 100
                bar = (style["fill"] * filled
                       + style["head"] * (1 if filled < bar_width else 0)
                       + style["empty"] * (bar_width - filled - (1 if filled < bar_width else 0)))
                elapsed = time.monotonic() - start
                done_bytes = total * pct // 100
                done_gb = done_bytes / (1024 ** 3)
                total_gb = total / (1024 ** 3)
                speed_mbs = (done_bytes / (1024 ** 2)) / elapsed if elapsed > 1 else 0
                if pct > 0 and speed_mbs > 0:
                    remaining_bytes = total - done_bytes
                    eta_secs = int(remaining_bytes / (speed_mbs * 1024 * 1024))
                    eta_str = format_time(eta_secs)
                else:
                    eta_str = "..."
                print(
                    f"\r  {style['left']}{bar}{style['right']} {pct:3d}%  "
                    f"{done_gb:.1f}/{total_gb:.1f} GB  "
                    f"{speed_mbs:.0f} MB/s  ETA {eta_str}   ",
                    end="", flush=True,
                )

    return _progress_cb
