"""riplex orchestrate command — multi-disc rip and organize pipeline."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from riplex.config import get_api_key, get_archive_root, get_output_root, get_rip_output
from riplex.detect import infer_media_type
from riplex.disc.analysis import (
    build_dvd_entries,
    format_seconds,
    is_skip_title,
    print_disc_analysis,
    select_rippable_titles,
)
from riplex.disc.provider import (
    detect_disc_format,
    detect_disc_number,
    disc_content_summary,
)
from riplex.lookup import lookup_metadata
from riplex.manifest import (
    build_rip_manifest,
    build_rip_path,
    build_scanned_from_manifests,
    build_snapshot_manifest,
    find_ripped_discs,
    write_manifest,
)
from riplex.metadata.sources.tmdb import TmdbProvider
from riplex.models import SearchRequest
from riplex.title import parse_volume_label
from riplex.ui import is_interactive, prompt_choice, prompt_confirm, prompt_text

from riplex_cli.formatting import (
    build_execute_command,
    dry_run_banner,
    make_progress_callback,
    random_bar_style,
    setup_logging,
)

log = logging.getLogger(__name__)


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
        summary = disc_content_summary(disc)
        status = ""
        if disc.number in ripped_discs:
            status = "  [RIPPED]"
        elif disc.number == inserted_disc:
            status = "  [INSERTED]"
        fmt_str = f" ({fmt})" if fmt else ""
        print(f"  Disc {disc.number}{fmt_str}: {summary}{status}")
    print()


async def run_orchestrate(args: argparse.Namespace) -> int:
    """Multi-disc rip and organize pipeline."""
    from riplex.disc.makemkv import (
        eject_disc,
        find_makemkvcon,
        run_disc_info,
        run_drive_list,
        run_rip,
        wait_for_disc,
    )

    log_file = setup_logging(verbose=getattr(args, "verbose", False))
    log.info("riplex orchestrate: args=%s", vars(args))
    print(f"Debug log: {log_file}", file=sys.stderr)

    snapshot_mode = getattr(args, "snapshot", False)
    dry_run = not getattr(args, "execute", False) and not snapshot_mode
    if snapshot_mode:
        print("\n--- SNAPSHOT MODE (scan + write manifest, no rip) ---\n")
    elif dry_run:
        print(f"\n{dry_run_banner('rip and organize')}\n")
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
            disc_info = None
        elif len(active) > 1 and is_interactive():
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
            disc_info = None
        else:
            selected = active[0]
            print(f"Found disc in drive {selected.index}: {selected.disc_label} ({selected.device})", file=sys.stderr)
            drive_idx = selected.index
            drive_device = selected.device
            volume_label = selected.disc_label
            disc_info = None
    else:
        try:
            drive_idx = int(drive_arg)
        except ValueError:
            drive_idx = drive_arg
        volume_label = None
        disc_info = None
        drive_device = ""
        for d in drives:
            if d.index == drive_idx or d.device == drive_arg:
                drive_device = d.device
                break

    # Read initial disc info
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
        title_arg = parse_volume_label(volume_label)
        if title_arg:
            print(f"Auto-detected title from volume label: {title_arg}", file=sys.stderr)
            title_arg = prompt_text("Title", default=title_arg)
        else:
            print("Error: could not detect title from volume label. Provide --title.", file=sys.stderr)
            return 1

    # Auto-detect disc format
    disc_format = getattr(args, "disc_format", None)
    if not disc_format:
        disc_format = detect_disc_format(disc_info)
        if disc_format:
            log.info("Auto-detected disc format: %s", disc_format)

    # Infer media type
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

    print(f"TMDb: {canonical} ({year})", file=sys.stderr)

    if meta.dvdcompare_error:
        if isinstance(meta.dvdcompare_error, LookupError):
            print(f"Error: dvdcompare lookup failed: {meta.dvdcompare_error}", file=sys.stderr)
        else:
            print(f"Error: dvdcompare lookup failed ({type(meta.dvdcompare_error).__name__}): {meta.dvdcompare_error}", file=sys.stderr)
        return 1

    if not discs:
        print("Error: no disc metadata found on dvdcompare.", file=sys.stderr)
        return 1

    # Output directory
    output_val = get_output_root(getattr(args, "output", None))
    if not output_val:
        print("Error: --output or output_root config required.", file=sys.stderr)
        return 1

    folder_base = f"{canonical} ({year})"  # noqa: kept for display/logging
    rip_root = build_rip_path(canonical, year)

    # Detect which disc is currently inserted
    current_disc_num = detect_disc_number(disc_info, discs)

    # Resume: detect already-ripped discs from manifest files
    ripped_discs = find_ripped_discs(rip_root)

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
        unripped = [d for d in disc_order if d.number not in ripped_discs]
        if len(unripped) > 1:
            from riplex.ui import prompt_multi_select
            options = []
            for d in unripped:
                summary = disc_content_summary(d)
                fmt = d.disc_format if hasattr(d, "disc_format") and d.disc_format else ""
                fmt_str = f" ({fmt})" if fmt else ""
                options.append(f"Disc {d.number}{fmt_str}: {summary}")
            selected_indices = prompt_multi_select(
                "Which discs do you want to rip?",
                options,
                defaults=list(range(len(options))),
            )
            if selected_indices is not None:
                selected_discs = [unripped[i] for i in selected_indices]
                disc_order = [d for d in disc_order if d.number in ripped_discs] + selected_discs

    # Start from the inserted disc if possible
    if current_disc_num:
        start_disc = next((d for d in disc_order if d.number == current_disc_num), None)
        remaining = [d for d in disc_order if d.number != current_disc_num]
        disc_order = ([start_disc] if start_disc else []) + remaining

    for disc_idx, disc in enumerate(disc_order):
        if disc.number in ripped_discs:
            continue

        need_insert = (disc_idx > 0) or (current_disc_num != disc.number)

        if need_insert and not dry_run:
            summary = disc_content_summary(disc)
            fmt = disc.disc_format if hasattr(disc, "disc_format") and disc.disc_format else ""
            fmt_str = f" ({fmt})" if fmt else ""
            print(f"\n{'=' * 60}")
            print(f"Insert Disc {disc.number}{fmt_str}: {summary}")
            print(f"{'=' * 60}")

            if is_interactive():
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
            detected = detect_disc_number(disc_info, discs)
            if detected and detected != disc.number:
                print(f"Warning: expected Disc {disc.number} but detected Disc {detected}.", file=sys.stderr)
                if not prompt_confirm("Continue anyway?"):
                    continue

        # Prompt: rip, skip, or finish
        if not dry_run and not snapshot_mode:
            summary = disc_content_summary(disc)
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

        is_current_disc = (disc.number == current_disc_num)
        output_dir = rip_root / f"Disc {disc.number}"

        if dry_run and not is_current_disc:
            summary = disc_content_summary(disc)
            fmt = disc.disc_format if hasattr(disc, "disc_format") and disc.disc_format else ""
            fmt_str = f" ({fmt})" if fmt else ""
            print(f"\nDisc {disc.number}{fmt_str}: {summary}")
            print(f"  Would prompt for insertion and rip to: {output_dir}")
            ripped_discs.add(disc.number)
            continue

        # Show disc analysis for the currently-inserted disc
        current_disc_entries = [d for d in discs if d.number == disc.number]
        dvd_entries, total_episode_runtime, episode_count = build_dvd_entries(current_disc_entries)
        print_disc_analysis(disc_info, current_disc_entries, is_movie, movie_runtime)

        # Filter titles to rip
        rip_titles = select_rippable_titles(
            disc_info, dvd_entries, is_movie, movie_runtime,
            total_episode_runtime, episode_count,
        )

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
            manifest = build_snapshot_manifest(
                canonical=canonical,
                year=year,
                is_movie=is_movie,
                disc_number=disc.number,
                volume_label=volume_label,
                disc_format=disc_format,
                release_name=release_name,
                disc_info=disc_info,
                titles=rip_titles,
                dvd_entries=dvd_entries,
                movie_runtime=movie_runtime,
                total_episode_runtime=total_episode_runtime,
                episode_count=episode_count,
            )
            manifest_path = write_manifest(output_dir, manifest)
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
            print()

            results.append(rip_result)
            if rip_result.success:
                print(f"  Done: {rip_result.output_file} ({format_seconds(int(elapsed))})")
            else:
                print(f"  FAILED: {rip_result.error_message}", file=sys.stderr)
                any_failed = True

        # Disc rip summary
        total_elapsed = time.monotonic() - rip_start
        succeeded = [r for r in results if r.success]
        failed = [r for r in results if not r.success]

        print(f"\nDisc {disc.number}: {len(succeeded)} succeeded, {len(failed)} failed"
              f" ({format_seconds(int(total_elapsed))})")

        # Write rip manifest
        if succeeded:
            manifest = build_rip_manifest(
                canonical=canonical,
                year=year,
                is_movie=is_movie,
                disc_number=disc.number,
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

    if dry_run and not rip_root.exists():
        print(f"\n{'=' * 60}")
        print("Organize phase (skipped in dry-run, no ripped files yet)")
        print(f"{'=' * 60}")
        print(f"\nRe-run with --execute to rip and organize:\n  {build_execute_command()}")
        return 0

    print(f"\n{'=' * 60}")
    print("Organize phase")
    print(f"{'=' * 60}")

    from riplex_cli.commands.organize import run_organize, organize_with_scanned

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
        auto=True,
    )

    # Optimization: build ScannedDisc objects from manifest data (avoids ffprobe)
    scanned_from_manifest = build_scanned_from_manifests(rip_root)
    if scanned_from_manifest:
        log.info(
            "Using manifest data for organize (%d discs, skip ffprobe scan)",
            len(scanned_from_manifest),
        )
        print("Using rip manifest data (skipping ffprobe scan).", file=sys.stderr)
        api_key = get_api_key(getattr(args, "api_key", None))
        provider = TmdbProvider(api_key=api_key)
        try:
            org_result = await organize_with_scanned(
                scanned_from_manifest, canonical, organize_args,
                Path(output_val), provider,
            )
        finally:
            await provider.close()
    else:
        org_result = await run_organize(organize_args)

    if dry_run:
        print(f"\nRe-run with --execute to rip and organize:\n  {build_execute_command()}")

    # ---- Archive phase ----
    if not dry_run and org_result == 0:
        archive_root = get_archive_root()
        if archive_root and rip_root.exists():
            from riplex.organizer import archive_source_folder
            archive_dest = Path(archive_root) / folder_base
            if is_interactive():
                print(f"\nArchive rip folder to: {archive_dest}", file=sys.stderr)
                if prompt_confirm("Move rip folder to archive?"):
                    result = archive_source_folder(rip_root, archive_root)
                    if result:
                        print(f"Archived: {rip_root} -> {result}", file=sys.stderr)
            else:
                result = archive_source_folder(rip_root, archive_root)
                if result:
                    print(f"Archived: {rip_root} -> {result}", file=sys.stderr)

    return org_result if not any_failed else 1
