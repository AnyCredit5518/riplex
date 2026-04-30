"""CLI entry point for plex-planner."""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import shutil
import sys
import tempfile
from pathlib import Path

from plex_planner import __version__
from plex_planner.config import get_api_key, get_archive_root, get_output_root, get_rip_output
from plex_planner.dedup import find_all_redundant, find_duplicates, remove_duplicates
from plex_planner.detect import detect_format, detect_incomplete, group_title_folders
from plex_planner.disc_provider import _convert_film, lookup_discs
from plex_planner.matcher import (
    collect_disc_targets,
    map_folders_to_discs,
    match_discs,
)
from plex_planner.metadata_sources.tmdb import TmdbProvider
from plex_planner.models import PlannedMovie, SearchRequest
from plex_planner.organizer import build_organize_plan, execute_plan
from plex_planner.planner import plan
from plex_planner.scanner import scan_folder
from plex_planner.snapshot import capture as snapshot_capture, load as snapshot_load, save_from_scanned as snapshot_save_from_scanned
from plex_planner.ui import is_interactive, prompt_choice, prompt_confirm, prompt_text, set_auto_mode

log = logging.getLogger(__name__)

_LOG_DIR = Path(tempfile.gettempdir()) / "plex-planner"

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


def _random_bar_style() -> dict[str, str]:
    """Pick a random progress bar style for visual variety."""
    import random
    return random.choice(_BAR_STYLES)


def _build_execute_command() -> str:
    """Reconstruct the current CLI invocation with ``--execute`` appended.

    Strips any ``--dry-run`` / ``-n`` flags and quotes arguments that
    contain spaces so the result is safe to copy/paste.
    """
    raw = sys.argv[:]
    # Remove --dry-run / -n (backwards-compat flag on rip)
    cleaned = [a for a in raw if a not in ("--dry-run", "-n")]
    # Don't double-add --execute
    if "--execute" not in cleaned:
        cleaned.append("--execute")
    # Replace full exe path with just the basename
    if cleaned:
        cleaned[0] = Path(cleaned[0]).stem
    parts = [f'"{a}"' if " " in a else a for a in cleaned]
    return " ".join(parts)


def _dry_run_banner(verb: str) -> str:
    """Return the banner printed at the start of a dry-run."""
    return f"--- DRY RUN (pass --execute to {verb}) ---"


def _execute_hint(subcommand: str) -> str:
    """Return the end-of-run hint with a copy-pasteable command."""
    verb = "apply these changes" if subcommand == "organize" else "rip"
    return f"Re-run with --execute to {verb}:\n  {_build_execute_command()}"


def _setup_logging(verbose: bool = False) -> Path:
    """Configure file-based debug logging for the entire package.

    Always writes DEBUG-level output to a log file in the temp directory.
    When *verbose* is True, also prints DEBUG messages to stderr.

    Returns the path to the log file.
    """
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = _LOG_DIR / "plex-planner.log"

    root = logging.getLogger("plex_planner")
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


_TRAILING_YEAR_RE = re.compile(r"\s*\(\d{4}\)\s*$")
_TRAILING_DISC_RE = re.compile(
    r"\s*[-_]?\s*(?:D(?:isc)?\s*\d+)\s*$", re.IGNORECASE,
)


def _infer_title_from_scanned(scanned: list) -> str | None:
    """Derive a clean title from MKV title_tag metadata.

    Picks the title_tag of the longest file (most likely the main feature).
    Returns ``None`` when no useful title_tag is present.
    """
    all_files = [f for d in scanned for f in d.files]
    if not all_files:
        return None
    longest = max(all_files, key=lambda f: f.duration_seconds)
    tag = longest.title_tag
    if not tag or not tag.strip():
        return None
    # Strip trailing disc label (e.g. "SEVEN WORLDS ONE PLANET D1")
    clean = _TRAILING_DISC_RE.sub("", tag.strip())
    # Strip trailing year if embedded, e.g. "Waterworld (1995)"
    clean, _ = _strip_year_from_title(clean)
    return clean or None


def _strip_year_from_title(name: str) -> tuple[str, int | None]:
    """Strip a trailing ``(YYYY)`` from a folder name.

    Returns ``(clean_title, year)`` where *year* is the extracted value
    or ``None`` if no trailing year was found.
    """
    m = _TRAILING_YEAR_RE.search(name)
    if m:
        year = int(m.group().strip().strip("()"))
        return name[: m.start()].strip(), year
    return name, None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plex-planner",
        description=(
            "Rip physical discs and organize MKV files into "
            "Plex-compatible folder structures."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}",
    )
    subs = parser.add_subparsers(dest="command")

    # --- organize ---
    org_parser = subs.add_parser(
        "organize",
        help="Scan a MakeMKV rip folder and organize into Plex structure.",
    )
    org_parser.add_argument("folder", help="Path to a MakeMKV rip folder.")
    org_parser.add_argument("--title", help="Override title (default: folder name).")
    org_parser.add_argument("--year", type=int, help="Release year.")
    org_parser.add_argument(
        "--type",
        dest="media_type",
        choices=["movie", "tv", "auto"],
        default="auto",
        help="Force media type. Default: auto-detect.",
    )
    org_parser.add_argument(
        "--format",
        dest="disc_format",
        default=None,
        help="Disc format filter for dvdcompare (e.g. 'Blu-ray 4K').",
    )
    org_parser.add_argument(
        "--release",
        default=None,
        help="Regional release: 1-based index or name keyword (default: auto-detect).",
    )
    org_parser.add_argument(
        "--output",
        default=None,
        help="Output root directory (or set PLEX_ROOT env var, or output_root in config).",
    )
    org_parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Actually move files (default: dry-run preview only).",
    )
    org_parser.add_argument("--json", action="store_true", default=False)
    org_parser.add_argument("--api-key", default=None)
    org_parser.add_argument(
        "--unmatched",
        choices=["ignore", "move", "delete", "extras"],
        default="ignore",
        help="Policy for files that can't be matched: ignore (default), move to _Unmatched folder, delete, or extras (route to Other/ folder).",
    )
    org_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Print debug logging to stderr in addition to the log file.",
    )
    org_parser.add_argument(
        "--no-cache",
        action="store_true",
        default=False,
        help="Bypass the local cache and fetch fresh data from APIs.",
    )
    org_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Re-organize files even if they are already tagged as organized.",
    )
    org_parser.add_argument(
        "--snapshot",
        default=None,
        help="Load a snapshot JSON file instead of scanning a real folder. Forces dry-run mode.",
    )
    org_parser.add_argument(
        "--auto",
        action="store_true",
        default=False,
        help="Skip interactive prompts, use best-guess defaults.",
    )

    # --- lookup ---
    guide_parser = subs.add_parser(
        "lookup",
        help="Look up disc contents and metadata for a title from TMDb and dvdcompare.",
    )
    guide_parser.add_argument("title", help="Movie or TV show title.")
    guide_parser.add_argument("--year", type=int, help="Release year.")
    guide_parser.add_argument(
        "--type",
        dest="media_type",
        choices=["movie", "tv", "auto"],
        default="auto",
        help="Force media type. Default: auto-detect.",
    )
    guide_parser.add_argument(
        "--format",
        dest="disc_format",
        default=None,
        help="Disc format filter for dvdcompare (e.g. 'Blu-ray 4K').",
    )
    guide_parser.add_argument(
        "--release",
        default="america",
        help="Regional release: 1-based index or name keyword (default: america).",
    )
    guide_parser.add_argument(
        "--output",
        default=None,
        help="Output root for --create-folders (or set PLEX_ROOT env var, or config).",
    )
    guide_parser.add_argument(
        "--create-folders",
        action="store_true",
        default=False,
        help="Pre-create the recommended MakeMKV rip folder structure.",
    )
    guide_parser.add_argument("--json", action="store_true", default=False)
    guide_parser.add_argument("--api-key", default=None)
    guide_parser.add_argument(
        "--drive",
        default=None,
        help="Read live disc info from a drive via makemkvcon. "
             "Pass a drive index (e.g. 0), device name (e.g. D:), or 'auto' "
             "to use the first drive with a disc inserted.",
    )
    guide_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Print debug logging to stderr in addition to the log file.",
    )
    guide_parser.add_argument(
        "--no-cache",
        action="store_true",
        default=False,
        help="Bypass the local cache and fetch fresh data from APIs.",
    )
    guide_parser.add_argument(
        "--no-specials",
        action="store_true",
        default=False,
        help="Exclude specials (Season 00) for TV shows.",
    )
    guide_parser.add_argument(
        "--no-extras",
        action="store_true",
        default=False,
        help="Omit recommended extras folder skeleton.",
    )

    # --- rip ---
    rip_parser = subs.add_parser(
        "rip",
        help="Read a disc, recommend titles, and rip via makemkvcon.",
    )
    rip_parser.add_argument(
        "title", nargs="?", default=None,
        help="Movie or TV show title (auto-detected from volume label if omitted).",
    )
    rip_parser.add_argument(
        "--drive",
        default="auto",
        help="Drive index (e.g. 0), device name (e.g. D:), or 'auto' (default: auto).",
    )
    rip_parser.add_argument("--year", type=int, help="Release year.")
    rip_parser.add_argument(
        "--type", dest="media_type", choices=["movie", "tv", "auto"],
        default="auto",
    )
    rip_parser.add_argument(
        "--format", dest="disc_format", default=None,
        help="Disc format filter for dvdcompare (auto-detected from disc resolution if omitted).",
    )
    rip_parser.add_argument(
        "--release", default=None,
        help="Regional release: 1-based index or name keyword (default: auto-detect).",
    )
    rip_parser.add_argument(
        "--output", default=None,
        help="Output root directory (or set PLEX_ROOT env var, or config).",
    )
    rip_parser.add_argument(
        "--titles", default=None,
        help="Comma-separated title indices to rip (overrides auto-recommendation).",
    )
    rip_parser.add_argument(
        "--all", dest="rip_all", action="store_true", default=False,
        help="Rip all titles (skip recommendation filter).",
    )
    rip_parser.add_argument(
        "--yes", "-y", action="store_true", default=False,
        help="Skip confirmation prompt.",
    )
    rip_parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Actually rip (default: dry-run preview only).",
    )
    rip_parser.add_argument(
        "--dry-run", "-n", action="store_true", default=False,
        help=argparse.SUPPRESS,  # kept for backwards compat; dry-run is now default
    )
    rip_parser.add_argument(
        "--organize", dest="auto_organize", action="store_true", default=False,
        help="Automatically run organize after ripping.",
    )
    rip_parser.add_argument("--json", action="store_true", default=False)
    rip_parser.add_argument("--api-key", default=None)
    rip_parser.add_argument(
        "--verbose", "-v", action="store_true", default=False,
    )
    rip_parser.add_argument(
        "--no-cache", action="store_true", default=False,
    )
    rip_parser.add_argument(
        "--auto",
        action="store_true",
        default=False,
        help="Skip interactive prompts, use best-guess defaults.",
    )

    # --- orchestrate ---
    orch_parser = subs.add_parser(
        "orchestrate",
        help="Multi-disc rip and organize pipeline.",
    )
    orch_parser.add_argument(
        "--title", default=None,
        help="Movie or TV show title (auto-detected from volume label if omitted).",
    )
    orch_parser.add_argument(
        "--drive",
        default="auto",
        help="Drive index (e.g. 0), device name (e.g. D:), or 'auto' (default: auto).",
    )
    orch_parser.add_argument("--year", type=int, help="Release year.")
    orch_parser.add_argument(
        "--type", dest="media_type", choices=["movie", "tv", "auto"],
        default="auto",
    )
    orch_parser.add_argument(
        "--format", dest="disc_format", default=None,
        help="Disc format filter for dvdcompare (auto-detected from disc resolution if omitted).",
    )
    orch_parser.add_argument(
        "--release", default=None,
        help="Regional release: 1-based index or name keyword (default: auto-detect).",
    )
    orch_parser.add_argument(
        "--output", default=None,
        help="Output root directory (or set PLEX_ROOT env var, or config).",
    )
    orch_parser.add_argument(
        "--yes", "-y", action="store_true", default=False,
        help="Skip confirmation prompts.",
    )
    orch_parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Actually rip and organize (default: dry-run preview only).",
    )
    orch_parser.add_argument(
        "--unmatched",
        choices=["ignore", "move", "delete", "extras"],
        default="extras",
        help="Policy for unmatched files during organize (default: extras).",
    )
    orch_parser.add_argument("--json", action="store_true", default=False)
    orch_parser.add_argument("--api-key", default=None)
    orch_parser.add_argument(
        "--verbose", "-v", action="store_true", default=False,
    )
    orch_parser.add_argument(
        "--no-cache", action="store_true", default=False,
    )
    orch_parser.add_argument(
        "--auto",
        action="store_true",
        default=False,
        help="Skip interactive prompts, use best-guess defaults.",
    )
    orch_parser.add_argument(
        "--discs", default=None,
        help="Comma-separated disc numbers to rip (e.g. '1,3'). Skips others.",
    )
    orch_parser.add_argument(
        "--snapshot",
        action="store_true",
        default=False,
        help="Scan disc and write manifest without ripping. Useful to regenerate manifests for already-ripped files.",
    )

    return parser



