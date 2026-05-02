"""riplex lookup command — disc contents and metadata preview."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from riplex.config import get_api_key, get_output_root, get_rip_output
from riplex.disc.analysis import (
    build_dvd_entries,
    classify_title,
    format_seconds,
    is_skip_title,
    print_disc_analysis,
)
from riplex.disc.provider import (
    detect_disc_format,
    fetch_and_select_release,
    lookup_discs,
)
from riplex.lookup import lookup_metadata
from riplex.manifest import create_rip_folders
from riplex.metadata.sources.tmdb import TmdbProvider
from riplex.models import SearchRequest
from riplex.ui import prompt_text

from riplex_cli.formatting import setup_logging

log = logging.getLogger(__name__)


def _disc_role(disc, is_movie: bool) -> str:
    """Return a short role label for a disc in the folder listing."""
    if disc.is_film:
        return " (main film)"
    if is_movie:
        if disc.extras or disc.episodes:
            return " (extras)"
        return ""
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
            print(f"Main feature runtime: {format_seconds(movie_runtime)}")
        print("Tip: rip all titles and use 'riplex organize' to sort them.")
        return

    print(f"\nDisc contents ({len(discs)} disc(s)):")
    print("-" * 60)

    play_all_tips: list[str] = []

    for disc in discs:
        fmt_str = f" [{disc.disc_format}]" if disc.disc_format else ""
        role_tag = " ** MAIN FILM **" if disc.is_film else ""
        print(f"\n  Disc {disc.number}{fmt_str}{role_tag}")

        if disc.is_film and movie_runtime:
            print(f"    The Film: {format_seconds(movie_runtime)}")

        items = disc.episodes + disc.extras

        if not items and disc.is_film:
            continue

        has_episodes = bool(disc.episodes)
        has_extras = bool(disc.extras)

        episodes_are_extras = is_movie and has_episodes and not disc.is_film

        if has_episodes and not episodes_are_extras:
            total_ep_runtime = sum(e.runtime_seconds for e in disc.episodes)
            print(f"    Episodes ({len(disc.episodes)}, total {format_seconds(total_ep_runtime)}):")
            for ep in disc.episodes:
                rt = format_seconds(ep.runtime_seconds) if ep.runtime_seconds else "?"
                print(f"      {ep.title} ({rt})")
            play_all_tips.append(
                f"Disc {disc.number}: has {len(disc.episodes)} episodes "
                f"(total {format_seconds(total_ep_runtime)}). "
                f"If MakeMKV shows a single title with {len(disc.episodes)} "
                f"or more chapters totaling ~{format_seconds(total_ep_runtime)}, "
                f"that is the play-all. You can rip just that one title; "
                f"riplex will split it by chapters."
            )
        elif episodes_are_extras:
            total_ep_runtime = sum(e.runtime_seconds for e in disc.episodes)
            print(f"    Extras - play-all group ({len(disc.episodes)} items, total {format_seconds(total_ep_runtime)}):")
            for ep in disc.episodes:
                rt = format_seconds(ep.runtime_seconds) if ep.runtime_seconds else "?"
                print(f"      {ep.title} ({rt})")

        if has_extras:
            total_extra_runtime = sum(e.runtime_seconds for e in disc.extras)
            print(f"    Extras ({len(disc.extras)}, total {format_seconds(total_extra_runtime)}):")
            for extra in disc.extras:
                rt = format_seconds(extra.runtime_seconds) if extra.runtime_seconds else "?"
                ftype = f" [{extra.feature_type}]" if extra.feature_type else ""
                print(f"      {extra.title} ({rt}){ftype}")

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
        print(f"    riplex will match each by runtime to its dvdcompare entry.")

    if total_features > 0:
        print(f"  - {total_features} total feature(s) across {len(discs)} disc(s).")

    print(f"  - After ripping, run: riplex organize \"{folder_base}\"")


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



async def run_lookup(args: argparse.Namespace) -> int:
    """Look up disc contents and metadata for a title from TMDb and dvdcompare."""
    log_file = setup_logging(verbose=getattr(args, "verbose", False))
    log.info("riplex lookup: args=%s", vars(args))
    print(f"Debug log: {log_file}", file=sys.stderr)

    if getattr(args, "no_cache", False):
        from riplex import cache
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
        meta = await lookup_metadata(request, provider, skip_dvdcompare=True)
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

    # Look up dvdcompare disc metadata
    disc_format = getattr(args, "disc_format", None)
    release = getattr(args, "release", "america")
    dvdcompare_title = canonical
    print("Looking up disc metadata on dvdcompare.net ...", file=sys.stderr)
    discs: list = []
    try:
        discs = await lookup_discs(dvdcompare_title, disc_format=disc_format, release=release, year=year)
    except LookupError:
        print("Warning: no dvdcompare data found. Guide will be limited to TMDb info.", file=sys.stderr)
    except Exception as exc:
        print(f"Warning: dvdcompare lookup failed ({type(exc).__name__}). Guide will be limited to TMDb info.", file=sys.stderr)

    # Live disc analysis via makemkvcon
    drive_arg = getattr(args, "drive", None)
    disc_info = None
    if drive_arg is not None:
        from riplex.disc.makemkv import (
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
                drive_idx = drive_arg

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
        print_disc_analysis(disc_info, discs, is_movie, movie_runtime)

    # Optionally create folders
    if getattr(args, "create_folders", False) and discs:
        output_val = get_output_root(getattr(args, "output", None))
        if not output_val:
            print("Error: --output or output_root config required for --create-folders.", file=sys.stderr)
            return 1
        rip_output = get_rip_output()
        makemkv_root = Path(rip_output) / f"{canonical} ({year})" if rip_output else Path(output_val) / "Rips" / f"{canonical} ({year})"
        created = create_rip_folders(makemkv_root, discs)
        if created:
            print(f"\nCreated {len(created)} folder(s) under {makemkv_root}")
            for p in created:
                print(f"  {p}")

    return 0
