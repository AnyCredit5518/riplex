"""CLI entry point for plex-planner."""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
import tempfile
from pathlib import Path

from plex_planner.config import get_api_key, get_output_root
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
from plex_planner.snapshot import capture as snapshot_capture, load as snapshot_load, save as snapshot_save

log = logging.getLogger(__name__)

_LOG_DIR = Path(tempfile.gettempdir()) / "plex-planner"


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
            "Look up Plex-canonical metadata for a movie or TV title and "
            "output the expected folder structure, filenames, and runtimes."
        ),
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
        default="america",
        help="Regional release: 1-based index or name keyword (default: america).",
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

    # --- snapshot ---
    snap_parser = subs.add_parser(
        "snapshot",
        help="Capture a metadata snapshot of a MakeMKV rip folder.",
    )
    snap_parser.add_argument("folder", help="Path to a MakeMKV rip folder.")
    snap_parser.add_argument(
        "-o", "--output",
        default=None,
        help="Output file path (default: <folder>.snapshot.json in current directory).",
    )

    # --- rip-guide ---
    guide_parser = subs.add_parser(
        "rip-guide",
        help="Show disc contents and recommended rip strategy before ripping.",
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

    # --- plan (deprecated alias for rip-guide) ---
    plan_parser = subs.add_parser(
        "plan",
        help="(Deprecated) Alias for rip-guide.",
    )
    # Mirror all rip-guide args so plan parses the same CLI.
    plan_parser.add_argument("title", nargs="?", help="Movie or TV show title.")
    plan_parser.add_argument("--year", type=int, help="Release year.")
    plan_parser.add_argument(
        "--type", dest="media_type", choices=["movie", "tv", "auto"],
        default="auto",
    )
    plan_parser.add_argument("--format", dest="disc_format", default=None)
    plan_parser.add_argument("--release", default="america")
    plan_parser.add_argument("--output", default=None)
    plan_parser.add_argument("--create-folders", action="store_true", default=False)
    plan_parser.add_argument("--json", action="store_true", default=False)
    plan_parser.add_argument("--api-key", default=None)
    plan_parser.add_argument("--drive", default=None)
    plan_parser.add_argument("--verbose", "-v", action="store_true", default=False)
    plan_parser.add_argument("--no-cache", action="store_true", default=False)
    plan_parser.add_argument("--no-specials", action="store_true", default=False)
    plan_parser.add_argument("--no-extras", action="store_true", default=False)

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
        "--dry-run", "-n", action="store_true", default=False,
        help="Show analysis and what would be ripped, then exit without ripping.",
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

    return parser



async def _run(args: argparse.Namespace) -> int:
    if args.command == "organize":
        return await _run_organize(args)
    if args.command == "snapshot":
        return _run_snapshot(args)
    if args.command == "plan":
        print(
            "Warning: 'plan' is deprecated, use 'rip-guide' instead.",
            file=sys.stderr,
        )
        return await _run_rip_guide(args)
    if args.command == "rip-guide":
        return await _run_rip_guide(args)
    if args.command == "rip":
        return await _run_rip(args)
    # Unknown or missing command
    return 1


def _run_snapshot(args: argparse.Namespace) -> int:
    """Capture a metadata snapshot of a rip folder."""
    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"Error: not a directory: {folder}", file=sys.stderr)
        return 1

    if args.output:
        output = Path(args.output)
    else:
        output = Path(f"{folder.name}.snapshot.json")

    snapshot_save(folder, output)
    print(f"Snapshot saved to {output}")
    return 0


async def _run_rip_guide(args: argparse.Namespace) -> int:
    """Show disc contents and recommended rip strategy (Tier 1: dvdcompare only)."""
    log_file = _setup_logging(verbose=getattr(args, "verbose", False))
    log.info("plex-planner rip-guide: args=%s", vars(args))
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
        makemkv_root = Path(output_val) / "_MakeMKV" / f"{canonical} ({year})"
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
            print(f"  _MakeMKV/{folder_base}/{label}/{fmt_str}{role}")
    else:
        print(f"  _MakeMKV/{folder_base}/")

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

    print(f"  - After ripping, run: plex-planner organize \"_MakeMKV/{folder_base}\"")


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
    if not label or len(label) < 4:
        return None

    # Strip disc number suffix including its leading separator.
    # Matches: "_D2", "-Disc3", " - Disc 1", "_Disc_1"
    # Won't match titles with dashes like "Spider-Man" or "X-Men".
    cleaned = re.sub(r"[\s_-]+D(?:isc[\s_]*)?\d+\s*$", "", label, flags=re.IGNORECASE)

    # Replace underscores with spaces
    cleaned = cleaned.replace("_", " ").strip()

    if len(cleaned) < 3:
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