async def _run(args: argparse.Namespace) -> int:
    if args.command == "organize":
        return await _run_organize(args)
    if args.command == "lookup":
        return await _run_lookup(args)
    if args.command == "rip":
        return await _run_rip(args)
    if args.command == "orchestrate":
        return await _run_orchestrate(args)
    # Unknown or missing command
    return 1


async def _run_lookup(args: argparse.Namespace) -> int:
    """Look up disc contents and metadata for a title from TMDb and dvdcompare."""
    log_file = _setup_logging(verbose=getattr(args, "verbose", False))
    log.info("plex-planner lookup: args=%s", vars(args))
    print(f"Debug log: {log_file}", file=sys.stderr)

    if getattr(args, "no_cache", False):
        from plex_planner import cache
        cache.disable()

    api_key = get_api_key(getattr(args, "api_key", None))
    try:
        provider = TmdbProvider(api_key=api_key)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        request = SearchRequest(
            title=args.title,
            year=getattr(args, "year", None),
            media_type=getattr(args, "media_type", "auto"),
            include_specials=not getattr(args, "no_specials", False),
            include_extras_skeleton=not getattr(args, "no_extras", False),
        )
        result = await plan(request, provider)
    except LookupError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error fetching TMDb metadata: {exc}", file=sys.stderr)
        return 1
    finally:
        await provider.close()

    canonical = result.canonical_title
    year = result.year
    is_movie = isinstance(result, PlannedMovie)
    movie_runtime = result.runtime_seconds if is_movie else None

    # Look up dvdcompare disc metadata
    disc_format = getattr(args, "disc_format", None)
    release = getattr(args, "release", "america")
    dvdcompare_title = canonical
    print("Looking up disc metadata on dvdcompare.net ...", file=sys.stderr)
    discs: list = []
    try:
        discs = await lookup_discs(dvdcompare_title, disc_format=disc_format, release=release)
    except LookupError:
        print("Warning: no dvdcompare data found. Guide will be limited to TMDb info.", file=sys.stderr)
    except Exception as exc:
        print(f"Warning: dvdcompare lookup failed ({type(exc).__name__}). Guide will be limited to TMDb info.", file=sys.stderr)

    # Live disc analysis via makemkvcon (run before output so JSON can include it)
    drive_arg = getattr(args, "drive", None)
    disc_info = None
    if drive_arg is not None:
        from plex_planner.makemkv import (
            DiscInfo,
            find_makemkvcon,
            run_disc_info,
            run_drive_list,
        )

        exe = find_makemkvcon()
        if not exe:
            print("\nError: makemkvcon not found. Install MakeMKV or ensure makemkvcon is on PATH.", file=sys.stderr)
            return 1

        if drive_arg == "auto":
            print("Scanning drives ...", file=sys.stderr)
            drives = run_drive_list(exe)
            active = [d for d in drives if d.has_disc]
            if not active:
                print("Error: no disc found in any drive.", file=sys.stderr)
                return 1
            print(f"Found disc in drive {active[0].index}: {active[0].disc_label} ({active[0].device})", file=sys.stderr)
            drive_idx = active[0].index
        else:
            try:
                drive_idx = int(drive_arg)
            except ValueError:
                drive_idx = drive_arg  # device name like "D:"

        print(f"Reading disc info from drive {drive_idx} ...", file=sys.stderr)
        try:
            disc_info = run_disc_info(drive_idx, exe)
        except (RuntimeError, FileNotFoundError) as exc:
            print(f"Error reading disc: {exc}", file=sys.stderr)
            return 1

    if getattr(args, "json", False):
        print(_rip_guide_json(canonical, year, is_movie, movie_runtime, discs, disc_info))
        return 0

    _print_rip_guide(canonical, year, is_movie, movie_runtime, discs)

    if disc_info is not None:
        _print_disc_analysis(disc_info, discs, is_movie, movie_runtime)

    # Optionally create folders
    if getattr(args, "create_folders", False) and discs:
        output_val = get_output_root(getattr(args, "output", None))
        if not output_val:
            print("Error: --output or output_root config required for --create-folders.", file=sys.stderr)
            return 1
        rip_output = get_rip_output()
        makemkv_root = Path(rip_output) / f"{canonical} ({year})" if rip_output else Path(output_val) / "Rips" / f"{canonical} ({year})"
        created = _create_rip_folders(makemkv_root, discs)
        if created:
            print(f"\nCreated {len(created)} folder(s) under {makemkv_root}")
            for p in created:
                print(f"  {p}")

    return 0



def _disc_role(disc, is_movie: bool) -> str:
    """Return a short role label for a disc in the folder listing."""
    if disc.is_film:
        return " (main film)"
    if is_movie:
        # For movies, episodes on non-film discs are play-all bonus groups
        if disc.extras or disc.episodes:
            return " (extras)"
        return ""
    # TV show
    if disc.episodes and not disc.extras:
        return " (episodes)"
    if disc.extras and not disc.episodes:
        return " (extras)"
    if disc.episodes and disc.extras:
        return " (episodes + extras)"
    return ""


def _print_rip_guide(
    canonical: str,
    year: int,
    is_movie: bool,
    movie_runtime: int | None,
    discs: list,
) -> None:
    """Print a human-readable rip guide to stdout."""
    media_label = "Movie" if is_movie else "TV Show"
    print(f"\n{canonical} ({year}) [{media_label}]")
    print("=" * 60)

    # Recommended folder structure
    print(f"\nRecommended rip folder structure:")
    folder_base = f"{canonical} ({year})"
    if discs:
        for disc in discs:
            label = f"Disc {disc.number}"
            fmt_str = f" [{disc.disc_format}]" if disc.disc_format else ""
            role = _disc_role(disc, is_movie)
            print(f"  Rips/{folder_base}/{label}/{fmt_str}{role}")
    else:
        print(f"  Rips/{folder_base}/")

    if not discs:
        print("\nNo dvdcompare disc data available.")
        if movie_runtime:
            print(f"Main feature runtime: {_format_seconds(movie_runtime)}")
        print("Tip: rip all titles and use 'plex-planner organize' to sort them.")
        return

    # Per-disc breakdown
    print(f"\nDisc contents ({len(discs)} disc(s)):")
    print("-" * 60)

    play_all_tips: list[str] = []

    for disc in discs:
        fmt_str = f" [{disc.disc_format}]" if disc.disc_format else ""
        role_tag = " ** MAIN FILM **" if disc.is_film else ""
        print(f"\n  Disc {disc.number}{fmt_str}{role_tag}")

        if disc.is_film and movie_runtime:
            print(f"    The Film: {_format_seconds(movie_runtime)}")

        items = disc.episodes + disc.extras

        if not items and disc.is_film:
            continue

        has_episodes = bool(disc.episodes)
        has_extras = bool(disc.extras)

        # For movies, "episodes" on a non-film disc are really play-all
        # bonus feature groups (dvdcompare models them as children).
        episodes_are_extras = is_movie and has_episodes and not disc.is_film

        if has_episodes and not episodes_are_extras:
            total_ep_runtime = sum(e.runtime_seconds for e in disc.episodes)
            print(f"    Episodes ({len(disc.episodes)}, total {_format_seconds(total_ep_runtime)}):")
            for ep in disc.episodes:
                rt = _format_seconds(ep.runtime_seconds) if ep.runtime_seconds else "?"
                print(f"      {ep.title} ({rt})")
            play_all_tips.append(
                f"Disc {disc.number}: has {len(disc.episodes)} episodes "
                f"(total {_format_seconds(total_ep_runtime)}). "
                f"If MakeMKV shows a single title with {len(disc.episodes)} "
                f"or more chapters totaling ~{_format_seconds(total_ep_runtime)}, "
                f"that is the play-all. You can rip just that one title; "
                f"plex-planner will split it by chapters."
            )
        elif episodes_are_extras:
            total_ep_runtime = sum(e.runtime_seconds for e in disc.episodes)
            print(f"    Extras - play-all group ({len(disc.episodes)} items, total {_format_seconds(total_ep_runtime)}):")
            for ep in disc.episodes:
                rt = _format_seconds(ep.runtime_seconds) if ep.runtime_seconds else "?"
                print(f"      {ep.title} ({rt})")

        if has_extras:
            total_extra_runtime = sum(e.runtime_seconds for e in disc.extras)
            print(f"    Extras ({len(disc.extras)}, total {_format_seconds(total_extra_runtime)}):")
            for extra in disc.extras:
                rt = _format_seconds(extra.runtime_seconds) if extra.runtime_seconds else "?"
                ftype = f" [{extra.feature_type}]" if extra.feature_type else ""
                print(f"      {extra.title} ({rt}){ftype}")

    # Summary and tips
    total_features = sum(len(d.episodes) + len(d.extras) for d in discs)
    film_discs = [d for d in discs if d.is_film]
    extras_discs = [d for d in discs if not d.is_film and (d.extras or d.episodes)]

    print(f"\n{'=' * 60}")
    print("Rip tips:")

    if film_discs:
        film_nums = ", ".join(str(d.number) for d in film_discs)
        print(f"  - Main film is on disc {film_nums}.")

    if play_all_tips:
        for tip in play_all_tips:
            print(f"  - {tip}")

    if extras_discs:
        nums = ", ".join(str(d.number) for d in extras_discs)
        print(f"  - Extras are on disc {nums}. Rip all titles from extras discs;")
        print(f"    plex-planner will match each by runtime to its dvdcompare entry.")

    if total_features > 0:
        print(f"  - {total_features} total feature(s) across {len(discs)} disc(s).")

    print(f"  - After ripping, run: plex-planner organize \"{folder_base}\"")


