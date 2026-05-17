"""Interactive disc-fixture capture tool (dev only).

Walks a single inserted disc through the disc-read → TMDb pick →
dvdcompare pick pipeline, writing three snapshot files into a
per-disc folder under ``--output-root`` (default: ``./_captures/``).

This is **not** a user-facing feature. It's a developer utility for
collecting raw inputs that can later be curated into ``tests/fixtures/``
disc-analysis fixtures.

Output per run::

    <output-root>/<slug>/Disc <N>/
        riplex-rip.snapshot.json    # disc titles + selection (phase="capture")
        tmdb.snapshot.json          # TMDb search query + chosen result + all results
        dvdcompare.snapshot.json    # dvdcompare search + chosen URL + full film data

Usage::

    python scripts/capture_fixture.py
    python scripts/capture_fixture.py --drive 0 --title "Dunkirk" --year 2017
    python scripts/capture_fixture.py --output-root ./_captures --force
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dvdcompare.scraper import BASE_URL as DVDC_BASE_URL
from dvdcompare.scraper import get_film_by_url, search as dvdc_search

from riplex import config
from riplex.disc.makemkv import (
    DiscInfo,
    DriveInfo,
    MakeMKV,
    find_makemkvcon,
)
from riplex.metadata.sources.tmdb import TmdbProvider
from riplex.snapshot import save_rip_snapshot

DEFAULT_OUTPUT_ROOT = Path("./_captures")
SNAPSHOT_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Interactive helpers
# ---------------------------------------------------------------------------

def _prompt(message: str, default: str = "") -> str:
    """Prompt with a default. Empty input returns default."""
    suffix = f" [{default}]" if default else ""
    raw = input(f"{message}{suffix}: ").strip()
    return raw or default


def _prompt_choice(message: str, options: list[str], default_index: int = 0) -> int:
    """Numbered-list prompt. Returns the chosen index (0-based)."""
    if not options:
        raise ValueError("No options to choose from")
    print(message)
    for i, opt in enumerate(options, start=1):
        marker = " *" if (i - 1) == default_index else "  "
        print(f"{marker}{i:>3}. {opt}")
    while True:
        raw = input(f"Choose [1-{len(options)}, default {default_index + 1}]: ").strip()
        if not raw:
            return default_index
        try:
            idx = int(raw) - 1
        except ValueError:
            print("  Not a number, try again.")
            continue
        if 0 <= idx < len(options):
            return idx
        print(f"  Out of range, must be 1..{len(options)}.")


def _slugify(text: str) -> str:
    """Filesystem-safe slug."""
    text = re.sub(r"[^\w\s.-]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "_", text.strip())
    return text or "unknown"


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def _pick_drive(makemkv: MakeMKV, drive_arg: str | None) -> DriveInfo:
    """Resolve the target drive: --drive override, else first drive with a disc."""
    drives = makemkv.drive_list()
    drives_with_disc = [d for d in drives if d.has_disc]

    if drive_arg is not None:
        try:
            target_index = int(drive_arg)
        except ValueError:
            # Allow letter like "D:" — match by device
            target_index = -1
            for d in drives:
                if d.device.upper().startswith(drive_arg.upper().rstrip(":")):
                    target_index = d.index
                    break
            if target_index < 0:
                raise SystemExit(f"No drive matches '{drive_arg}'.")
        for d in drives:
            if d.index == target_index:
                if not d.has_disc:
                    raise SystemExit(f"Drive {drive_arg} has no disc loaded.")
                return d
        raise SystemExit(f"No drive with index {drive_arg}.")

    if not drives_with_disc:
        raise SystemExit(
            "No optical drives with a disc detected. "
            "Insert a disc and re-run, or pass --drive."
        )
    if len(drives_with_disc) == 1:
        d = drives_with_disc[0]
        print(f"Using drive {d.index}: {d.state_label} ({d.device})")
        return d
    options = [f"{d.index}: {d.state_label} ({d.device})" for d in drives_with_disc]
    idx = _prompt_choice("Multiple drives with discs:", options)
    return drives_with_disc[idx]


def _disc_info_to_dict(disc_info: DiscInfo) -> dict:
    """Convert DiscInfo to a JSON-safe dict matching rip-snapshot title shape."""
    return {
        "disc_name": disc_info.disc_name,
        "disc_type": disc_info.disc_type,
        "title_count": len(disc_info.titles),
        "titles": [
            {
                "index": t.index,
                "name": t.name,
                "duration_seconds": t.duration_seconds,
                "chapters": t.chapters,
                "size_bytes": t.size_bytes,
                "filename": t.filename,
                "playlist": t.playlist,
                "resolution": t.resolution,
                "video_codec": t.video_codec,
                "audio_tracks": list(t.audio_tracks),
                "subtitle_tracks": list(t.subtitle_tracks),
                "stream_count": t.stream_count,
                "segment_count": t.segment_count,
            }
            for t in disc_info.titles
        ],
    }


async def _run_tmdb_search(query: str, year: int | None, media_type: str) -> tuple[list, dict] | None:
    """Search TMDb. Returns (results_list, raw_query_meta) or None if no API key."""
    api_key = config.get_api_key(None)
    if not api_key:
        print("WARN: no TMDb API key configured; skipping TMDb lookup.")
        return None
    provider = TmdbProvider(api_key=api_key)
    try:
        results = await provider.search(query, year=year, media_type=media_type)  # type: ignore[arg-type]
    finally:
        await provider.close()
    return results, {"query": query, "year": year, "media_type": media_type}


def _pick_tmdb_result(results: list) -> Any | None:
    """Numbered picker over TMDb search results. Returns None if user skips."""
    if not results:
        print("No TMDb results.")
        return None
    options = [
        f"{r.title} ({r.year or '?'}) [{r.media_type}] — {r.source_id}"
        for r in results
    ]
    options.append("<skip TMDb / leave unmatched>")
    idx = _prompt_choice("TMDb results:", options)
    if idx == len(options) - 1:
        return None
    return results[idx]


def _pick_dvdcompare_result(search_results: list) -> Any | None:
    """Numbered picker over dvdcompare search results."""
    if not search_results:
        print("No dvdcompare results.")
        return None
    options = [f"{r.title} — {r.url}" for r in search_results]
    options.append("<skip dvdcompare>")
    idx = _prompt_choice("dvdcompare results:", options)
    if idx == len(options) - 1:
        return None
    return search_results[idx]


# ---------------------------------------------------------------------------
# Snapshot writers
# ---------------------------------------------------------------------------

def _write_rip_snapshot(out_dir: Path, disc_info: DiscInfo, *,
                       canonical: str, year: int | None,
                       is_movie: bool, release_name: str) -> Path:
    """Write riplex-rip.snapshot.json via the existing helper."""
    p = save_rip_snapshot(
        out_dir,
        disc_info,
        canonical=canonical,
        year=year,
        is_movie=is_movie,
        movie_runtime=None,
        release_name=release_name,
        discs=None,
        ripped_titles=[],
        selected_titles=[],
        phase="capture",
    )
    if p is None:
        raise SystemExit("Failed to write rip snapshot")
    return p


def _write_tmdb_snapshot(out_dir: Path, *, query_meta: dict,
                         picked: Any | None, all_results: list) -> Path:
    """Write tmdb.snapshot.json."""
    payload = {
        "snapshot_version": SNAPSHOT_SCHEMA_VERSION,
        "type": "tmdb",
        "created": datetime.now(timezone.utc).isoformat(),
        "query": query_meta,
        "picked": dataclasses.asdict(picked) if picked is not None else None,
        "all_results": [dataclasses.asdict(r) for r in all_results],
    }
    p = out_dir / "tmdb.snapshot.json"
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return p


def _write_dvdcompare_snapshot(out_dir: Path, *, search_text: str,
                               picked_url: str | None,
                               all_results: list, film: Any | None) -> Path:
    """Write dvdcompare.snapshot.json."""
    payload = {
        "snapshot_version": SNAPSHOT_SCHEMA_VERSION,
        "type": "dvdcompare",
        "created": datetime.now(timezone.utc).isoformat(),
        "search_text": search_text,
        "picked_url": picked_url,
        "base_url": DVDC_BASE_URL,
        "all_results": [
            {"title": r.title, "url": r.url} for r in all_results
        ],
        "film": dataclasses.asdict(film) if film is not None else None,
    }
    p = out_dir / "dvdcompare.snapshot.json"
    p.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--drive", help="Drive index (0, 1, ...) or letter (D:). "
                    "Default: auto-detect first drive with a disc.")
    ap.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT,
                    help=f"Where to write captures. Default: {DEFAULT_OUTPUT_ROOT}")
    ap.add_argument("--title", help="Pre-fill canonical title.")
    ap.add_argument("--year", type=int, help="Pre-fill year.")
    ap.add_argument("--type", choices=["movie", "tv", "auto"], default="auto",
                    help="Pre-fill media type. Default: auto.")
    ap.add_argument("--disc-number", type=int, help="Pre-fill disc number (default 1).")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing capture folder.")
    args = ap.parse_args(argv)

    # --- Step 1: find makemkvcon -------------------------------------------
    exe = find_makemkvcon()
    if exe is None:
        print("ERROR: makemkvcon not found on PATH.", file=sys.stderr)
        return 2
    makemkv = MakeMKV(exe)

    # --- Step 2: pick a drive ----------------------------------------------
    print("\n=== Step 1/7: Detecting drives ===")
    drive = _pick_drive(makemkv, args.drive)

    # --- Step 3: read the disc ---------------------------------------------
    print(f"\n=== Step 2/7: Reading disc on drive {drive.index} ({drive.device}) ===")
    print("(this may take a minute...)")
    disc_info = makemkv.disc_info(drive.index)
    print(f"Disc: {disc_info.disc_name}  ({disc_info.disc_type})")
    print(f"Titles found: {len(disc_info.titles)}")

    # --- Step 4: confirm title/year/type/disc# -----------------------------
    print("\n=== Step 3/7: Confirm title metadata ===")
    default_title = args.title or disc_info.disc_name or "Unknown"
    canonical = _prompt("Canonical title", default_title)
    year_str = _prompt("Year (blank for none)", str(args.year) if args.year else "")
    year = int(year_str) if year_str.isdigit() else None
    media_type = _prompt("Type [movie|tv|auto]", args.type)
    if media_type not in {"movie", "tv", "auto"}:
        media_type = "auto"
    disc_num_str = _prompt("Disc number", str(args.disc_number or 1))
    disc_number = int(disc_num_str) if disc_num_str.isdigit() else 1

    # --- Step 5: TMDb search + pick ----------------------------------------
    print("\n=== Step 4/7: TMDb search ===")
    tmdb_picked = None
    tmdb_all: list = []
    tmdb_query_meta: dict = {"query": canonical, "year": year, "media_type": media_type}
    tmdb_search_text = _prompt("TMDb search text", canonical)
    tmdb_query_meta["query"] = tmdb_search_text
    try:
        tmdb_result = asyncio.run(_run_tmdb_search(tmdb_search_text, year, media_type))
    except Exception as exc:
        print(f"WARN: TMDb search failed: {exc}")
        tmdb_result = None
    if tmdb_result is not None:
        tmdb_all, tmdb_query_meta = tmdb_result
        tmdb_picked = _pick_tmdb_result(tmdb_all)
        if tmdb_picked is not None:
            canonical = tmdb_picked.title
            if tmdb_picked.year:
                year = tmdb_picked.year
            media_type = tmdb_picked.media_type

    is_movie = (media_type == "movie") or (media_type == "auto" and (tmdb_picked is None or tmdb_picked.media_type == "movie"))

    # --- Step 6: dvdcompare search + pick ----------------------------------
    print("\n=== Step 5/7: dvdcompare search ===")
    dvdc_search_text = _prompt("dvdcompare search text", canonical)
    try:
        dvdc_results = asyncio.run(dvdc_search(dvdc_search_text))
    except Exception as exc:
        print(f"WARN: dvdcompare search failed: {exc}")
        dvdc_results = []
    dvdc_picked = _pick_dvdcompare_result(dvdc_results) if dvdc_results else None

    # --- Step 7: fetch full film -------------------------------------------
    film = None
    picked_url = None
    if dvdc_picked is not None:
        print("\n=== Step 6/7: Fetching full dvdcompare film ===")
        url = dvdc_picked.url
        if not url.startswith("http"):
            picked_url = f"{DVDC_BASE_URL.rstrip('/')}/{url.lstrip('/')}"
        else:
            picked_url = url
        try:
            film = asyncio.run(get_film_by_url(picked_url))
            release_count = len(getattr(film, "releases", []) or [])
            film_title = getattr(film, "title", "?")
            print(f"Fetched film: {film_title} (releases={release_count})")
        except Exception as exc:
            print(f"WARN: failed to fetch film: {exc}")
            film = None

    # --- Step 8: write snapshots -------------------------------------------
    print("\n=== Step 7/7: Writing snapshots ===")
    slug = _slugify(f"{canonical}_{year}" if year else canonical)
    out_dir = args.output_root / slug / f"Disc {disc_number}"
    if out_dir.exists() and not args.force:
        print(f"ERROR: {out_dir} already exists. Pass --force to overwrite.",
              file=sys.stderr)
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)

    release_name = ""
    if film is not None and getattr(film, "releases", None):
        # Pick first release as the "release name" hint; user can edit later.
        first = film.releases[0]
        release_name = getattr(first, "name", "") or getattr(first, "title", "") or ""

    rip_path = _write_rip_snapshot(
        out_dir, disc_info,
        canonical=canonical, year=year, is_movie=is_movie,
        release_name=release_name,
    )
    tmdb_path = _write_tmdb_snapshot(
        out_dir, query_meta=tmdb_query_meta,
        picked=tmdb_picked, all_results=tmdb_all,
    )
    dvdc_path = _write_dvdcompare_snapshot(
        out_dir, search_text=dvdc_search_text,
        picked_url=picked_url, all_results=dvdc_results, film=film,
    )

    print(f"\nWrote:\n  {rip_path}\n  {tmdb_path}\n  {dvdc_path}")
    print(f"\nDone. Capture folder: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
