"""riplex organize command — scan and organize MKV files into Plex structure."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from riplex.config import get_api_key, get_archive_root, get_output_root
from riplex.dedup import find_all_redundant, remove_duplicates
from riplex.detect import detect_format, detect_incomplete, detect_organize_layout, infer_media_type_from_files
from riplex.lookup import lookup_metadata, resolve_disc_groups
from riplex.manifest import build_scanned_from_manifests
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
    parse_season_number,
    strip_year_from_title,
)
from riplex.ui import prompt_confirm, prompt_text

from riplex_cli.formatting import (
    dry_run_banner,
    execute_hint,
    setup_logging,
)

log = logging.getLogger(__name__)


def _has_complete_manifests(folder: Path) -> bool:
    """Return True if every direct subfolder containing MKVs also has a
    ``_rip_manifest.json`` (i.e. the folder was produced by ``riplex rip``).
    """
    subfolders_with_mkvs = [
        c for c in folder.iterdir()
        if c.is_dir() and any(c.glob("*.mkv"))
    ]
    if not subfolders_with_mkvs:
        return False
    return all((c / "_rip_manifest.json").exists() for c in subfolders_with_mkvs)


def _load_scanned(folder: Path, args: argparse.Namespace) -> list:
    """Load ScannedDisc list, preferring rip manifests when present.

    Re-probes via ffprobe when ``--rescan`` is set or when manifests are
    missing/incomplete.
    """
    if not getattr(args, "rescan", False) and _has_complete_manifests(folder):
        print(
            f"Loading rip manifests from {folder} (use --rescan to force ffprobe).",
            file=sys.stderr,
        )
        scanned = build_scanned_from_manifests(folder)
        if scanned:
            return scanned
        print("Manifests found but no usable entries; falling back to ffprobe scan.", file=sys.stderr)
    print(f"Scanning {folder} ...", file=sys.stderr)
    return scan_folder(folder)


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
        # Session marker takes priority over layout detection: a
        # ``_riplex_session.json`` in the folder means this was produced
        # by an orchestrate run and may span multiple work-folders. Fan
        # out to each work so a Psych-style release (TV series + linked
        # films on the same physical release) organizes into every
        # per-work Plex target in one pass.
        from riplex.manifest import SESSION_MARKER_NAME, read_session_marker

        marker = read_session_marker(folder)
        if marker is None and (folder / SESSION_MARKER_NAME).exists():
            log.warning("Session marker in %s is malformed; falling back to single-folder organize.", folder)

        if marker is not None:
            return await _organize_session_works(
                folder, marker, args, output_root, provider,
            )

        layout = detect_organize_layout(folder)

        if layout.mode == "single":
            if args.title:
                title = args.title
            else:
                title, inferred_year = strip_year_from_title(folder.name)
                if inferred_year and not getattr(args, "year", None):
                    args.year = inferred_year
            return await _organize_single(
                folder, title, args, output_root, provider,
            )
        elif layout.mode == "batch":
            return await _organize_batch(
                folder, args, output_root, provider,
            )
        else:
            print("No MKV files found.", file=sys.stderr)
            return 1
    finally:
        await provider.close()


async def _organize_session_works(
    folder: Path,
    marker: dict,
    args: argparse.Namespace,
    output_root: Path,
    provider: TmdbProvider,
) -> int:
    """Fan out organize across every work-folder in a session marker.

    The marker sitting in *folder* names every work-folder produced by a
    single orchestrate session (e.g. TV series + bonus-films disc from
    Psych: Complete Series). Each work is organized sequentially with
    its own title / year / media_type; missing sibling folders are
    logged and skipped so a partial rip can still land what's present.

    Returns the worst exit code across all works. Sibling archive and
    organized-marker writes happen inside each ``_organize_single``
    call (via ``organize_with_scanned``), so nothing extra is needed
    here.
    """
    import copy

    root = folder.parent
    release_name = marker.get("release_name", "")
    works_data = marker.get("works", [])

    if not works_data:
        print(
            f"Session marker in {folder} has no works. "
            "Falling back to single-folder organize.",
            file=sys.stderr,
        )
        title, inferred_year = strip_year_from_title(folder.name)
        if inferred_year and not getattr(args, "year", None):
            args.year = inferred_year
        return await _organize_single(folder, title, args, output_root, provider)

    print(
        f"\nSession marker in {folder.name}: {len(works_data)} work(s) "
        f"from release {release_name!r}",
        file=sys.stderr,
    )
    for w in works_data:
        print(
            f"  * {w.get('title', '?')} ({w.get('year', '?')}) "
            f"-> {w.get('folder', '?')}",
            file=sys.stderr,
        )

    overall_rc = 0
    for idx, w in enumerate(works_data, 1):
        work_title = w.get("title", "")
        work_year = w.get("year") or None
        work_media_type = w.get("media_type", "movie")
        work_folder_name = w.get("folder", "")

        if not work_folder_name or not work_title:
            print(
                f"  [{idx}/{len(works_data)}] SKIPPED: marker entry "
                f"missing title or folder.",
                file=sys.stderr,
            )
            overall_rc = max(overall_rc, 1)
            continue

        work_folder = root / work_folder_name
        print(f"\n{'=' * 60}", file=sys.stderr)
        print(
            f"[{idx}/{len(works_data)}] Organizing {work_title} "
            f"({work_year or '?'}) — {work_folder_name}",
            file=sys.stderr,
        )
        print(f"{'=' * 60}", file=sys.stderr)

        if not work_folder.exists():
            print(
                f"  Work folder does not exist: {work_folder}",
                file=sys.stderr,
            )
            print(
                f"  Skipping this work — nothing to organize.",
                file=sys.stderr,
            )
            continue

        # Per-work args: override title/year/media_type without mutating
        # the caller's Namespace.
        work_args = copy.copy(args)
        work_args.title = work_title
        work_args.year = work_year
        work_args.media_type = work_media_type

        rc = await _organize_single(
            work_folder, work_title, work_args, output_root, provider,
        )
        if rc != 0:
            overall_rc = max(overall_rc, rc)

    return overall_rc



async def _organize_batch(
    root: Path,
    args: argparse.Namespace,
    output_root: Path,
    provider: TmdbProvider,
) -> int:
    """Batch organize: auto-detect title groups and process each."""
    groups = detect_organize_layout(root).groups
    if not groups:
        print("No title groups found.", file=sys.stderr)
        return 1

    print(f"Batch mode: found {len(groups)} title group(s).", file=sys.stderr)
    for g in groups:
        folders = ", ".join(f.name for f in g.folders)
        print(f"  {g.title} ({len(g.folders)} folder(s): {folders})", file=sys.stderr)

    overall_rc = 0
    for i, group in enumerate(groups):
        requested_season = getattr(args, "season_number", None)
        if requested_season is not None and group.season_number is not None and requested_season != group.season_number:
            print(f"Skipping {group.title} Season {group.season_number:02d} (requested season {requested_season}).", file=sys.stderr)
            continue

        print(f"\n{'='*60}", file=sys.stderr)
        group_label = group.title
        if group.season_number is not None:
            group_label = f"{group.title} Season {group.season_number}"
        print(f"[{i+1}/{len(groups)}] {group_label}", file=sys.stderr)
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

        original_season = getattr(args, "season_number", None)
        if original_season is None and group.season_number is not None:
            args.season_number = group.season_number

        if len(group.folders) == 1:
            rc = await _organize_single(
                target_folder, title, args, output_root, provider,
            )
        else:
            rc = await _organize_multi_folder(
                group.folders, title, args, output_root, provider,
            )

        args.season_number = original_season

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
        try:
            scanned = _load_scanned(folder, args)
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

    try:
        scanned = _load_scanned(folder, args)
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

    if getattr(args, "season_number", None) is None and source_folder is not None:
        inferred_season = parse_season_number(source_folder.name)
        if inferred_season is not None:
            args.season_number = inferred_season
            log.debug("Inferred season_number=%s from folder name %r", inferred_season, source_folder.name)

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
            season_number=getattr(args, "season_number", None),
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

    unmatched_policy = getattr(args, "unmatched", "ignore")

    # Multi-work release: split into groups (TV series + bonus films,
    # etc.) and route each group to its own TMDb target. Mirrors the GUI's
    # Disc Overview flow. Returns [] for single-work releases so we fall
    # through to the legacy single-plan path.
    disc_groups = await resolve_disc_groups(meta, provider)
    if disc_groups:
        from riplex.organize_by_group import build_multi_group_plan

        print(
            f"\nRelease routes into {len(disc_groups)} group(s):",
            file=sys.stderr,
        )
        org_plan, group_plans = await build_multi_group_plan(
            scanned, discs, disc_groups, provider, output_root,
            request_defaults=request,
        )
        for gp in group_plans:
            if gp.skipped_reason:
                print(
                    f"  * {gp.label}: SKIPPED ({gp.skipped_reason})",
                    file=sys.stderr,
                )
            else:
                moves = len(gp.plan.moves) if gp.plan else 0
                splits = len(gp.plan.splits) if gp.plan else 0
                extra = f" +{splits} split" if splits else ""
                print(
                    f"  * {gp.label}: {moves} file(s) routed{extra}",
                    file=sys.stderr,
                )
        print(
            f"Merged plan: {len(org_plan.moves)} moves, "
            f"{len(org_plan.unmatched)} unmatched, "
            f"{len(org_plan.missing)} missing.",
            file=sys.stderr,
        )
    else:
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

        # Build organize plan. Key by absolute path so files with
        # colliding basenames across disc folders don't overwrite each
        # other in the lookup maps.
        file_map = {f.path: f.path for d in scanned for f in d.files}
        scanned_map = {f.path: f for d in scanned for f in d.files}
        targets = collect_disc_targets(discs, result) if discs else None
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