def _rip_guide_json(
    canonical: str,
    year: int,
    is_movie: bool,
    movie_runtime: int | None,
    discs: list,
    disc_info=None,
) -> str:
    """Return JSON representation of the rip guide."""
    import json
    import dataclasses

    data: dict = {
        "title": canonical,
        "year": year,
        "media_type": "movie" if is_movie else "tv",
        "movie_runtime_seconds": movie_runtime,
        "recommended_folder": f"{canonical} ({year})",
        "discs": [dataclasses.asdict(d) for d in discs],
    }

    if disc_info is not None:
        dvd_entries, total_episode_runtime, episode_count = build_dvd_entries(discs)

        titles_json = []
        for t in disc_info.titles:
            recommendation = classify_title(
                t, disc_info.titles, dvd_entries,
                is_movie, movie_runtime,
                total_episode_runtime, episode_count,
            )
            skip = is_skip_title(
                t, disc_info.titles, is_movie, movie_runtime,
                total_episode_runtime, episode_count,
            )
            titles_json.append({
                "index": t.index,
                "name": t.name,
                "duration_seconds": t.duration_seconds,
                "chapters": t.chapters,
                "size_bytes": t.size_bytes,
                "filename": t.filename,
                "playlist": t.playlist,
                "resolution": t.resolution,
                "video_codec": t.video_codec,
                "audio_tracks": t.audio_tracks,
                "segment_count": t.segment_count,
                "segment_map": t.segment_map,
                "recommendation": recommendation,
                "skip": skip,
            })
        data["disc_analysis"] = {
            "disc_name": disc_info.disc_name,
            "disc_type": disc_info.disc_type,
            "titles": titles_json,
        }

    return json.dumps(data, indent=2)


def _create_rip_folders(makemkv_root: Path, discs: list) -> list[Path]:
    """Create the recommended disc subfolder structure.

    Returns list of created directories.
    """
    created: list[Path] = []
    for disc in discs:
        folder = makemkv_root / f"Disc {disc.number}"
        if not folder.exists():
            folder.mkdir(parents=True, exist_ok=True)
            created.append(folder)
    return created


# Disc analysis functions are in disc_analysis.py; import for use here.
from plex_planner.disc_analysis import (  # noqa: E402
    build_dvd_entries,
    classify_title,
    find_duration_match,
    format_seconds as _format_seconds,
    is_skip_title,
    print_disc_analysis as _print_disc_analysis,
)


def _parse_volume_label(label: str) -> str | None:
    """Extract a human-readable title from a disc volume label.

    Examples:
        "FROZEN_PLANET_II_D2" -> "Frozen Planet II"
        "PLANET_EARTH_III-Disc3" -> "Planet Earth III"
        "BLADE_RUNNER_2049" -> "Blade Runner 2049"
        "TGUN2" -> None (too short/ambiguous)
    """
    if not label or len(label) < 2:
        return None

    # Strip disc number suffix including its leading separator.
    # Matches: "_D2", "-Disc3", " - Disc 1", "_Disc_1"
    # Won't match titles with dashes like "Spider-Man" or "X-Men".
    cleaned = re.sub(r"[\s_-]+D(?:isc[\s_]*)?\d+\s*$", "", label, flags=re.IGNORECASE)

    # Replace underscores with spaces
    cleaned = cleaned.replace("_", " ").strip()

    if len(cleaned) < 2:
        return None

    # Title-case, preserving roman numerals
    words = cleaned.split()
    result = []
    for w in words:
        if re.fullmatch(r"[IVXLCDM]+", w, re.IGNORECASE):
            result.append(w.upper())
        else:
            result.append(w.capitalize())
    return " ".join(result)


def _detect_disc_format(disc_info) -> str | None:
    """Auto-detect dvdcompare format string from disc title resolutions.

    Returns "Blu-ray 4K" if any title is 3840-wide, else "Blu-ray".
    """
    if not disc_info.titles:
        return None
    for t in disc_info.titles:
        if t.resolution and "3840" in t.resolution:
            return "Blu-ray 4K"
    return "Blu-ray"


def _infer_media_type(disc_info) -> str:
    """Infer 'movie' or 'tv' from disc title structure.

    Heuristic: if a disc has 2+ non-play-all titles with durations
    between 15 and 75 minutes, it's likely a TV disc. A single long
    title (75+ minutes) suggests a movie disc.

    Returns "movie", "tv", or "auto" if ambiguous.
    """
    if not disc_info.titles:
        return "auto"

    # Identify candidate episode titles: substantial duration, low segment count
    candidates = [
        t for t in disc_info.titles
        if t.duration_seconds >= 900  # 15+ minutes
        and t.segment_count <= 1      # not a play-all
    ]

    if not candidates:
        return "auto"

    episode_length = [t for t in candidates if t.duration_seconds < 4500]  # < 75 min
    movie_length = [t for t in candidates if t.duration_seconds >= 4500]   # >= 75 min

    if len(episode_length) >= 2 and len(movie_length) == 0:
        return "tv"
    if len(movie_length) == 1 and len(episode_length) == 0:
        return "movie"

    return "auto"


def _select_dvdcompare_release(
    film,
    disc_info=None,
    preferred: str | None = None,
) -> tuple[list, str]:
    """Select the best dvdcompare release for a disc.

    Selection strategy:
    1. If *preferred* keyword given, keyword-match against release names.
       Error + exit if not found.
    2. If no *preferred*, try duration matching against *disc_info* (rip only).
    3. Fall back to first release.
    4. Reorder releases so the recommended one is first.
    5. If interactive and >1 release, let the user pick from the list.

    Returns (PlannedDisc list, release_name) or ([], "").
    """
    from dvdcompare.cli import select_releases

    if not film.releases:
        return [], ""

    # --- determine recommended release index ---
    rec_idx = 0  # 0-based index into film.releases

    if preferred:
        # Keyword match against release names
        try:
            selected = select_releases(film.releases, preferred)
            rec_idx = next(
                i for i, r in enumerate(film.releases) if r is selected[0]
            )
        except (LookupError, StopIteration):
            print(f"Error: no release matching '{preferred}'.", file=sys.stderr)
            print("Available releases:", file=sys.stderr)
            for i, r in enumerate(film.releases, 1):
                print(f"  {i}. {r.name}", file=sys.stderr)
            sys.exit(1)
    elif disc_info and disc_info.titles:
        # Duration matching (rip only)
        live_durations = sorted(
            [t.duration_seconds for t in disc_info.titles if t.duration_seconds > 120],
            reverse=True,
        )
        if live_durations:
            best_idx = None
            best_score = -1

            for rel_idx, rel in enumerate(film.releases):
                ep_durations = sorted(
                    [f.runtime_seconds for d in rel.discs for f in d.features
                     if f.runtime_seconds and f.runtime_seconds > 120],
                    reverse=True,
                )
                if not ep_durations:
                    continue

                matched = 0
                used = set()
                for live_dur in live_durations:
                    for i, ep_dur in enumerate(ep_durations):
                        if i not in used and abs(live_dur - ep_dur) < 60:
                            matched += 1
                            used.add(i)
                            break

                score = matched / len(ep_durations)
                if score > best_score:
                    best_score = score
                    best_idx = rel_idx

            if best_idx is not None and best_score >= 0.3:
                rec_idx = best_idx

    # --- reorder releases so recommended is first ---
    releases = [film.releases[rec_idx]] + [
        r for i, r in enumerate(film.releases) if i != rec_idx
    ]

    # --- interactive selection (skip if preferred already resolved) ---
    if is_interactive() and len(releases) > 1 and not preferred:
        options = []
        for rel in releases:
            disc_count = len(rel.discs) if rel.discs else 0
            disc_word = "disc" if disc_count == 1 else "discs"
            options.append(f"{rel.name} [{disc_count} {disc_word}]")
        chosen_idx = prompt_choice(
            "Select a dvdcompare release:", options, default=0,
        )
    else:
        chosen_idx = 0

    # --- convert chosen release ---
    chosen_release = releases[chosen_idx]
    # Find the 1-based index in the original film.releases for _convert_film
    orig_idx = next(i for i, r in enumerate(film.releases) if r is chosen_release)
    discs = _convert_film(film, str(orig_idx + 1))
    return discs, chosen_release.name


def _detect_disc_number(
    disc_info,
    dvdcompare_discs: list,
) -> int | None:
    """Auto-detect which dvdcompare disc number the physical disc corresponds to.

    Tries two strategies:
    1. Parse the volume label for a disc number (e.g. "FROZEN_PLANET_II_D2" -> 2)
    2. Match live title durations against each dvdcompare disc's episodes.

    Returns the disc number (1-based) or None if detection fails.
    """
    # Strategy 1: volume label
    label = disc_info.disc_name or ""
    match = re.search(r"[_\s-]D(?:isc\s*)?(\d+)\b", label, re.IGNORECASE)
    if match:
        return int(match.group(1))

    # Strategy 2: duration matching against dvdcompare discs
    if not dvdcompare_discs or not disc_info.titles:
        return None

    # Collect substantial title durations from the live disc
    live_durations = sorted(
        [t.duration_seconds for t in disc_info.titles if t.duration_seconds > 120],
        reverse=True,
    )
    if not live_durations:
        return None

    best_disc = None
    best_score = -1

    for disc in dvdcompare_discs:
        ep_durations = sorted(
            [ep.runtime_seconds for ep in disc.episodes if ep.runtime_seconds > 0],
            reverse=True,
        )
        if not ep_durations:
            continue

        # Count how many live titles match an episode within 60 seconds
        matched = 0
        used = set()
        for live_dur in live_durations:
            for i, ep_dur in enumerate(ep_durations):
                if i not in used and abs(live_dur - ep_dur) < 60:
                    matched += 1
                    used.add(i)
                    break

        # Score: fraction of episodes matched
        score = matched / len(ep_durations) if ep_durations else 0
        if score > best_score:
            best_score = score
            best_disc = disc.number

    # Require at least 50% of episodes to match
    if best_score >= 0.5:
        return best_disc

    # Strategy 3: for movies, match by disc format/resolution
    # If the live disc has 4K content and only one dvdcompare disc is 4K, that's our match
    live_resolutions = {t.resolution for t in disc_info.titles if t.resolution}
    has_4k = any("2160" in r for r in live_resolutions)
    has_1080 = any("1080" in r for r in live_resolutions)

    format_candidates = []
    for disc in dvdcompare_discs:
        fmt = (getattr(disc, "disc_format", "") or "").lower()
        if has_4k and ("4k" in fmt or "uhd" in fmt):
            format_candidates.append(disc.number)
        elif has_1080 and not has_4k and "4k" not in fmt and "uhd" not in fmt and "blu" in fmt:
            format_candidates.append(disc.number)

    if len(format_candidates) == 1:
        return format_candidates[0]

    return None


