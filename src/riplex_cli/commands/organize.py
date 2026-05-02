"""riplex organize command — scan and organize MKV files into Plex structure."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from riplex.config import get_api_key, get_archive_root, get_output_root
from riplex.dedup import find_all_redundant, remove_duplicates
from riplex.detect import detect_format, detect_incomplete, group_title_folders, infer_media_type_from_files
from riplex.lookup import lookup_metadata
from riplex.matcher import (
    collect_disc_targets,
    map_folders_to_discs,
    match_discs,
)
from riplex.metadata.sources.tmdb import TmdbProvider
from riplex.models import SearchRequest
from riplex.organizer import archive_source_folder, build_organize_plan, execute_plan
from riplex.scanner import scan_folder
from riplex.snapshot import (
    load as snapshot_load,
    load_organized_marker,
    save_from_scanned as snapshot_save_from_scanned,
    save_organized_marker,
)
from riplex.title import (
    infer_title_from_scanned,
    strip_year_from_title,
)
from riplex.ui import prompt_confirm, prompt_text

from riplex_cli.formatting import (
    dry_run_banner,
    execute_hint,
    setup_logging,
)

log = logging.getLogger(__name__)


async def run_organize(args: argparse.Namespace) -> int:
    """Run the organize workflow: scan, look up metadata, match, organize."""
    log_file = setup_logging(verbose=getattr(args, "verbose", False))
    log.info("riplex organize: args=%s", vars(args))
    print(f"Debug log: {log_file}", file=sys.stderr)

    dry_run = not getattr(args, "execute", False)
    if dry_run:
        print(f"\n{dry_run_banner('move files')}\n")
    else:
        print("\n--- EXECUTING ---\n")

    if getattr(args, "no_cache", False):
        from riplex import cache
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
            title, inferred_year = strip_year_from_title(folder.name)
            if inferred_year and not getattr(args, "year", None):
                args.year = inferred_year

        api_key = get_api_key(getattr(args, "api_key", None))
        try:
            provider = TmdbProvider(api_key=api_key)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        try:
            return await organize_with_scanned(
                scanned, title, args, output_root, provider,
                source_folder=folder,
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
        has_root_mkvs = any(folder.glob("*.mkv"))
        has_sub_mkvs = any(folder.glob("*/*.mkv"))

        if has_root_mkvs or (has_sub_mkvs and not any(folder.glob("*/*/*.mkv"))):
            if args.title:
                title = args.title
            else:
                title, inferred_year = strip_year_from_title(folder.name)
                if inferred_year and not getattr(args, "year", None):
                    args.year = inferred_year
            return await _organize_single(
                folder, title, args, output_root, provider,
            )
        elif has_sub_mkvs or any(folder.glob("*/*/*.mkv")):
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

        if len(group.folders) == 1:
            target_folder = group.folders[0]
        else:
            target_folder = group.folders[0]
            if all(f.parent == root for f in group.folders):
                pass  # handled below

        if args.title:
            title = args.title
        else:
            title, inferred_year = strip_year_from_title(group.title)
            if inferred_year and not getattr(args, "year", None):
                args.year = inferred_year

        if len(group.folders) == 1:
            rc = await _organize_single(
                target_folder, title, args, output_root, provider,
            )
        else:
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
    from riplex.models import ScannedDisc

    all_scanned: list[ScannedDisc] = []
    for folder in folders:
        print(f"Scanning {folder} ...", file=sys.stderr)
        try:
            scanned = scan_folder(folder)
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

    return await organize_with_scanned(
        all_scanned, title, args, output_root, provider,
        source_folder=folders[0].parent if folders else None,
    )


async def _organize_single(
    folder: Path,
    title: str,
    args: argparse.Namespace,
    output_root: Path,
    provider: TmdbProvider,
) -> int:
    """Organize a single rip folder."""
    # Check for organized marker (skip unless --force)
    if not getattr(args, "force", False):
        marker = load_organized_marker(folder)
        if marker:
            when = marker.organized_at[:10] if marker.organized_at else "unknown date"
            print(
                f"Already organized on {when} as \"{marker.title}\". "
                f"Use --force to re-organize.",
                file=sys.stderr,
            )
            return 0

    print(f"Scanning {folder} ...", file=sys.stderr)
    try:
        scanned = scan_folder(folder)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    snapshot_out = folder / f"{folder.name}.snapshot.json"
    if not snapshot_out.exists():
        snapshot_save_from_scanned(folder, scanned, snapshot_out)
        print(f"Snapshot saved to {snapshot_out}", file=sys.stderr)

    return await organize_with_scanned(
        scanned, title, args, output_root, provider,
        source_folder=folder,
    )


async def organize_with_scanned(
    scanned: list,
    title: str,
    args: argparse.Namespace,
    output_root: Path,
    provider: TmdbProvider,
    *,
    source_folder: Path | None = None,
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

    # Detect unusable files
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
        inferred = infer_title_from_scanned(scanned)
        if inferred and inferred.lower() != title.lower():
            log.debug("Title inferred from MKV title_tag: %r (was %r)", inferred, title)
            title = inferred
        title = prompt_text("Title", default=title)

    # Auto-detect media type from file durations
    media_type = getattr(args, "media_type", "auto")
    if media_type == "auto":
        media_type = infer_media_type_from_files(scanned)
        if media_type != "auto":
            log.debug("Auto-detected media_type=%r from file durations", media_type)

    # Look up TMDb + dvdcompare metadata
    try:
        request = SearchRequest(
            title=title,
            year=getattr(args, "year", None),
            media_type=media_type,
        )
        disc_format_arg = disc_format  # captured from detect_format above
        release = getattr(args, "release", None)
        print("Looking up disc metadata on dvdcompare.net ...", file=sys.stderr)
        meta = await lookup_metadata(
            request, provider,
            disc_format=disc_format_arg,
            preferred_release=release,
        )
    except LookupError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error fetching TMDb metadata: {exc}", file=sys.stderr)
        return 1

    print(f"TMDb: {meta.canonical} ({meta.year})", file=sys.stderr)

    if meta.dvdcompare_error:
        print(f"Error: dvdcompare lookup failed: {meta.dvdcompare_error}", file=sys.stderr)
        sys.exit(1)

    result = meta.planned
    discs = meta.discs
    print(f"Found {len(discs)} disc(s) on dvdcompare.", file=sys.stderr)

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
        print(f"\n{execute_hint('organize')}")

    # Tag organized files after successful execute
    if not dry_run:
        from riplex.tagger import tag_organized
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

        # Write organized marker to source folder
        if source_folder:
            move_count = len(org_plan.moves) + sum(
                len(s.chapter_destinations) for s in org_plan.splits
            )
            save_organized_marker(
                source_folder,
                title=title,
                file_count=move_count,
                output_root=str(output_root),
            )

        # Archive source folder if configured
        if source_folder:
            archive_root = get_archive_root()
            if archive_root and source_folder.exists():
                archive_dest = Path(archive_root) / source_folder.name
                if getattr(args, "auto", False):
                    result = archive_source_folder(source_folder, archive_root)
                    if result:
                        print(f"Archived: {source_folder} -> {result}", file=sys.stderr)
                else:
                    print(f"\nArchive rip folder to: {archive_dest}", file=sys.stderr)
                    if prompt_confirm("Move rip folder to archive?"):
                        result = archive_source_folder(source_folder, archive_root)
                        if result:
                            print(f"Archived: {source_folder} -> {result}", file=sys.stderr)

    return 0
