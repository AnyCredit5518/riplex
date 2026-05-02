"""riplex rip command — single-disc rip with smart title selection."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from riplex.config import get_api_key, get_output_root, get_rip_output
from riplex.detect import infer_media_type
from riplex.disc.analysis import (
    build_dvd_entries,
    format_seconds,
    is_skip_title,
    print_disc_analysis,
    select_rippable_titles,
)
from riplex.disc.makemkv import (
    MakeMKV,
    find_makemkvcon,
    run_disc_info,
    run_rip,
)
from riplex.disc.provider import (
    detect_disc_format,
    detect_disc_number,
)
from riplex.lookup import lookup_metadata
from riplex.manifest import build_rip_manifest, build_rip_path, write_manifest
from riplex.metadata.sources.tmdb import TmdbProvider
from riplex.models import SearchRequest
from riplex.snapshot import (
    copy_debug_log,
    get_debug_dir,
    save_rip_manifest,
    save_rip_snapshot,
)
from riplex.title import parse_volume_label
from riplex.ui import prompt_confirm, prompt_text

from riplex_cli.formatting import (
    dry_run_banner,
    execute_hint,
    make_progress_callback,
    random_bar_style,
    setup_logging,
)

log = logging.getLogger(__name__)


async def run_rip(args: argparse.Namespace) -> int:
    """Read a disc, show analysis, and rip recommended titles."""
    log_file = setup_logging(verbose=getattr(args, "verbose", False))
    log.info("riplex rip: args=%s", vars(args))
    print(f"Debug log: {log_file}", file=sys.stderr)

    dry_run = not getattr(args, "execute", False)
    if dry_run:
        print(f"\n{dry_run_banner('rip')}\n")
    else:
        print("\n--- EXECUTING ---\n")

    if getattr(args, "no_cache", False):
        from riplex import cache
        cache.disable()

    # Find makemkvcon
    exe = find_makemkvcon()
    if not exe:
        print("Error: makemkvcon not found. Install MakeMKV or ensure makemkvcon is on PATH.", file=sys.stderr)
        return 1
    mkv = MakeMKV(exe)

    # Resolve drive
    drive_arg = getattr(args, "drive", "auto") or "auto"
    print("Scanning drives ...", file=sys.stderr)
    try:
        drive_info = mkv.resolve_drive(drive_arg)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    drive_idx = drive_info.index
    volume_label = drive_info.disc_label if drive_info.has_disc else None
    print(f"Found disc in drive {drive_info.index}: {drive_info.disc_label} ({drive_info.device})", file=sys.stderr)

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

    if volume_label is None:
        volume_label = disc_info.disc_name or ""

    # Auto-detect title from volume label if not provided
    title_arg = getattr(args, "title", None)
    if not title_arg:
        title_arg = parse_volume_label(volume_label)
        if title_arg:
            print(f"Auto-detected title from volume label: {title_arg}", file=sys.stderr)
            title_arg = prompt_text("Title", default=title_arg)
        else:
            print("Error: could not detect title from volume label. Provide a title argument.", file=sys.stderr)
            return 1

    # Auto-detect disc format from resolution if not provided
    disc_format = getattr(args, "disc_format", None)
    if not disc_format:
        disc_format = detect_disc_format(disc_info)
        if disc_format:
            log.info("Auto-detected disc format: %s", disc_format)

    # Infer media type from disc structure if not specified
    media_type_arg = getattr(args, "media_type", "auto")
    if media_type_arg == "auto":
        media_type_arg = infer_media_type(disc_info)
        if media_type_arg != "auto":
            log.info("Inferred media type from disc structure: %s", media_type_arg)

    # TMDb + dvdcompare lookup
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
        release = getattr(args, "release", None)
        print("Looking up disc metadata on dvdcompare.net ...", file=sys.stderr)
        meta = await lookup_metadata(
            request, provider,
            disc_format=disc_format,
            disc_info=disc_info,
            preferred_release=release,
        )
    except LookupError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error fetching TMDb metadata: {exc}", file=sys.stderr)
        return 1
    finally:
        await provider.close()

    canonical = meta.canonical
    year = meta.year
    is_movie = meta.is_movie
    movie_runtime = meta.movie_runtime
    discs = meta.discs
    release_name = meta.release_name

    if meta.dvdcompare_error:
        if isinstance(meta.dvdcompare_error, LookupError):
            print(f"Warning: {meta.dvdcompare_error}", file=sys.stderr)
        else:
            print(f"Warning: dvdcompare lookup failed ({type(meta.dvdcompare_error).__name__}).", file=sys.stderr)
    elif release_name:
        print(f"  Selected release: {release_name}", file=sys.stderr)

    # Show disc analysis
    print_disc_analysis(disc_info, discs, is_movie, movie_runtime)

    # Determine which titles to rip
    dvd_entries, total_episode_runtime, episode_count = build_dvd_entries(discs)

    if getattr(args, "titles", None):
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
        rip_titles = select_rippable_titles(
            disc_info, dvd_entries, is_movie, movie_runtime,
            total_episode_runtime, episode_count,
        )

    if not rip_titles:
        print("\nNo titles to rip.", file=sys.stderr)
        return 0

    # Output directory
    output_val = get_output_root(getattr(args, "output", None))
    if not output_val:
        print("Error: --output or output_root config required.", file=sys.stderr)
        return 1

    disc_number = detect_disc_number(disc_info, discs)
    if not disc_number:
        disc_number = 1
        if discs and len(discs) > 1:
            print(f"\nWarning: could not auto-detect disc number. Defaulting to 'Disc 1'.", file=sys.stderr)
            print("  Use --titles and manually organize if this is wrong.", file=sys.stderr)

    output_dir = build_rip_path(canonical, year, disc_number)

    # Confirmation
    total_size = sum(t.size_bytes for t in rip_titles) / (1024 ** 3)
    rip_indices_str = ", ".join(str(t.index) for t in rip_titles)
    print(f"\nWill rip {len(rip_titles)} title(s) [{rip_indices_str}] ({total_size:.1f} GB)")
    print(f"Output: {output_dir}")

    dry_run = not getattr(args, "execute", False)
    if dry_run:
        print(f"\n{execute_hint('rip')}")
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
              f"{format_seconds(t.duration_seconds)}, "
              f"{t.size_bytes / (1024**3):.1f} GB ...")

        title_start = time.monotonic()
        title_bytes = t.size_bytes

        rip_result = run_rip(
            drive_idx, t.index, output_dir,
            makemkvcon=exe,
            progress_callback=make_progress_callback(title_start, title_bytes),
        )

        elapsed = time.monotonic() - title_start
        print()  # newline after progress

        results.append(rip_result)
        if rip_result.success:
            print(f"  Done: {rip_result.output_file} ({format_seconds(int(elapsed))})")
        else:
            print(f"  FAILED: {rip_result.error_message}", file=sys.stderr)

    # Summary
    total_elapsed = time.monotonic() - rip_start
    succeeded = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    print(f"\n{'=' * 60}")
    print(f"Rip complete: {len(succeeded)} succeeded, {len(failed)} failed"
          f" ({format_seconds(int(total_elapsed))})")
    if succeeded:
        print(f"Output: {output_dir}")
    if failed:
        for r in failed:
            print(f"  FAILED title {r.title_index}: {r.error_message}", file=sys.stderr)

    # Write rip manifest
    if succeeded:
        manifest = build_rip_manifest(
            canonical=canonical,
            year=year,
            is_movie=is_movie,
            disc_number=disc_number,
            volume_label=volume_label,
            disc_format=disc_format,
            release_name=release_name,
            disc_info=disc_info,
            rip_results=results,
            dvd_entries=dvd_entries,
            movie_runtime=movie_runtime,
            total_episode_runtime=total_episode_runtime,
            episode_count=episode_count,
        )
        manifest_path = write_manifest(output_dir, manifest)
        log.info("Wrote rip manifest: %s", manifest_path)

        # Also write debug copies to _riplex/ folder
        debug_dir = get_debug_dir(output_dir.parent)
        save_rip_manifest(debug_dir, manifest)
        save_rip_snapshot(
            debug_dir, disc_info,
            canonical=canonical, year=year, is_movie=is_movie,
            movie_runtime=movie_runtime, release_name=release_name,
            discs=discs, ripped_titles=[t.index for t in rip_titles],
        )
        copy_debug_log(debug_dir)

    # Auto-organize
    if getattr(args, "auto_organize", False) and succeeded and not failed:
        from riplex_cli.commands.organize import run_organize

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
        return await run_organize(organize_args)

    return 1 if failed else 0