async def _run_rip(args: argparse.Namespace) -> int:
    """Read a disc, show analysis, and rip recommended titles."""
    import json as json_mod
    import time

    from plex_planner.makemkv import (
        find_makemkvcon,
        run_disc_info,
        run_drive_list,
        run_rip,
    )

    log_file = _setup_logging(verbose=getattr(args, "verbose", False))
    log.info("plex-planner rip: args=%s", vars(args))
    print(f"Debug log: {log_file}", file=sys.stderr)

    dry_run = not getattr(args, "execute", False)
    if dry_run:
        print(f"\n{_dry_run_banner('rip')}\n")
    else:
        print("\n--- EXECUTING ---\n")

    if getattr(args, "no_cache", False):
        from plex_planner import cache
        cache.disable()

    # Find makemkvcon
    exe = find_makemkvcon()
    if not exe:
        print("Error: makemkvcon not found. Install MakeMKV or ensure makemkvcon is on PATH.", file=sys.stderr)
        return 1

    # Resolve drive
    drive_arg = getattr(args, "drive", "auto") or "auto"
    if drive_arg == "auto":
        print("Scanning drives ...", file=sys.stderr)
        drives = run_drive_list(exe)
        active = [d for d in drives if d.has_disc]
        if not active:
            print("Error: no disc found in any drive.", file=sys.stderr)
            return 1
        print(f"Found disc in drive {active[0].index}: {active[0].disc_label} ({active[0].device})", file=sys.stderr)
        drive_idx = active[0].index
        volume_label = active[0].disc_label
    else:
        try:
            drive_idx = int(drive_arg)
        except ValueError:
            drive_idx = drive_arg
        volume_label = None

    # Read disc info
    print("Reading disc info ...", file=sys.stderr)
    try:
        disc_info = run_disc_info(drive_idx, exe)
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"Error reading disc: {exc}", file=sys.stderr)
        return 1

    if not disc_info.titles:
        print("Error: no titles found on disc.", file=sys.stderr)
        return 1

    # If drive wasn't auto, get label from disc_info
    if volume_label is None:
        volume_label = disc_info.disc_name or ""

    # Auto-detect title from volume label if not provided
    title_arg = getattr(args, "title", None)
    if not title_arg:
        title_arg = _parse_volume_label(volume_label)
        if title_arg:
            print(f"Auto-detected title from volume label: {title_arg}", file=sys.stderr)
            title_arg = prompt_text("Title", default=title_arg)
        else:
            print("Error: could not detect title from volume label. Provide a title argument.", file=sys.stderr)
            return 1

    # Auto-detect disc format from resolution if not provided
    disc_format = getattr(args, "disc_format", None)
    if not disc_format:
        disc_format = _detect_disc_format(disc_info)
        if disc_format:
            log.info("Auto-detected disc format: %s", disc_format)

    # Infer media type from disc structure if not specified
    media_type_arg = getattr(args, "media_type", "auto")
    if media_type_arg == "auto":
        media_type_arg = _infer_media_type(disc_info)
        if media_type_arg != "auto":
            log.info("Inferred media type from disc structure: %s", media_type_arg)

    # TMDb lookup
    api_key = get_api_key(getattr(args, "api_key", None))
    try:
        provider = TmdbProvider(api_key=api_key)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        request = SearchRequest(
            title=title_arg,
            year=getattr(args, "year", None),
            media_type=media_type_arg,
        )
        result = await plan(request, provider)
    except LookupError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error fetching TMDb metadata: {exc}", file=sys.stderr)
        return 1
    finally:
        await provider.close()

    canonical = result.canonical_title
    year = result.year
    is_movie = isinstance(result, PlannedMovie)
    movie_runtime = result.runtime_seconds if is_movie else None

    # dvdcompare lookup
    release = getattr(args, "release", None)
    discs: list = []
    release_name = ""
    print("Looking up disc metadata on dvdcompare.net ...", file=sys.stderr)
    try:
        from dvdcompare.scraper import find_film
        film = await find_film(canonical, disc_format)
        discs, release_name = _select_dvdcompare_release(
            film, disc_info=disc_info, preferred=release,
        )
        if release_name:
            print(f"  Selected release: {release_name}", file=sys.stderr)
    except SystemExit:
        raise
    except LookupError as exc:
        print(f"Warning: {exc}", file=sys.stderr)
    except Exception as exc:
        print(f"Warning: dvdcompare lookup failed ({type(exc).__name__}).", file=sys.stderr)

    # Show disc analysis
    _print_disc_analysis(disc_info, discs, is_movie, movie_runtime)

    # Determine which titles to rip
    dvd_entries, total_episode_runtime, episode_count = build_dvd_entries(discs)

    if getattr(args, "titles", None):
        # User override
        try:
            rip_indices = [int(x.strip()) for x in args.titles.split(",")]
        except ValueError:
            print("Error: --titles must be comma-separated integers.", file=sys.stderr)
            return 1
        rip_titles = [t for t in disc_info.titles if t.index in rip_indices]
        if not rip_titles:
            print("Error: none of the specified title indices exist on disc.", file=sys.stderr)
            return 1
    elif getattr(args, "rip_all", False):
        rip_titles = list(disc_info.titles)
    else:
        rip_titles = [
            t for t in disc_info.titles
            if not is_skip_title(
                t, disc_info.titles, is_movie, movie_runtime,
                total_episode_runtime, episode_count,
            )
        ]

    if not rip_titles:
        print("\nNo titles to rip.", file=sys.stderr)
        return 0

    # Output directory
    output_val = get_output_root(getattr(args, "output", None))
    if not output_val:
        print("Error: --output or output_root config required.", file=sys.stderr)
        return 1

    disc_number = _detect_disc_number(disc_info, discs)
    folder_base = f"{canonical} ({year})"
    if disc_number:
        disc_folder = f"Disc {disc_number}"
    else:
        disc_folder = "Disc 1"
        if discs and len(discs) > 1:
            print(f"\nWarning: could not auto-detect disc number. Defaulting to '{disc_folder}'.", file=sys.stderr)
            print("  Use --titles and manually organize if this is wrong.", file=sys.stderr)

    rip_output = get_rip_output()
    rip_base = Path(rip_output) / folder_base if rip_output else Path(output_val) / "Rips" / folder_base
    output_dir = rip_base / disc_folder

    # Confirmation
    total_size = sum(t.size_bytes for t in rip_titles) / (1024 ** 3)
    rip_indices_str = ", ".join(str(t.index) for t in rip_titles)
    print(f"\nWill rip {len(rip_titles)} title(s) [{rip_indices_str}] ({total_size:.1f} GB)")
    print(f"Output: {output_dir}")

    dry_run = not getattr(args, "execute", False)
    if dry_run:
        print(f"\n{_execute_hint('rip')}")
        return 0

    if not getattr(args, "yes", False):
        if not prompt_confirm("Proceed?"):
            print("Aborted.", file=sys.stderr)
            return 0

    # Rip each title
    rip_start = time.monotonic()
    results = []
    for i, t in enumerate(rip_titles, 1):
        print(f"\nRipping title {t.index} ({i}/{len(rip_titles)}): "
              f"{_format_seconds(t.duration_seconds)}, "
              f"{t.size_bytes / (1024**3):.1f} GB ...")

        title_start = time.monotonic()
        last_pct = [-1]
        title_bytes = t.size_bytes
        bar_style = _random_bar_style()

        def _progress_cb(progress, _last=last_pct, _style=bar_style,
                         _start=title_start, _total=title_bytes):
            if progress.max_val > 0:
                pct = progress.current * 100 // progress.max_val
                if pct != _last[0]:
                    _last[0] = pct
                    bar_width = 30
                    filled = bar_width * pct // 100
                    bar = _style["fill"] * filled + _style["head"] * (1 if filled < bar_width else 0) + _style["empty"] * (bar_width - filled - (1 if filled < bar_width else 0))
                    elapsed = time.monotonic() - _start
                    done_bytes = _total * pct // 100
                    done_gb = done_bytes / (1024 ** 3)
                    total_gb = _total / (1024 ** 3)
                    speed_mbs = (done_bytes / (1024 ** 2)) / elapsed if elapsed > 1 else 0
                    if pct > 0 and speed_mbs > 0:
                        remaining_bytes = _total - done_bytes
                        eta_secs = int(remaining_bytes / (speed_mbs * 1024 * 1024))
                        eta_str = _format_seconds(eta_secs)
                    else:
                        eta_str = "..."
                    print(
                        f"\r  {_style['left']}{bar}{_style['right']} {pct:3d}%  "
                        f"{done_gb:.1f}/{total_gb:.1f} GB  "
                        f"{speed_mbs:.0f} MB/s  ETA {eta_str}   ",
                        end="", flush=True,
                    )

        rip_result = run_rip(
            drive_idx, t.index, output_dir,
            makemkvcon=exe,
            progress_callback=_progress_cb,
        )

        elapsed = time.monotonic() - title_start
        print()  # newline after progress

        results.append(rip_result)
        if rip_result.success:
            print(f"  Done: {rip_result.output_file} ({_format_seconds(int(elapsed))})")
        else:
            print(f"  FAILED: {rip_result.error_message}", file=sys.stderr)

    # Summary
    total_elapsed = time.monotonic() - rip_start
    succeeded = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    print(f"\n{'=' * 60}")
    print(f"Rip complete: {len(succeeded)} succeeded, {len(failed)} failed"
          f" ({_format_seconds(int(total_elapsed))})")
    if succeeded:
        print(f"Output: {output_dir}")
    if failed:
        for r in failed:
            print(f"  FAILED title {r.title_index}: {r.error_message}", file=sys.stderr)

    # Write rip manifest
    if succeeded:
        manifest = {
            "title": canonical,
            "year": year,
            "type": "movie" if is_movie else "tv",
            "disc_number": disc_number,
            "disc_label": volume_label,
            "format": disc_format,
            "release": release_name,
            "files": [],
        }
        for r in results:
            if not r.success:
                continue
            t = next((t for t in disc_info.titles if t.index == r.title_index), None)
            classification = ""
            if t:
                classification = classify_title(
                    t, disc_info.titles, dvd_entries,
                    is_movie, movie_runtime,
                    total_episode_runtime, episode_count,
                )
                # Strip " - rip this" / " - skip ..." suffix for the manifest
                if " - " in classification:
                    classification = classification[:classification.rindex(" - ")]
            manifest["files"].append({
                "filename": Path(r.output_file).name if r.output_file else "",
                "title_index": r.title_index,
                "duration": t.duration_seconds if t else 0,
                "resolution": t.resolution if t else "",
                "size_bytes": t.size_bytes if t else 0,
                "classification": classification,
                "stream_count": t.stream_count if t else 0,
                "stream_fingerprint": build_stream_fingerprint(t) if t else "",
                "chapter_count": t.chapters if t else 0,
                "chapter_durations": (
                    probe_chapter_durations(r.output_file)
                    if r.output_file else []
                ),
            })

        manifest_path = output_dir / "_rip_manifest.json"
        manifest_path.write_text(json_mod.dumps(manifest, indent=2), encoding="utf-8")
        log.info("Wrote rip manifest: %s", manifest_path)

    # Write debug snapshot (disc_info + metadata for troubleshooting)
    try:
        snapshot = {
            "disc_name": disc_info.disc_name,
            "drive": str(drive_idx),
            "title_count": len(disc_info.titles),
            "titles": [
                {
                    "index": t.index,
                    "duration_seconds": t.duration_seconds,
                    "resolution": t.resolution,
                    "size_bytes": t.size_bytes,
                    "chapters": getattr(t, "chapter_count", None),
                }
                for t in disc_info.titles
            ],
            "tmdb": {
                "canonical_title": canonical,
                "year": year,
                "type": "movie" if is_movie else "tv",
                "movie_runtime": movie_runtime,
            },
            "dvdcompare": {
                "release": release_name,
                "disc_count": len(discs),
                "discs": [
                    {
                        "number": d.number,
                        "episode_count": len(d.episodes),
                        "extra_count": len(d.extras),
                    }
                    for d in discs
                ],
            },
            "ripped_titles": [t.index for t in rip_titles],
        }
        snapshot_path = output_dir / "_rip_snapshot.json"
        snapshot_path.write_text(json_mod.dumps(snapshot, indent=2), encoding="utf-8")
        log.info("Wrote rip snapshot: %s", snapshot_path)
    except Exception as exc:
        log.warning("Failed to write rip snapshot: %s", exc)

    # Auto-organize
    if getattr(args, "auto_organize", False) and succeeded and not failed:
        print(f"\nRunning organize on {output_dir.parent} ...")
        organize_args = argparse.Namespace(
            folder=str(output_dir.parent),
            title=canonical,
            year=year,
            media_type="movie" if is_movie else "tv",
            disc_format=disc_format,
            release=release_name or "1",
            output=output_val,
            execute=True,
            json=False,
            api_key=getattr(args, "api_key", None),
            unmatched="extras",
            verbose=getattr(args, "verbose", False),
            no_cache=getattr(args, "no_cache", False),
            force=False,
            snapshot=None,
        )
        return await _run_organize(organize_args)

    return 1 if failed else 0


