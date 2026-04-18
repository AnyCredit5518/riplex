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
from plex_planner.formatter import to_json, to_text
from plex_planner.matcher import (
    collect_disc_targets,
    format_match_report,
    map_folders_to_discs,
    match_discs,
    match_files,
    parse_duration,
)
from plex_planner.metadata_sources.tmdb import TmdbProvider
from plex_planner.models import SearchRequest
from plex_planner.organizer import build_organize_plan, execute_plan
from plex_planner.planner import plan
from plex_planner.scanner import scan_folder

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

    # --- plan (default / legacy) ---
    plan_parser = subs.add_parser("plan", help="Look up metadata and output a plan.")
    _add_plan_args(plan_parser)

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

    return parser


def _add_plan_args(parser: argparse.ArgumentParser) -> None:
    """Add the plan-mode arguments to a parser."""
    parser.add_argument(
        "title",
        nargs="?",
        help="Movie or TV show title to look up.",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help="Release year (strongly recommended for accuracy).",
    )
    parser.add_argument(
        "--type",
        dest="media_type",
        choices=["movie", "tv", "auto"],
        default="auto",
        help="Force media type. Default: auto-detect.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output as JSON instead of human-readable text.",
    )
    parser.add_argument(
        "--no-specials",
        action="store_true",
        default=False,
        help="Exclude specials (Season 00) for TV shows.",
    )
    parser.add_argument(
        "--no-extras",
        action="store_true",
        default=False,
        help="Omit recommended extras folder skeleton.",
    )
    parser.add_argument(
        "--match",
        nargs="+",
        metavar="FILE:DURATION",
        help=(
            "Match ripped files by duration. Format: filename:duration "
            "(e.g. title_t00.mkv:48m12s title_t01.mkv:47m58s)"
        ),
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="TMDb API key (or set TMDB_API_KEY env var, or config file).",
    )


def _parse_match_args(match_args: list[str]) -> list[tuple[str, int]]:
    """Parse --match arguments into (filename, seconds) tuples."""
    files: list[tuple[str, int]] = []
    for arg in match_args:
        if ":" not in arg:
            print(f"Warning: skipping invalid match arg '{arg}' (expected file:duration)", file=sys.stderr)
            continue
        # Split on last colon to handle filenames with colons (unlikely on Windows)
        idx = arg.rfind(":")
        name = arg[:idx]
        dur_str = arg[idx + 1 :]
        seconds = parse_duration(dur_str)
        if seconds <= 0:
            print(f"Warning: could not parse duration for '{arg}'", file=sys.stderr)
            continue
        files.append((name, seconds))
    return files


async def _run(args: argparse.Namespace) -> int:
    if args.command == "organize":
        return await _run_organize(args)
    return await _run_plan(args)


async def _run_plan(args: argparse.Namespace) -> int:
    if not args.title:
        print("Error: title is required for plan mode.", file=sys.stderr)
        return 1

    api_key = get_api_key(args.api_key)
    try:
        provider = TmdbProvider(api_key=api_key)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    request = SearchRequest(
        title=args.title,
        year=args.year,
        media_type=args.media_type,
        include_specials=not args.no_specials,
        include_extras_skeleton=not args.no_extras,
    )

    try:
        result = await plan(request, provider)
    except LookupError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error fetching metadata: {exc}", file=sys.stderr)
        return 1
    finally:
        await provider.close()

    if args.json:
        print(to_json(result))
    else:
        print(to_text(result))

    # Optional matching
    if args.match:
        ripped = _parse_match_args(args.match)
        if ripped:
            candidates = match_files(ripped, result)
            print()
            print(format_match_report(candidates))

    return 0


def main() -> None:
    # Backward compatibility: if the first arg isn't a known subcommand,
    # treat as the legacy "plan" invocation.
    _SUBCOMMANDS = {"plan", "organize"}
    if len(sys.argv) > 1 and sys.argv[1] not in _SUBCOMMANDS and sys.argv[1] != "-h" and sys.argv[1] != "--help":
        sys.argv.insert(1, "plan")

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

    # Detect incomplete files
    incomplete = detect_incomplete(scanned)
    if incomplete:
        print(f"Warning: {len(incomplete)} file(s) appear incomplete (still ripping?):", file=sys.stderr)
        for f in incomplete:
            print(f"  {f.name} (0 duration / no streams)", file=sys.stderr)
        # Remove incomplete files from scanned
        incomplete_paths = {f.path for f in incomplete}
        for disc in scanned:
            disc.files = [f for f in disc.files if f.path not in incomplete_paths]
        total_files = sum(len(d.files) for d in scanned)
        if total_files == 0:
            print("No complete MKV files found.", file=sys.stderr)
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

    # Look up TMDb metadata
    try:
        request = SearchRequest(
            title=title,
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

    print(f"TMDb: {result.canonical_title} ({result.year})", file=sys.stderr)

    # Look up dvdcompare disc metadata
    if disc_format == "DVD":
        print("Note: DVD format detected. dvdcompare does not support DVD releases; skipping disc metadata lookup.", file=sys.stderr)
        discs = []
    else:
        print("Looking up disc metadata on dvdcompare.net ...", file=sys.stderr)
        try:
            discs = await lookup_discs(
                title,
                disc_format=disc_format,
                release=getattr(args, "release", "america"),
            )
            print(f"Found {len(discs)} disc(s) on dvdcompare.", file=sys.stderr)
        except LookupError as exc:
            print(f"Warning: dvdcompare lookup failed: {exc}", file=sys.stderr)
            print("Proceeding without disc metadata.", file=sys.stderr)
            discs = []

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
