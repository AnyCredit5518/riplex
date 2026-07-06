"""Interactive prompt utilities for riplex CLI.

All user-facing prompts (numbered lists, confirmations, free-text input) live
here.  Every function checks ``is_interactive()`` and returns the default
value silently when running in non-interactive mode (piped stdin, --auto flag,
or explicitly disabled).

Prompts are printed to **stdout**; diagnostic messages stay on stderr.
"""

from __future__ import annotations

import signal
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


def _input(prompt: str) -> str:
    """``input()`` that reliably raises ``KeyboardInterrupt`` on Ctrl-C.

    ``asyncio.run`` (Python 3.11+) installs a SIGINT handler that
    cooperatively cancels the running task instead of raising
    ``KeyboardInterrupt``. During a synchronous ``input()`` call inside
    an async flow that means the first Ctrl-C is swallowed: on Windows
    the console returns an empty read, so the caller silently sees a
    blank line and uses its default. Temporarily reinstalling
    ``signal.default_int_handler`` around the read makes SIGINT raise
    immediately, matching what the user expects at a prompt. Restored
    afterwards so asyncio's cancellation semantics still work while
    real async work is running.

    ``signal.signal`` is only valid from the main thread; the CLI is
    single-threaded so that is fine. In the unusual case where it's
    called off-thread (test runners, embedding) the swap is skipped
    and ``input()`` runs with whatever handler is active.
    """
    try:
        old = signal.signal(signal.SIGINT, signal.default_int_handler)
    except (ValueError, OSError):
        return input(prompt)
    try:
        return input(prompt)
    finally:
        signal.signal(signal.SIGINT, old)


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
            raw = _input(f"Choice [1-{len(options)}, default={default + 1}]: ").strip()
        except EOFError:
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
        raw = _input(f"{message} [{hint}] ").strip().lower()
    except EOFError:
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
        raw = _input(f"{message} [{default}]: ").strip()
    except EOFError:
        print()
        return default

    return raw if raw else default


def prompt_multi_select(
    header: str,
    options: list[str],
    *,
    defaults: list[int] | None = None,
) -> list[int] | None:
    """Show a numbered list and let the user select multiple items.

    Parameters
    ----------
    header:
        A short label printed above the list.
    options:
        Display strings for each option.
    defaults:
        0-based indices selected by default (returned in non-interactive mode).

    Returns
    -------
    list[int] | None
        The 0-based indices of the selected options, or None if cancelled.
    """
    if not options:
        return defaults

    if defaults is None:
        defaults = list(range(len(options)))

    if not is_interactive():
        return defaults

    print(f"\n{header}")
    for i, opt in enumerate(options):
        print(f"  {i + 1}. {opt}")

    print(f"\nEnter disc numbers separated by commas, 'all' for all, or 'none' to skip.")
    while True:
        try:
            raw = _input(f"Selection [default=all]: ").strip().lower()
        except EOFError:
            print()
            return defaults

        if not raw or raw == "all":
            return list(range(len(options)))

        if raw == "none":
            return []

        try:
            selected = [int(x.strip()) - 1 for x in raw.split(",")]
        except ValueError:
            print("  Enter numbers separated by commas (e.g. '1,3'), 'all', or 'none'.")
            continue

        if all(0 <= s < len(options) for s in selected):
            return selected

        print(f"  Numbers must be between 1 and {len(options)}.")


def _parse_index_spec(raw: str, valid: list[int]) -> list[int]:
    """Parse ``"3,5-7,9"`` into ``[3, 5, 6, 7, 9]``, validating against ``valid``."""
    valid_set = set(valid)
    result: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo_s, hi_s = part.split("-", 1)
            try:
                lo, hi = int(lo_s.strip()), int(hi_s.strip())
            except ValueError:
                raise ValueError(f"invalid range: {part!r}")
            if lo > hi:
                lo, hi = hi, lo
            for i in range(lo, hi + 1):
                if i in valid_set:
                    result.append(i)
        else:
            try:
                i = int(part)
            except ValueError:
                raise ValueError(f"invalid index: {part!r}")
            if i not in valid_set:
                raise ValueError(f"title #{i} does not exist on disc")
            result.append(i)
    if not result:
        raise ValueError("no valid indices provided")
    return result


def prompt_proceed_or_edit(message: str = "Proceed?") -> str:
    """Ask ``[Y]es / [n]o / [e]dit`` and return ``"yes"``, ``"no"`` or ``"edit"``.

    Non-interactive mode returns ``"yes"`` (matching the default of
    ``prompt_confirm``). EOF/Ctrl-C returns ``"no"``.
    """
    if not is_interactive():
        return "yes"
    try:
        raw = _input(f"{message} [Y/n/e(dit)] ").strip().lower()
    except EOFError:
        print()
        return "no"
    if not raw or raw in ("y", "yes"):
        return "yes"
    if raw in ("e", "edit"):
        return "edit"
    return "no"


def prompt_rip_selection(
    titles: list,
    default_indices: list[int],
    classifications: dict[int, str] | None = None,
) -> list[int] | None:
    """Interactive checkbox-style picker for makemkvcon titles.

    Renders a table with a ``[x]``/``[ ]`` prefix reflecting the current
    selection and loops until the user accepts (``done``/Enter),
    cancels (``cancel``), or clears everything. Accepted commands per line:

    * ``3,5-7`` — toggle these title indices
    * ``all`` — select every title on the disc
    * ``none`` — deselect everything
    * ``default`` — restore the analyzer's recommendation
    * ``done`` / Enter — accept the current selection
    * ``cancel`` — abort the edit (returns ``None``)

    Non-interactive mode returns ``default_indices`` unchanged.
    """
    from riplex.disc.analysis import format_seconds

    if not titles:
        return list(default_indices)
    if not is_interactive():
        return list(default_indices)

    classifications = classifications or {}
    all_indices = [t.index for t in titles]
    default_set = set(default_indices)
    selected: set[int] = set(default_indices)

    while True:
        print()
        print(f"  {'':<3}  {'#':>3}  {'Duration':>9}  {'Size':>8}  {'Recommendation'}")
        print(f"  {'':-<3}  {'':->3}  {'':->9}  {'':->8}  {'':->40}")
        for t in titles:
            mark = "[x]" if t.index in selected else "[ ]"
            dur = format_seconds(t.duration_seconds)
            size = f"{t.size_bytes / (1024 ** 3):.1f} GB"
            label = classifications.get(t.index, "")
            print(f"  {mark:<3}  {t.index:>3}  {dur:>9}  {size:>8}  {label}")

        total_size_gb = sum(
            t.size_bytes for t in titles if t.index in selected
        ) / (1024 ** 3)
        print(f"\n  Selected: {len(selected)} title(s) ({total_size_gb:.1f} GB)")
        print(
            "\n  Commands: <indices> to toggle (e.g. '3,5-7'), "
            "'all', 'none', 'default',\n"
            "            Enter or 'done' to accept, 'cancel' to abort."
        )
        try:
            raw = _input("  Selection: ").strip().lower()
        except EOFError:
            print()
            return None

        if not raw or raw == "done":
            return sorted(selected)
        if raw == "cancel":
            return None
        if raw == "all":
            selected = set(all_indices)
            continue
        if raw == "none":
            selected = set()
            continue
        if raw == "default":
            selected = set(default_set)
            continue

        try:
            toggles = _parse_index_spec(raw, all_indices)
        except ValueError as exc:
            print(f"  {exc}")
            continue
        for idx in toggles:
            if idx in selected:
                selected.discard(idx)
            else:
                selected.add(idx)