# ---- helpers for disc content summaries ----

def _find_ripped_discs(output_dir: Path) -> set[int]:
    """Scan output_dir for Disc N subdirectories with a _rip_manifest.json."""
    ripped: set[int] = set()
    if not output_dir.exists():
        return ripped
    for child in output_dir.iterdir():
        if child.is_dir() and (child / "_rip_manifest.json").exists():
            m = re.match(r"Disc\s+(\d+)", child.name, re.IGNORECASE)
            if m:
                ripped.add(int(m.group(1)))
    return ripped


def _disc_content_summary(disc) -> str:
    """Return a short comma-separated summary of a dvdcompare disc's content."""
    titles = []
    for ep in disc.episodes:
        titles.append(ep.title)
    for ex in disc.extras:
        titles.append(ex.title)
    if not titles:
        return "(no content listed)"
    # Truncate if too many items
    if len(titles) > 4:
        return ", ".join(titles[:4]) + f", ... ({len(titles)} items)"
    return ", ".join(titles)


def _print_disc_overview(
    dvdcompare_discs: list,
    release_name: str,
    ripped_discs: set[int],
    inserted_disc: int | None,
) -> None:
    """Print a formatted overview of all discs in the release."""
    print(f"\n{release_name} [{len(dvdcompare_discs)} discs]")
    for disc in dvdcompare_discs:
        fmt = disc.disc_format if hasattr(disc, "disc_format") and disc.disc_format else ""
        summary = _disc_content_summary(disc)
        status = ""
        if disc.number in ripped_discs:
            status = "  [RIPPED]"
        elif disc.number == inserted_disc:
            status = "  [INSERTED]"
        fmt_str = f" ({fmt})" if fmt else ""
        print(f"  Disc {disc.number}{fmt_str}: {summary}{status}")
    print()


def _build_scanned_from_manifests(rip_root: Path) -> list:
    """Build ScannedDisc objects from rip manifest files (skip ffprobe).

    Reads _rip_manifest.json from each Disc N subfolder and constructs
    ScannedFile objects using metadata captured at rip time.
    """
    import json as json_mod

    from plex_planner.models import ScannedDisc, ScannedFile

    discs: list[ScannedDisc] = []
    for child in sorted(rip_root.iterdir()):
        manifest_path = child / "_rip_manifest.json"
        if not child.is_dir() or not manifest_path.exists():
            continue
        try:
            manifest = json_mod.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json_mod.JSONDecodeError) as exc:
            log.warning("Failed to read manifest %s: %s", manifest_path, exc)
            continue

        files: list[ScannedFile] = []
        for entry in manifest.get("files", []):
            filename = entry.get("filename", "")
            if not filename:
                continue
            file_path = child / filename
            # Parse resolution into width/height
            res = entry.get("resolution", "")
            width, height = 0, 0
            if "x" in res:
                parts = res.split("x")
                try:
                    width, height = int(parts[0]), int(parts[1])
                except ValueError:
                    pass

            sf = ScannedFile(
                name=filename,
                path=str(file_path),
                duration_seconds=entry.get("duration", 0),
                size_bytes=entry.get("size_bytes", 0),
                stream_count=entry.get("stream_count", 0),
                stream_fingerprint=entry.get("stream_fingerprint", ""),
                chapter_count=entry.get("chapter_count", 0),
                chapter_durations=entry.get("chapter_durations", []),
                max_width=width,
                max_height=height,
            )
            files.append(sf)

        if files:
            discs.append(ScannedDisc(folder_name=child.name, files=files))

    return discs


