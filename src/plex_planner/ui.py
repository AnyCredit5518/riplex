"""Interactive prompt utilities for plex-planner CLI.

All user-facing prompts (numbered lists, confirmations, free-text input) live
here.  Every function checks ``is_interactive()`` and returns the default
value silently when running in non-interactive mode (piped stdin, --auto flag,
or explicitly disabled).

Prompts are printed to **stdout**; diagnostic messages stay on stderr.
"""

from __future__ import annotations

import sys

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_auto_mode: bool = False


def set_auto_mode(auto: bool) -> None:
    """Enable or disable automatic (non-interactive) mode."""
    global _auto_mode
    _auto_mode = auto


def is_interactive() -> bool:
    """Return True when interactive prompts should be shown.

    Interactive mode is active when:
    * stdin is connected to a real terminal (TTY), AND
    * ``--auto`` was **not** passed on the command line.
    """
    if _auto_mode:
        return False
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------

def prompt_choice(
    header: str,
    options: list[str],
    *,
    default: int = 0,
) -> int:
    """Show a numbered list and return the 0-based index chosen by the user.

    Parameters
    ----------
    header:
        A short label printed above the list (e.g. "Select a TMDb match:").
    options:
        Display strings for each option.  Indices are 1-based in the UI.
    default:
        0-based index returned when the user presses Enter without typing,
        or when running in non-interactive mode.

    Returns
    -------
    int
        The 0-based index of the selected option.
    """
    if not options:
        return default
    default = max(0, min(default, len(options) - 1))

    if not is_interactive():
        return default

    print(f"\n{header}")
    for i, opt in enumerate(options):
        marker = " (* recommended)" if i == default else ""
        print(f"  {i + 1}. {opt}{marker}")

    while True:
        try:
            raw = input(f"Choice [1-{len(options)}, default={default + 1}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return default

        if not raw:
            return default

        try:
            choice = int(raw)
        except ValueError:
            print(f"  Enter a number between 1 and {len(options)}.")
            continue

        if 1 <= choice <= len(options):
            return choice - 1

        print(f"  Enter a number between 1 and {len(options)}.")


def prompt_confirm(
    message: str,
    *,
    default: bool = True,
) -> bool:
    """Ask a yes/no question and return the answer.

    Parameters
    ----------
    message:
        The question text (e.g. "Proceed?").
    default:
        Value returned when the user presses Enter, or when non-interactive.
    """
    if not is_interactive():
        return default

    hint = "Y/n" if default else "y/N"
    try:
        raw = input(f"{message} [{hint}] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return default

    if not raw:
        return default
    return raw in ("y", "yes")


def prompt_text(
    message: str,
    *,
    default: str = "",
) -> str:
    """Prompt for free-text input with a default value.

    Parameters
    ----------
    message:
        The prompt label.
    default:
        Value returned when the user presses Enter, or when non-interactive.
    """
    if not is_interactive():
        return default

    try:
        raw = input(f"{message} [{default}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default

    return raw if raw else default
