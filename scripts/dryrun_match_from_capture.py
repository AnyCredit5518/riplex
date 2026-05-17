"""Dry-run match demo against a capture fixture.

Loads dvdcompare + tmdb + riplex-rip snapshots from a capture folder,
classifies the rip titles the same way ``riplex rip`` would, then runs
the *organize-time* matcher against synthetic ScannedFile objects so
you can see the new tighter cap + classification-honoring logic in
action without touching any real files.

Usage:
    py scripts/dryrun_match_from_capture.py \\
        "_captures/Back_to_the_Future_Part_III_1990/Disc 1" \\
        --release 2 \\
        --disc 5 \\
        --runtime-seconds 7080
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from riplex.disc.analysis import build_dvd_entries, classify_title  # noqa: E402
from riplex.disc.provider import _convert_release  # noqa: E402
from riplex.matcher import collect_disc_targets, match_discs  # noqa: E402
from riplex.models import (  # noqa: E402
    PlannedMovie,
    ScannedDisc,
    ScannedFile,
)


class _Title:
    def __init__(self, index, duration_seconds, resolution, size_bytes, chapters):
        self.index = index
        self.duration_seconds = duration_seconds
        self.resolution = resolution
        self.size_bytes = size_bytes
        self.chapter_count = chapters
        self.name = f"t{index:02d}.mkv"


def _ns(obj):
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: _ns(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [_ns(x) for x in obj]
    return obj


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("capture", help="Path to a capture folder (Disc N).")
    ap.add_argument("--release", type=int, default=2,
                    help="1-based dvdcompare release index (default: 2).")
    ap.add_argument("--disc", type=int, default=None,
                    help="Only include this dvc disc number (default: all film discs).")
    ap.add_argument("--folder-name", default="Disc 5",
                    help="ScannedDisc folder_name (default: 'Disc 5').")
    ap.add_argument("--runtime-seconds", type=int, default=7080,
                    help="Movie runtime in seconds (default: 7080 = BTTF III).")
    args = ap.parse_args()

    cap = Path(args.capture)
    rip_snap = _load(cap / "riplex-rip.snapshot.json")
    dvdc_snap = _load(cap / "dvdcompare.snapshot.json")
    tmdb_snap = _load(cap / "tmdb.snapshot.json")

    picked = tmdb_snap.get("picked") or {}
    title = picked.get("title", "Unknown")
    year = picked.get("year") or 0
    plan = PlannedMovie(
        canonical_title=title,
        year=year,
        runtime=f"{args.runtime_seconds // 60}m",
        runtime_seconds=args.runtime_seconds,
    )

    releases = dvdc_snap.get("film", {}).get("releases") or []
    if not releases:
        print("ERROR: dvdcompare snapshot has no releases.")
        return 1
    rel_idx = args.release - 1
    if rel_idx < 0 or rel_idx >= len(releases):
        print(f"ERROR: --release {args.release} out of range (1..{len(releases)})")
        return 1
    rel = releases[rel_idx]
    print(f"Release: [{args.release}] {rel.get('name', '?')}  "
          f"({rel.get('year', '?')}) - {len(rel.get('discs', []))} disc(s)")

    if args.disc is not None:
        rel = dict(rel)
        rel["discs"] = [d for d in rel["discs"] if d["number"] == args.disc]
        if not rel["discs"]:
            print(f"ERROR: --disc {args.disc} not present in release.")
            return 1

    discs = _convert_release(_ns(rel))
    dvd_entries, total_ep_runtime, ep_count = build_dvd_entries(discs)

    titles_raw = rip_snap["data"]["titles"]
    titles = [
        _Title(
            index=t["index"],
            duration_seconds=t["duration_seconds"],
            resolution=t.get("resolution", ""),
            size_bytes=t.get("size_bytes", 0),
            chapters=t.get("chapters", 0),
        )
        for t in titles_raw
    ]

    classifications = {}
    for t in titles:
        classifications[t.index] = classify_title(
            t, titles, dvd_entries,
            is_movie=True,
            movie_runtime=plan.runtime_seconds,
            total_episode_runtime=total_ep_runtime,
            episode_count=ep_count,
        )

    scanned_files = [
        ScannedFile(
            name=f"{args.folder_name}_t{t.index:02d}.mkv",
            path=f"(synthetic)/{args.folder_name}/t{t.index:02d}.mkv",
            duration_seconds=t.duration_seconds,
            size_bytes=t.size_bytes,
            chapter_count=t.chapter_count,
            classification=classifications[t.index],
        )
        for t in titles
    ]
    scanned = [ScannedDisc(folder_name=args.folder_name, files=scanned_files)]

    targets = collect_disc_targets(discs, plan)
    result = match_discs(scanned, discs, plan)

    print(f"\nPlan: {plan.canonical_title} ({plan.year})  "
          f"runtime={plan.runtime_seconds}s")
    print(f"PlannedDiscs: {len(discs)}  targets: {len(targets)}  "
          f"titles: {len(titles)}")

    print("\nRIP-TIME CLASSIFICATION (cached on each ScannedFile):")
    for t in titles:
        cls = classifications[t.index]
        marker = ""
        if cls.startswith(("Unmatched content", "Unknown content", "Very short")):
            marker = "  <-- 'unidentified' (blocks loose extras claim)"
        print(f"  t{t.index:02d}  {t.duration_seconds:>5}s  "
              f"{t.resolution:10s}  {cls}{marker}")

    print(f"\nORGANIZE MATCH RESULT:")
    print(f"  matched   = {len(result.matched)}")
    print(f"  unmatched = {len(result.unmatched)}")
    print(f"  missing   = {len(result.missing)}")

    print("\nMATCHED (sorted by delta):")
    for c in sorted(result.matched, key=lambda c: c.delta_seconds):
        print(f"  [{c.confidence:6s} \u00B1{c.delta_seconds:>4}s]  "
              f"{c.file_name:30s} -> {c.matched_label}  "
              f"({c.file_duration_seconds}s vs {c.matched_runtime_seconds}s)")

    if result.unmatched:
        print("\nUNMATCHED:")
        for f in result.unmatched:
            print(f"  {f.name:30s} {f.duration_seconds:>5}s  "
                  f"[{f.classification}]")

    if result.missing:
        print("\nMISSING TARGETS:")
        for label in result.missing:
            print(f"  {label}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