async def _run_orchestrate(args: argparse.Namespace) -> int:
    """Multi-disc rip and organize pipeline."""
    import json as json_mod
    import time

    from plex_planner.makemkv import (
        build_stream_fingerprint,
        eject_disc,
        find_makemkvcon,
        probe_chapter_durations,
        run_disc_info,
        run_drive_list,
        run_rip,
        wait_for_disc,
    )

    log_file = _setup_logging(verbose=getattr(args, "verbose", False))
    log.info("plex-planner orchestrate: args=%s", vars(args))
    print(f"Debug log: {log_file}", file=sys.stderr)

    snapshot_mode = getattr(args, "snapshot", False)
    dry_run = not getattr(args, "execute", False) and not snapshot_mode
    if snapshot_mode:
        print("\n--- SNAPSHOT MODE (scan + write manifest, no rip) ---\n")
    elif dry_run:
        print(f"\n{_dry_run_banner('rip and organize')}\n")
    else:
        print("\n--- EXECUTING ---\n")

    if getattr(args, "no_cache", False):
        from plex_planner import cache
        cache.disable()

    # Find makemkvcon
    exe = find_makemkvcon()
    if not exe:
        print("Error: makemkvcon not found. Install MakeMKV or ensure makemkvcon is on PATH.", file=sys.stderr)
        return 1

    # Resolve drive
    drive_arg = getattr(args, "drive", "auto") or "auto"
    print("Scanning drives ...", file=sys.stderr)
    drives = run_drive_list(exe)

    if drive_arg == "auto":
        active = [d for d in drives if d.has_disc]
        if not active:
            if not is_interactive():
                print("Error: no disc found in any drive.", file=sys.stderr)
                return 1
            # Interactive: prompt to insert a disc
            if not drives:
                print("Error: no optical drives found.", file=sys.stderr)
                return 1
            drive_idx = drives[0].index
            drive_device = drives[0].device
            print("No disc inserted.", file=sys.stderr)
            if not prompt_confirm("Insert a disc and continue?"):
                return 0
            print("Waiting for disc ...", file=sys.stderr)
            new_drive = wait_for_disc(
                drive_idx, makemkvcon=exe, previous_label="",
            )
            if not new_drive:
                print("Timed out waiting for disc.", file=sys.stderr)
                return 1
            print(f"Detected: {new_drive.disc_label} ({new_drive.device})", file=sys.stderr)
            drive_device = new_drive.device
            volume_label = new_drive.disc_label
            disc_info = None  # read below
        elif len(active) > 1 and is_interactive():
            # Multiple drives have discs, let user choose
            print(f"Found {len(active)} drives with discs:", file=sys.stderr)
            chosen = prompt_choice(
                "Which drive to use?",
                [f"Drive {d.index}: {d.disc_label} ({d.device})" for d in active],
                default=0,
            )
            selected = active[chosen]
            print(f"Found disc in drive {selected.index}: {selected.disc_label} ({selected.device})", file=sys.stderr)
            drive_idx = selected.index
            drive_device = selected.device
            volume_label = selected.disc_label
            disc_info = None  # read below
        else:
            selected = active[0]
            print(f"Found disc in drive {selected.index}: {selected.disc_label} ({selected.device})", file=sys.stderr)
            drive_idx = selected.index
            drive_device = selected.device
            volume_label = selected.disc_label
            disc_info = None  # read below
    else:
        try:
            drive_idx = int(drive_arg)
        except ValueError:
            drive_idx = drive_arg
        volume_label = None
        disc_info = None
        # Resolve device letter from drive list regardless of how drive was specified
        drive_device = ""
        for d in drives:
            if d.index == drive_idx or d.device == drive_arg:
                drive_device = d.device
                break

    # Read initial disc info (only if a disc is present or drive explicitly given)
    if disc_info is None:
        print("Reading disc info ...", file=sys.stderr)
        try:
            disc_info = run_disc_info(drive_idx, exe)
        except (RuntimeError, FileNotFoundError) as exc:
            print(f"Error reading disc: {exc}", file=sys.stderr)
            return 1

        if not disc_info.titles:
            print("Error: no titles found on disc.", file=sys.stderr)
            return 1

    if volume_label is None:
        volume_label = disc_info.disc_name or ""

    # Auto-detect title
    title_arg = getattr(args, "title", None)
    if not title_arg:
        title_arg = _parse_volume_label(volume_label)
        if title_arg:
            print(f"Auto-detected title from volume label: {title_arg}", file=sys.stderr)
            title_arg = prompt_text("Title", default=title_arg)
        else:
            print("Error: could not detect title from volume label. Provide --title.", file=sys.stderr)
            return 1

    # Auto-detect disc format
    disc_format = getattr(args, "disc_format", None)
    if not disc_format:
        disc_format = _detect_disc_format(disc_info)
        if disc_format:
            log.info("Auto-detected disc format: %s", disc_format)

    # Infer media type
    media_type_arg = getattr(args, "media_type", "auto")
    if media_type_arg == "auto":
        media_type_arg = _infer_media_type(disc_info)
        if media_type_arg != "auto":
            log.info("Inferred media type from disc structure: %s", media_type_arg)

    # TMDb lookup
    api_key = get_api_key(getattr(args, "api_key", None))
    try:
        provider = TmdbProvider(api_key=api_key)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        request = SearchRequest(
            title=title_arg,
            year=getattr(args, "year", None),
            media_type=media_type_arg,
        )
        result = await plan(request, provider)
    except LookupError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error fetching TMDb metadata: {exc}", file=sys.stderr)
        return 1
    finally:
        await provider.close()

    canonical = result.canonical_title
    year = result.year
    is_movie = isinstance(result, PlannedMovie)
    movie_runtime = result.runtime_seconds if is_movie else None

    print(f"TMDb: {canonical} ({year})", file=sys.stderr)

    # dvdcompare lookup
    release = getattr(args, "release", None)
    discs: list = []
    release_name = ""
    print("Looking up disc metadata on dvdcompare.net ...", file=sys.stderr)
    try:
        from dvdcompare.scraper import find_film
        film = await find_film(canonical, disc_format)
        discs, release_name = _select_dvdcompare_release(
            film, disc_info=disc_info, preferred=release,
        )
    except SystemExit:
        raise
    except LookupError as exc:
        print(f"Error: dvdcompare lookup failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: dvdcompare lookup failed ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1

    if not discs:
        print("Error: no disc metadata found on dvdcompare.", file=sys.stderr)
        return 1

    # Output directory
    output_val = get_output_root(getattr(args, "output", None))
    if not output_val:
        print("Error: --output or output_root config required.", file=sys.stderr)
        return 1

    folder_base = f"{canonical} ({year})"
    rip_output = get_rip_output()
    rip_root = Path(rip_output) / folder_base if rip_output else Path(output_val) / "Rips" / folder_base

    # Detect which disc is currently inserted
    current_disc_num = _detect_disc_number(disc_info, discs)

    # Resume: detect already-ripped discs from manifest files
    ripped_discs = _find_ripped_discs(rip_root)

    # Show disc overview
    _print_disc_overview(discs, release_name, ripped_discs, current_disc_num)

    if ripped_discs:
        ripped_list = ", ".join(str(n) for n in sorted(ripped_discs))
        print(f"Previously ripped: Disc {ripped_list}", file=sys.stderr)

    # ---- Per-disc rip loop ----
    any_ripped = len(ripped_discs) > 0
    any_failed = False
    disc_order = sorted(discs, key=lambda d: d.number)

    # Filter discs based on --discs flag or interactive prompt
    discs_arg = getattr(args, "discs", None)
    if discs_arg:
        # Parse comma-separated disc numbers
        try:
            selected_nums = {int(x.strip()) for x in discs_arg.split(",")}
        except ValueError:
            print("Error: --discs must be comma-separated numbers (e.g. '1,3').", file=sys.stderr)
            return 1
        disc_order = [d for d in disc_order if d.number in selected_nums]
        if not disc_order:
            print("Error: none of the specified disc numbers match this release.", file=sys.stderr)
            return 1
    elif is_interactive() and not snapshot_mode and len(disc_order) > 1:
        # Interactive disc selection when multiple discs exist
        unripped = [d for d in disc_order if d.number not in ripped_discs]
        if len(unripped) > 1:
            from plex_planner.ui import prompt_multi_select
            options = []
            for d in unripped:
                summary = _disc_content_summary(d)
                fmt = d.disc_format if hasattr(d, "disc_format") and d.disc_format else ""
                fmt_str = f" ({fmt})" if fmt else ""
                options.append(f"Disc {d.number}{fmt_str}: {summary}")
            selected_indices = prompt_multi_select(
                "Which discs do you want to rip?",
                options,
                defaults=list(range(len(options))),  # all selected by default
            )
            if selected_indices is not None:
                selected_discs = [unripped[i] for i in selected_indices]
                # Keep already-ripped discs in order (they'll be skipped anyway)
                # and replace unripped portion with selection
                disc_order = [d for d in disc_order if d.number in ripped_discs] + selected_discs

    # Start from the inserted disc if possible, otherwise from first unripped
    if current_disc_num:
        # Reorder: inserted disc first, then remaining in order
        start_disc = next((d for d in disc_order if d.number == current_disc_num), None)
        remaining = [d for d in disc_order if d.number != current_disc_num]
        disc_order = ([start_disc] if start_disc else []) + remaining

    for disc_idx, disc in enumerate(disc_order):
        if disc.number in ripped_discs:
            continue

        # Check if we need the user to insert this disc
        need_insert = (disc_idx > 0) or (current_disc_num != disc.number)

        if need_insert and not dry_run:
            summary = _disc_content_summary(disc)
            fmt = disc.disc_format if hasattr(disc, "disc_format") and disc.disc_format else ""
            fmt_str = f" ({fmt})" if fmt else ""
            print(f"\n{'=' * 60}")
            print(f"Insert Disc {disc.number}{fmt_str}: {summary}")
            print(f"{'=' * 60}")

            if is_interactive():
                # Interactive: wait for user to confirm
                if not prompt_confirm("Disc inserted and ready?"):
                    action = prompt_choice(
                        "What would you like to do?",
                        ["Skip this disc", "Finish and organize"],
                        default=0,
                    )
                    if action == 1:
                        break
                    continue
            else:
                # Non-interactive (--auto): wait for a new disc to appear
                print("Waiting for new disc ...", file=sys.stderr)
                new_drive = wait_for_disc(
                    drive_idx, makemkvcon=exe,
                    previous_label=volume_label or "",
                )
                if not new_drive:
                    print("Timed out waiting for disc. Stopping.", file=sys.stderr)
                    break
                print(f"Detected: {new_drive.disc_label} ({new_drive.device})", file=sys.stderr)
                volume_label = new_drive.disc_label

            # Re-read disc info after insertion
            print("Reading disc info ...", file=sys.stderr)
            try:
                disc_info = run_disc_info(drive_idx, exe)
            except (RuntimeError, FileNotFoundError) as exc:
                print(f"Error reading disc: {exc}", file=sys.stderr)
                any_failed = True
                continue

            # Verify disc number
            detected = _detect_disc_number(disc_info, discs)
            if detected and detected != disc.number:
                print(f"Warning: expected Disc {disc.number} but detected Disc {detected}.", file=sys.stderr)
                if not prompt_confirm("Continue anyway?"):
                    continue

        # Prompt: rip, skip, or finish
        if not dry_run and not snapshot_mode:
            summary = _disc_content_summary(disc)
            fmt = disc.disc_format if hasattr(disc, "disc_format") and disc.disc_format else ""
            fmt_str = f" ({fmt})" if fmt else ""
            action = prompt_choice(
                f"Disc {disc.number}{fmt_str}: {summary}",
                [
                    "Rip this disc",
                    "Skip this disc",
                    "Finish and organize",
                ],
                default=0,
            )
            if action == 1:
                continue
            if action == 2:
                break

        # In dry-run, we can only analyze the currently-inserted disc.
        # For other discs, show a placeholder based on dvdcompare metadata.
        is_current_disc = (disc.number == current_disc_num)
        output_dir = rip_root / f"Disc {disc.number}"

        if dry_run and not is_current_disc:
            summary = _disc_content_summary(disc)
            fmt = disc.disc_format if hasattr(disc, "disc_format") and disc.disc_format else ""
            fmt_str = f" ({fmt})" if fmt else ""
            print(f"\nDisc {disc.number}{fmt_str}: {summary}")
            print(f"  Would prompt for insertion and rip to: {output_dir}")
            ripped_discs.add(disc.number)
            continue

        # Show disc analysis for the currently-inserted disc
        # Only use current disc's entries for classification to avoid
        # matching extras from other discs to titles on this one
        current_disc_entries = [d for d in discs if d.number == disc.number]
        dvd_entries, total_episode_runtime, episode_count = build_dvd_entries(current_disc_entries)
        _print_disc_analysis(disc_info, current_disc_entries, is_movie, movie_runtime)

        # Filter titles to rip (smart filtering)
        rip_titles = [
            t for t in disc_info.titles
            if not is_skip_title(
                t, disc_info.titles, is_movie, movie_runtime,
                total_episode_runtime, episode_count,
            )
        ]

        if not rip_titles:
            print(f"\nNo titles to rip on Disc {disc.number}.", file=sys.stderr)
            continue

        total_size = sum(t.size_bytes for t in rip_titles) / (1024 ** 3)
        rip_indices_str = ", ".join(str(t.index) for t in rip_titles)
        print(f"\nWill rip {len(rip_titles)} title(s) [{rip_indices_str}] ({total_size:.1f} GB)")
        print(f"Output: {output_dir}")

        # --snapshot: write manifest from disc info without ripping
        if snapshot_mode:
            output_dir.mkdir(parents=True, exist_ok=True)
            manifest = {
                "title": canonical,
                "year": year,
                "type": "movie" if is_movie else "tv",
                "disc_number": disc.number,
                "disc_label": volume_label,
                "format": disc_format,
                "release": release_name,
                "files": [],
            }
            for t in rip_titles:
                classification = classify_title(
                    t, disc_info.titles, dvd_entries,
                    is_movie, movie_runtime,
                    total_episode_runtime, episode_count,
                )
                if " - " in classification:
                    classification = classification[:classification.rindex(" - ")]
                manifest["files"].append({
                    "filename": f"{canonical.replace(' ', '_')}_t{t.index:02d}.mkv",
                    "title_index": t.index,
                    "duration": t.duration_seconds,
                    "resolution": t.resolution,
                    "size_bytes": t.size_bytes,
                    "classification": classification,
                    "stream_count": t.stream_count,
                    "stream_fingerprint": build_stream_fingerprint(t),
                    "chapter_count": t.chapters,
                    "chapter_durations": [],
                })
            manifest_path = output_dir / "_rip_manifest.json"
            manifest_path.write_text(json_mod.dumps(manifest, indent=2), encoding="utf-8")
            print(f"Snapshot manifest written: {manifest_path}", file=sys.stderr)
            ripped_discs.add(disc.number)
            continue

        if dry_run:
            ripped_discs.add(disc.number)
            continue

        if not getattr(args, "yes", False):
            if not prompt_confirm("Proceed?"):
                continue

        # Rip each title on this disc
        rip_start = time.monotonic()
        results = []
        for i, t in enumerate(rip_titles, 1):
            print(f"\nRipping title {t.index} ({i}/{len(rip_titles)}): "
                  f"{_format_seconds(t.duration_seconds)}, "
                  f"{t.size_bytes / (1024**3):.1f} GB ...")

            title_start = time.monotonic()
            title_bytes = t.size_bytes
            last_pct = [-1]
            bar_style = _random_bar_style()

            def _progress_cb(progress, _last=last_pct, _style=bar_style,
                             _start=title_start, _total=title_bytes):
                if progress.max_val > 0:
                    pct = progress.current * 100 // progress.max_val
                    if pct != _last[0]:
                        _last[0] = pct
                        bar_width = 30
                        filled = bar_width * pct // 100
                        bar = _style["fill"] * filled + _style["head"] * (1 if filled < bar_width else 0) + _style["empty"] * (bar_width - filled - (1 if filled < bar_width else 0))
                        elapsed = time.monotonic() - _start
                        # Size progress
                        done_bytes = _total * pct // 100
                        done_gb = done_bytes / (1024 ** 3)
                        total_gb = _total / (1024 ** 3)
                        # Speed
                        speed_mbs = (done_bytes / (1024 ** 2)) / elapsed if elapsed > 1 else 0
                        # ETA
                        if pct > 0 and speed_mbs > 0:
                            remaining_bytes = _total - done_bytes
                            eta_secs = int(remaining_bytes / (speed_mbs * 1024 * 1024))
                            eta_str = _format_seconds(eta_secs)
                        else:
                            eta_str = "..."
                        print(
                            f"\r  {_style['left']}{bar}{_style['right']} {pct:3d}%  "
                            f"{done_gb:.1f}/{total_gb:.1f} GB  "
                            f"{speed_mbs:.0f} MB/s  ETA {eta_str}   ",
                            end="", flush=True,
                        )

            rip_result = run_rip(
                drive_idx, t.index, output_dir,
                makemkvcon=exe,
                progress_callback=_progress_cb,
            )

            elapsed = time.monotonic() - title_start
            print()  # newline after progress

            results.append(rip_result)
            if rip_result.success:
                print(f"  Done: {rip_result.output_file} ({_format_seconds(int(elapsed))})")
            else:
                print(f"  FAILED: {rip_result.error_message}", file=sys.stderr)
                any_failed = True

        # Disc rip summary
        total_elapsed = time.monotonic() - rip_start
        succeeded = [r for r in results if r.success]
        failed = [r for r in results if not r.success]

        print(f"\nDisc {disc.number}: {len(succeeded)} succeeded, {len(failed)} failed"
              f" ({_format_seconds(int(total_elapsed))})")

        # Write rip manifest
        if succeeded:
            manifest = {
                "title": canonical,
                "year": year,
                "type": "movie" if is_movie else "tv",
                "disc_number": disc.number,
                "disc_label": volume_label,
                "format": disc_format,
                "release": release_name,
                "files": [],
            }
            for r in results:
                if not r.success:
                    continue
                t = next((t for t in disc_info.titles if t.index == r.title_index), None)
                classification = ""
                if t:
                    classification = classify_title(
                        t, disc_info.titles, dvd_entries,
                        is_movie, movie_runtime,
                        total_episode_runtime, episode_count,
                    )
                    if " - " in classification:
                        classification = classification[:classification.rindex(" - ")]
                manifest["files"].append({
                    "filename": Path(r.output_file).name if r.output_file else "",
                    "title_index": r.title_index,
                    "duration": t.duration_seconds if t else 0,
                    "resolution": t.resolution if t else "",
                    "size_bytes": t.size_bytes if t else 0,
                    "classification": classification,
                    "stream_count": t.stream_count if t else 0,
                    "stream_fingerprint": build_stream_fingerprint(t) if t else "",
                    "chapter_count": t.chapters if t else 0,
                    "chapter_durations": (
                        probe_chapter_durations(r.output_file)
                        if r.output_file else []
                    ),
                })

            manifest_path = output_dir / "_rip_manifest.json"
            manifest_path.write_text(json_mod.dumps(manifest, indent=2), encoding="utf-8")
            log.info("Wrote rip manifest: %s", manifest_path)
            ripped_discs.add(disc.number)
            any_ripped = True

            # Eject disc after successful rip
            if drive_device:
                print(f"\nEjecting disc ...", file=sys.stderr)
                eject_disc(drive_device)

    # ---- Summary ----
    if ripped_discs:
        ripped_list = ", ".join(str(n) for n in sorted(ripped_discs))
        print(f"\n{'=' * 60}")
        print(f"Rip phase complete. Discs ripped: {ripped_list}")
        print(f"Output: {rip_root}")

    # ---- Organize phase ----
    if snapshot_mode:
        print(f"\nSnapshot complete. Manifests written to: {rip_root}", file=sys.stderr)
        return 0

    if not any_ripped and not ripped_discs:
        print("\nNo discs were ripped. Nothing to organize.", file=sys.stderr)
        return 0

    # In dry-run, skip organize if the rip folder doesn't actually exist
    if dry_run and not rip_root.exists():
        print(f"\n{'=' * 60}")
        print("Organize phase (skipped in dry-run, no ripped files yet)")
        print(f"{'=' * 60}")
        print(f"\nRe-run with --execute to rip and organize:\n  {_build_execute_command()}")
        return 0

    print(f"\n{'=' * 60}")
    print("Organize phase")
    print(f"{'=' * 60}")

    organize_args = argparse.Namespace(
        folder=str(rip_root),
        title=canonical,
        year=year,
        media_type="movie" if is_movie else "tv",
        disc_format=disc_format,
        release=release_name or "1",
        output=output_val,
        execute=not dry_run,
        json=False,
        api_key=getattr(args, "api_key", None),
        unmatched=getattr(args, "unmatched", "extras"),
        verbose=getattr(args, "verbose", False),
        no_cache=getattr(args, "no_cache", False),
        force=False,
        snapshot=None,
        auto=True,  # skip interactive prompts in organize since we resolved metadata above
    )

    # Optimization: build ScannedDisc objects from manifest data (avoids ffprobe)
    scanned_from_manifest = _build_scanned_from_manifests(rip_root)
    if scanned_from_manifest:
        log.info(
            "Using manifest data for organize (%d discs, skip ffprobe scan)",
            len(scanned_from_manifest),
        )
        print("Using rip manifest data (skipping ffprobe scan).", file=sys.stderr)
        api_key = get_api_key(getattr(args, "api_key", None))
        provider = TmdbProvider(api_key=api_key)
        try:
            org_result = await _organize_with_scanned(
                scanned_from_manifest, canonical, organize_args,
                Path(output_val), provider,
            )
        finally:
            await provider.close()
    else:
        org_result = await _run_organize(organize_args)

    if dry_run:
        # Replace the organize hint with an orchestrate hint
        print(f"\nRe-run with --execute to rip and organize:\n  {_build_execute_command()}")

    # ---- Archive phase ----
    if not dry_run and org_result == 0:
        archive_root = get_archive_root()
        if archive_root and rip_root.exists():
            archive_dest = Path(archive_root) / folder_base
            if is_interactive():
                print(f"\nArchive rip folder to: {archive_dest}", file=sys.stderr)
                if prompt_confirm("Move rip folder to archive?"):
                    archive_dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(rip_root), archive_dest)
                    print(f"Archived: {rip_root} -> {archive_dest}", file=sys.stderr)
            else:
                # Auto mode: archive automatically
                archive_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(rip_root), archive_dest)
                print(f"Archived: {rip_root} -> {archive_dest}", file=sys.stderr)

    return org_result if not any_failed else 1


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    set_auto_mode(getattr(args, "auto", False))
    sys.exit(asyncio.run(_run(args)))


