r"""Generate _rip_snapshot.json for existing rips in _MakeMKV folders.

Usage:
    py scripts/generate_rip_snapshots.py E:\Media\_MakeMKV\Dynasties [...]

Scans each folder's disc subdirectories, probes MKV files for metadata,
looks up TMDb, and writes a _rip_snapshot.json in each disc folder.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

# Ensure riplex is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from riplex.config import get_api_key
from riplex.metadata_sources.tmdb import TmdbProvider
from riplex.models import PlannedMovie, SearchRequest
from riplex.planner import plan
from riplex.scanner import scan_folder


def _parse_title_year(folder_name: str) -> tuple[str, int | None]:
    """Extract title and optional year from folder name like 'Frozen Planet II (2022)'."""
    m = re.match(r"^(.+?)\s*\((\d{4})\)\s*$", folder_name)
    if m:
        return m.group(1).strip(), int(m.group(2))
    return folder_name.strip(), None


def _resolution_str(width: int, height: int) -> str:
    if width and height:
        return f"{width}x{height}"
    return ""


async def generate_snapshot(folder: Path) -> None:
    """Generate _rip_snapshot.json files for all disc subfolders in a rip folder."""
    title_text, year = _parse_title_year(folder.name)
    print(f"\n{'=' * 60}")
    print(f"Processing: {folder.name}")
    print(f"  Title: {title_text}, Year: {year or 'unknown'}")

    # Determine disc layout: subfolders or flat
    disc_dirs = sorted(
        [d for d in folder.iterdir() if d.is_dir() and not d.name.startswith("_")],
        key=lambda d: d.name,
    )
    if not disc_dirs:
        # Flat layout (e.g. Earth - One Amazing Day)
        disc_dirs = [folder]

    # TMDb lookup
    api_key = get_api_key()
    provider = TmdbProvider(api_key=api_key)
    try:
        # Probe first disc to infer media type from file count
        first_disc_mkvs = sorted(disc_dirs[0].glob("*.mkv"))
        episode_count = sum(1 for _ in first_disc_mkvs)
        media_type = "tv" if episode_count >= 2 else "auto"

        request = SearchRequest(
            title=title_text,
            year=year,
            media_type=media_type,
        )
        result = await plan(request, provider)
        canonical = result.canonical_title
        tmdb_year = result.year
        is_movie = isinstance(result, PlannedMovie)
        movie_runtime = result.runtime_seconds if is_movie else None
        print(f"  TMDb: {canonical} ({tmdb_year}) [{'movie' if is_movie else 'tv'}]")
    except Exception as exc:
        print(f"  TMDb lookup failed: {exc}", file=sys.stderr)
        canonical = title_text
        tmdb_year = year
        is_movie = True
        movie_runtime = None
    finally:
        await provider.close()

    # Process each disc directory
    for disc_dir in disc_dirs:
        snapshot_path = disc_dir / "_rip_snapshot.json"
        if snapshot_path.exists():
            print(f"  Skipping {disc_dir.name}: _rip_snapshot.json already exists")
            continue

        mkv_files = sorted(disc_dir.glob("*.mkv"))
        if not mkv_files:
            print(f"  Skipping {disc_dir.name}: no MKV files")
            continue

        # Parse disc number from folder name
        disc_match = re.search(r"Disc\s*(\d+)", disc_dir.name, re.IGNORECASE)
        disc_number = int(disc_match.group(1)) if disc_match else None

        # Scan files for metadata
        scanned = scan_folder(disc_dir)
        titles = []
        for disc_group in scanned:
            for i, f in enumerate(disc_group.files):
                # Extract title index from filename (e.g. _t00, _t01)
                idx_match = re.search(r"_t(\d+)", f.name)
                title_idx = int(idx_match.group(1)) if idx_match else i

                titles.append({
                    "index": title_idx,
                    "duration_seconds": f.duration_seconds,
                    "resolution": _resolution_str(f.max_width, f.max_height),
                    "size_bytes": f.size_bytes,
                    "chapters": f.chapter_count or None,
                })

        # Detect format from resolution
        disc_format = None
        for t in titles:
            if t["resolution"] and "3840" in t["resolution"]:
                disc_format = "Blu-ray 4K"
                break
        if disc_format is None and titles:
            disc_format = "Blu-ray"

        snapshot = {
            "disc_name": disc_dir.name if disc_dir != folder else folder.name,
            "drive": "N/A (retroactive)",
            "title_count": len(titles),
            "titles": titles,
            "tmdb": {
                "canonical_title": canonical,
                "year": tmdb_year,
                "type": "movie" if is_movie else "tv",
                "movie_runtime": movie_runtime,
            },
            "dvdcompare": {
                "release": "",
                "disc_count": len(disc_dirs),
                "discs": [],
            },
            "ripped_titles": [t["index"] for t in titles],
            "retroactive": True,
        }

        snapshot_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        print(f"  Wrote: {snapshot_path}")
        print(f"    {len(titles)} title(s), format={disc_format}")
        for t in titles:
            dur_m = t["duration_seconds"] // 60
            dur_s = t["duration_seconds"] % 60
            size_gb = t["size_bytes"] / (1024 ** 3)
            print(f"    t{t['index']:02d}: {dur_m}:{dur_s:02d}, {size_gb:.1f} GB, {t['resolution']}")


async def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <folder> [<folder> ...]", file=sys.stderr)
        sys.exit(1)

    folders = [Path(f) for f in sys.argv[1:]]
    for folder in folders:
        if not folder.is_dir():
            print(f"Error: not a directory: {folder}", file=sys.stderr)
            continue
        await generate_snapshot(folder)

    print(f"\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