def _auto_select_release(
    film,
    disc_info,
    preferred: str = "america",
) -> tuple[list, str]:
    """Try to auto-select the best dvdcompare release for a disc.

    Strategy:
    1. Try the preferred release keyword (default "america")
    2. If that fails, score each release by duration matching against the disc
    3. If duration matching fails, fall back to the first release

    Returns (PlannedDisc list, release_name) or ([], "").
    """
    from dvdcompare.cli import select_releases

    if not film.releases:
        return [], ""

    # Strategy 1: try preferred release
    try:
        selected = select_releases(film.releases, preferred)
        discs = _convert_film(film, preferred)
        return discs, selected[0].name
    except LookupError:
        pass

    # Strategy 2: duration matching across all releases
    if disc_info and disc_info.titles:
        live_durations = sorted(
            [t.duration_seconds for t in disc_info.titles if t.duration_seconds > 120],
            reverse=True,
        )
        if live_durations:
            best_release = None
            best_score = -1

            for rel_idx, rel in enumerate(film.releases, 1):
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
                    best_release = rel_idx

            if best_release and best_score >= 0.3:
                discs = _convert_film(film, str(best_release))
                return discs, film.releases[best_release - 1].name

    # Strategy 3: fall back to first release
    discs = _convert_film(film, "1")
    return discs, film.releases[0].name


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
        else:
            print("Error: could not detect title from volume label. Provide a title argument.", file=sys.stderr)
            return 1

    # Auto-detect disc format from resolution if not provided
    disc_format = getattr(args, "disc_format", None)
    if not disc_format:
        disc_format = _detect_disc_format(disc_info)
        if disc_format:
            log.info("Auto-detected disc format: %s", disc_format)

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
            media_type=getattr(args, "media_type", "auto"),
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

    # dvdcompare lookup with auto-release fallback
    release = getattr(args, "release", None)
    discs: list = []
    release_name = ""
    print("Looking up disc metadata on dvdcompare.net ...", file=sys.stderr)
    try:
        if release:
            # Explicit release specified, use it directly
            discs = await lookup_discs(canonical, disc_format=disc_format, release=release)
            release_name = release
        else:
            # Auto-detect: fetch the film, then pick the best release
            from dvdcompare.scraper import find_film
            film = await find_film(canonical, disc_format)
            discs, release_name = _auto_select_release(film, disc_info)
            if release_name:
                print(f"  Selected release: {release_name}", file=sys.stderr)
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

    output_dir = Path(output_val) / "_MakeMKV" / folder_base / disc_folder

    # Confirmation
    total_size = sum(t.size_bytes for t in rip_titles) / (1024 ** 3)
    rip_indices_str = ", ".join(str(t.index) for t in rip_titles)
    print(f"\nWill rip {len(rip_titles)} title(s) [{rip_indices_str}] ({total_size:.1f} GB)")
    print(f"Output: {output_dir}")

    if getattr(args, "dry_run", False):
        return 0

    if not getattr(args, "yes", False):
        try:
            answer = input("Proceed? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            return 1
        if answer and answer not in ("y", "yes"):
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

        def _progress_cb(progress, _last=last_pct):
            if progress.max_val > 0:
                pct = progress.current * 100 // progress.max_val
                if pct != _last[0]:
                    _last[0] = pct
                    bar_width = 30
                    filled = bar_width * pct // 100
                    bar = "=" * filled + ">" * (1 if filled < bar_width else 0) + " " * (bar_width - filled - 1)
                    elapsed = time.monotonic() - title_start
                    elapsed_str = _format_seconds(int(elapsed))
                    print(f"\r  [{bar}] {pct:3d}%  {elapsed_str}", end="", flush=True)

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


def main() -> None:
    # Backward compatibility: if the first arg isn't a known subcommand,
    # default to rip-guide (formerly plan).
    _SUBCOMMANDS = {"plan", "organize", "snapshot", "rip-guide", "rip"}
    if len(sys.argv) > 1 and sys.argv[1] not in _SUBCOMMANDS and sys.argv[1] != "-h" and sys.argv[1] != "--help":
        sys.argv.insert(1, "rip-guide")

    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    sys.exit(asyncio.run(_run(args)))


async def _run_organize(args: argparse.Namespace) -> int:
    """Run the organize workflow: scan, look up metadata, match, organize."""
    log_file = _setup_logging(verbose=getattr(args, "verbose", False))
    log.info("plex-planner organize: args=%s", vars(args))
    print(f"Debug log: {log_file}", file=sys.stderr)

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

    # Auto-detect media type from file durations when mode is "auto":
    # a feature-length main file (> 90 min) strongly suggests a movie.
    # 90 min chosen to clear HBO-style long episodes (~70-80 min) while
    # still catching the shortest typical movies (~100+ min).
    media_type = getattr(args, "media_type", "auto")
    if media_type == "auto":
        all_files = [f for d in scanned for f in d.files]
        if all_files:
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
    try:
        discs = await lookup_discs(
            dvdcompare_title,
            disc_format=disc_format,
            release=getattr(args, "release", "america"),
        )
        print(f"Found {len(discs)} disc(s) on dvdcompare.", file=sys.stderr)
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
    if dry_run:
        print("\n--- DRY RUN (use --execute to move files) ---\n")
    else:
        print("\n--- EXECUTING ---\n")
    for line in actions:
        print(line)

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