async def _run_organize(args: argparse.Namespace) -> int:
    """Run the organize workflow: scan, look up metadata, match, organize."""
    log_file = _setup_logging(verbose=getattr(args, "verbose", False))
    log.info("plex-planner organize: args=%s", vars(args))
    print(f"Debug log: {log_file}", file=sys.stderr)

    dry_run = not getattr(args, "execute", False)
    if dry_run:
        print(f"\n{_dry_run_banner('move files')}\n")
    else:
        print("\n--- EXECUTING ---\n")

    if getattr(args, "no_cache", False):
        from plex_planner import cache
        cache.disable()

    # Snapshot mode: load metadata from JSON, force dry-run
    snapshot_path = getattr(args, "snapshot", None)
    if snapshot_path:
        snapshot_file = Path(snapshot_path)
        if not snapshot_file.is_file():
            print(f"Error: snapshot file not found: {snapshot_file}", file=sys.stderr)
            return 1
        if getattr(args, "execute", False):
            print("Error: --execute is not allowed with --snapshot (always dry-run).", file=sys.stderr)
            return 1
        args.execute = False

        scanned = snapshot_load(snapshot_file)
        print(f"Loaded snapshot from {snapshot_file}", file=sys.stderr)

        folder = Path(args.folder)
        output_val = get_output_root(args.output)
        output_root = Path(output_val) if output_val else folder.parent

        if args.title:
            title = args.title
        else:
            title, inferred_year = _strip_year_from_title(folder.name)
            if inferred_year and not getattr(args, "year", None):
                args.year = inferred_year

        api_key = get_api_key(getattr(args, "api_key", None))
        try:
            provider = TmdbProvider(api_key=api_key)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        try:
            return await _organize_with_scanned(
                scanned, title, args, output_root, provider,
            )
        finally:
            await provider.close()

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"Error: not a directory: {folder}", file=sys.stderr)
        return 1

    output_val = get_output_root(args.output)
    output_root = Path(output_val) if output_val else folder.parent

    api_key = get_api_key(getattr(args, "api_key", None))
    try:
        provider = TmdbProvider(api_key=api_key)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        # Detect batch vs single mode
        has_root_mkvs = any(folder.glob("*.mkv"))
        has_sub_mkvs = any(folder.glob("*/*.mkv"))

        if has_root_mkvs or (has_sub_mkvs and not any(folder.glob("*/*/*.mkv"))):
            # Single folder mode: MKVs at root or one level of subfolders
            if args.title:
                title = args.title
            else:
                title, inferred_year = _strip_year_from_title(folder.name)
                if inferred_year and not getattr(args, "year", None):
                    args.year = inferred_year
            return await _organize_single(
                folder, title, args, output_root, provider,
            )
        elif has_sub_mkvs or any(folder.glob("*/*/*.mkv")):
            # Batch mode: subfolders contain rip folders
            return await _organize_batch(
                folder, args, output_root, provider,
            )
        else:
            print("No MKV files found.", file=sys.stderr)
            return 1
    finally:
        await provider.close()


async def _organize_batch(
    root: Path,
    args: argparse.Namespace,
    output_root: Path,
    provider: TmdbProvider,
) -> int:
    """Batch organize: auto-detect title groups and process each."""
    groups = group_title_folders(root)
    if not groups:
        print("No title groups found.", file=sys.stderr)
        return 1

    print(f"Batch mode: found {len(groups)} title group(s).", file=sys.stderr)
    for g in groups:
        folders = ", ".join(f.name for f in g.folders)
        print(f"  {g.title} ({len(g.folders)} folder(s): {folders})", file=sys.stderr)

    overall_rc = 0
    for i, group in enumerate(groups):
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"[{i+1}/{len(groups)}] {group.title}", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)

        # Use the first folder if single, otherwise the group has
        # subfolders that scanner will pick up. For multi-folder groups
        # (like "Planet Earth III - Disc 1/2/3"), we need to find a
        # common parent or use the first folder's parent.
        if len(group.folders) == 1:
            target_folder = group.folders[0]
        else:
            # Multiple folders share the same parent (root)
            # Create a virtual scan by passing the root and filtering
            target_folder = group.folders[0]
            # If folders share a parent, scanner should handle subfolders
            # Check if all folders are immediate children of root
            if all(f.parent == root for f in group.folders):
                # We need to scan each folder and combine results
                pass  # handled below

        # Override title from group detection
        if args.title:
            title = args.title
        else:
            title, inferred_year = _strip_year_from_title(group.title)
            if inferred_year and not getattr(args, "year", None):
                args.year = inferred_year

        if len(group.folders) == 1:
            rc = await _organize_single(
                target_folder, title, args, output_root, provider,
            )
        else:
            # Multi-folder group: scan all folders and combine
            rc = await _organize_multi_folder(
                group.folders, title, args, output_root, provider,
            )

        if rc != 0 and rc != 1:
            overall_rc = rc
        elif rc == 1 and overall_rc == 0:
            overall_rc = 1

    return overall_rc


async def _organize_multi_folder(
    folders: list[Path],
    title: str,
    args: argparse.Namespace,
    output_root: Path,
    provider: TmdbProvider,
) -> int:
    """Organize a title group spanning multiple folders."""
    from plex_planner.models import ScannedDisc

    all_scanned: list[ScannedDisc] = []
    for folder in folders:
        print(f"Scanning {folder} ...", file=sys.stderr)
        try:
            scanned = scan_folder(folder)
            # Auto-generate snapshot per disc folder if missing
            snapshot_out = folder / f"{folder.name}.snapshot.json"
            if not snapshot_out.exists():
                snapshot_save_from_scanned(folder, scanned, snapshot_out)
                print(f"Snapshot saved to {snapshot_out}", file=sys.stderr)
            all_scanned.extend(scanned)
        except RuntimeError as exc:
            print(f"Error scanning {folder}: {exc}", file=sys.stderr)

    if not all_scanned:
        print(f"No MKV files found for {title}.", file=sys.stderr)
        return 1

    return await _organize_with_scanned(
        all_scanned, title, args, output_root, provider,
    )


async def _organize_single(
    folder: Path,
    title: str,
    args: argparse.Namespace,
    output_root: Path,
    provider: TmdbProvider,
) -> int:
    """Organize a single rip folder."""
    # Step 1: Scan MKV files
    print(f"Scanning {folder} ...", file=sys.stderr)
    try:
        scanned = scan_folder(folder)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Auto-generate snapshot if one doesn't exist yet
    snapshot_out = folder / f"{folder.name}.snapshot.json"
    if not snapshot_out.exists():
        snapshot_save_from_scanned(folder, scanned, snapshot_out)
        print(f"Snapshot saved to {snapshot_out}", file=sys.stderr)

    return await _organize_with_scanned(
        scanned, title, args, output_root, provider,
    )


async def _organize_with_scanned(
    scanned: list,
    title: str,
    args: argparse.Namespace,
    output_root: Path,
    provider: TmdbProvider,
) -> int:
    """Core organize pipeline operating on already-scanned disc groups."""
    total_files = sum(len(d.files) for d in scanned)
    print(f"Found {total_files} MKV files in {len(scanned)} disc group(s).", file=sys.stderr)
    if total_files == 0:
        print("No MKV files found.", file=sys.stderr)
        return 1

    # Skip already-organized files (unless --force)
    if not getattr(args, "force", False):
        skipped = 0
        for disc in scanned:
            before = len(disc.files)
            disc.files = [f for f in disc.files if not f.organized_tag]
            skipped += before - len(disc.files)
        if skipped:
            total_files = sum(len(d.files) for d in scanned)
            print(f"Skipping {skipped} already-organized file(s).", file=sys.stderr)
            if total_files == 0:
                print("All files already organized. Use --force to re-organize.", file=sys.stderr)
                return 0

    # Detect unusable files (incomplete, no audio)
    incomplete = detect_incomplete(scanned)
    if incomplete:
        print(f"Removing {len(incomplete)} unusable file(s):", file=sys.stderr)
        for f in incomplete:
            if f.duration_seconds == 0 or f.stream_count == 0:
                print(f"  {f.name} (incomplete: 0 duration / no streams)", file=sys.stderr)
            else:
                print(f"  {f.name} ({f.duration_seconds}s, no audio)", file=sys.stderr)
        incomplete_paths = {f.path for f in incomplete}
        for disc in scanned:
            disc.files = [f for f in disc.files if f.path not in incomplete_paths]
        total_files = sum(len(d.files) for d in scanned)
        if total_files == 0:
            print("No usable MKV files found.", file=sys.stderr)
            return 1

    # Auto-detect format if not specified
    disc_format = getattr(args, "disc_format", None)
    if not disc_format:
        disc_format = detect_format(scanned)
        if disc_format:
            log.debug("Auto-detected format: %s", disc_format)

    # Detect and remove duplicates + compilations
    dup_groups, comp_groups = find_all_redundant(scanned)
    if dup_groups:
        dup_count = sum(len(g.duplicates) for g in dup_groups)
        print(f"Detected {dup_count} duplicate(s) in {len(dup_groups)} group(s):", file=sys.stderr)
        for g in dup_groups:
            for d in g.duplicates:
                print(f"  DUPLICATE: {d.name} (keeping {g.keep.name})", file=sys.stderr)
    if comp_groups:
        print(f"Detected {len(comp_groups)} compilation(s):", file=sys.stderr)
        for c in comp_groups:
            parts = ", ".join(p.name for p in c.parts)
            print(f"  COMPILATION: {c.compilation.name} (combined from {parts})", file=sys.stderr)
    if dup_groups or comp_groups:
        scanned = remove_duplicates(scanned, dup_groups, comp_groups)
        total_files = sum(len(d.files) for d in scanned)
        print(f"Proceeding with {total_files} files after dedup.", file=sys.stderr)

    # Infer title from MKV title_tag when no --title override was given
    if not getattr(args, "title", None):
        inferred = _infer_title_from_scanned(scanned)
        if inferred and inferred.lower() != title.lower():
            log.debug("Title inferred from MKV title_tag: %r (was %r)", inferred, title)
            title = inferred
        title = prompt_text("Title", default=title)

    # Auto-detect media type from file durations when mode is "auto".
    # Two heuristics:
    #   TV:    2+ files in the 15-75 min range, none above 75 min
    #   Movie: a single feature-length file (> 90 min)
    media_type = getattr(args, "media_type", "auto")
    if media_type == "auto":
        all_files = [f for d in scanned for f in d.files]
        if all_files:
            episode_range = [f for f in all_files if 900 <= f.duration_seconds <= 4500]
            above_episode = [f for f in all_files if f.duration_seconds > 4500]
            if len(episode_range) >= 2 and not above_episode:
                media_type = "tv"
                log.debug("Auto-detected media_type='tv' (%d episode-length files)", len(episode_range))
            elif all_files:
                longest_dur = max(f.duration_seconds for f in all_files)
                if longest_dur > 5400:  # > 90 minutes
                    media_type = "movie"
                    log.debug("Auto-detected media_type='movie' (longest file %ds)", longest_dur)

    # Look up TMDb metadata
    try:
        request = SearchRequest(
            title=title,
            year=getattr(args, "year", None),
            media_type=media_type,
        )
        result = await plan(request, provider)
    except LookupError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error fetching TMDb metadata: {exc}", file=sys.stderr)
        return 1

    print(f"TMDb: {result.canonical_title} ({result.year})", file=sys.stderr)

    # Look up dvdcompare disc metadata using TMDb canonical title
    dvdcompare_title = result.canonical_title
    print("Looking up disc metadata on dvdcompare.net ...", file=sys.stderr)
    release = getattr(args, "release", None)
    try:
        from dvdcompare.scraper import find_film
        film = await find_film(dvdcompare_title, disc_format)
        discs, release_name = _select_dvdcompare_release(
            film, preferred=release,
        )
        print(f"Found {len(discs)} disc(s) on dvdcompare.", file=sys.stderr)
    except SystemExit:
        raise
    except LookupError as exc:
        print(f"Error: dvdcompare lookup failed: {exc}", file=sys.stderr)
        sys.exit(1)

    # Map folders to discs and match
    if discs:
        folder_map = map_folders_to_discs(scanned, discs, result)
        for folder_name, disc_num in folder_map.items():
            if disc_num is not None:
                print(f"  {folder_name} -> Disc {disc_num}", file=sys.stderr)
            else:
                print(f"  {folder_name} -> (unmapped, global fallback)", file=sys.stderr)

    result_obj = match_discs(scanned, discs, result)
    print(
        f"Matched {len(result_obj.matched)} files, "
        f"{len(result_obj.unmatched)} unmatched, "
        f"{len(result_obj.missing)} missing.",
        file=sys.stderr,
    )

    # Build organize plan
    file_map = {f.name: f.path for d in scanned for f in d.files}
    scanned_map = {f.name: f for d in scanned for f in d.files}
    targets = collect_disc_targets(discs, result) if discs else None
    unmatched_policy = getattr(args, "unmatched", "ignore")
    org_plan = build_organize_plan(
        result_obj, result, output_root, file_map,
        scanned_files=scanned_map, disc_targets=targets,
        unmatched_policy=unmatched_policy,
    )

    # Output
    dry_run = not getattr(args, "execute", False)
    unmatched_dir = output_root / "_Unmatched" / title if unmatched_policy == "move" else None
    actions = execute_plan(org_plan, dry_run=dry_run, unmatched_policy=unmatched_policy, unmatched_dir=unmatched_dir)
    for line in actions:
        print(line)

    if dry_run:
        print(f"\n{_execute_hint('organize')}")

    # Tag organized files after successful execute
    if not dry_run:
        from plex_planner.tagger import tag_organized
        tagged = 0
        for move in org_plan.moves:
            if tag_organized(move.destination, move.label):
                tagged += 1
        for split in org_plan.splits:
            for dest, label in zip(split.chapter_destinations, split.chapter_labels):
                if tag_organized(dest, label):
                    tagged += 1
        if tagged:
            log.info("Tagged %d file(s) as organized", tagged)

    return 0


if __name__ == "__main__":
    main()
