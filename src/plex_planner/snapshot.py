"""Capture and load folder snapshots for offline debugging and testing.

A snapshot is a JSON file containing the full metadata of a scanned folder
(durations, streams, chapters, file sizes) without any actual media data.
This lets users share their folder layout for bug reports, and lets
developers replay real scenarios in dry-run mode.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from plex_planner.models import ScannedDisc, ScannedFile
from plex_planner.scanner import scan_folder

log = logging.getLogger(__name__)

SNAPSHOT_VERSION = 1


def capture(folder: Path) -> dict:
    """Scan *folder* and return a snapshot dict ready for JSON serialization."""
    discs = scan_folder(folder)

    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "created": datetime.now(timezone.utc).isoformat(),
        "source_folder": str(folder),
        "groups": [
            {
                "folder_name": disc.folder_name,
                "files": [
                    _file_to_dict(f) for f in disc.files
                ],
            }
            for disc in discs
        ],
    }


def save(folder: Path, output: Path) -> Path:
    """Scan *folder*, write a snapshot JSON to *output*, return the path."""
    data = capture(folder)
    output.write_text(json.dumps(data, indent=2), encoding="utf-8")
    log.info("Snapshot saved: %s (%d group(s), %d file(s))",
             output, len(data["groups"]),
             sum(len(g["files"]) for g in data["groups"]))
    return output


def load(snapshot_path: Path) -> list[ScannedDisc]:
    """Load a snapshot JSON and return ScannedDisc objects.

    File paths in the returned objects are synthetic (relative to the
    snapshot's original source folder) since the actual files don't exist.
    """
    raw = json.loads(snapshot_path.read_text(encoding="utf-8"))

    version = raw.get("snapshot_version", 0)
    if version != SNAPSHOT_VERSION:
        raise ValueError(
            f"Unsupported snapshot version {version} (expected {SNAPSHOT_VERSION})"
        )

    discs: list[ScannedDisc] = []
    for group in raw["groups"]:
        files = [_dict_to_file(f) for f in group["files"]]
        discs.append(ScannedDisc(folder_name=group["folder_name"], files=files))

    log.info("Loaded snapshot: %s (%d group(s), %d file(s))",
             snapshot_path, len(discs),
             sum(len(d.files) for d in discs))
    return discs


def _file_to_dict(f: ScannedFile) -> dict:
    """Serialize a ScannedFile to a plain dict, keeping only metadata."""
    return {
        "name": f.name,
        "duration_seconds": f.duration_seconds,
        "size_bytes": f.size_bytes,
        "stream_count": f.stream_count,
        "stream_fingerprint": f.stream_fingerprint,
        "chapter_count": f.chapter_count,
        "chapter_durations": f.chapter_durations,
        "title_tag": f.title_tag,
        "max_width": f.max_width,
        "max_height": f.max_height,
        "organized_tag": f.organized_tag,
        "perceptual_hash": f.perceptual_hash,
    }


def _dict_to_file(d: dict) -> ScannedFile:
    """Deserialize a dict back into a ScannedFile.

    The ``path`` field is set to a synthetic value since the real file
    doesn't exist on the machine loading the snapshot.
    """
    return ScannedFile(
        name=d["name"],
        path=d["name"],  # synthetic; real path doesn't exist
        duration_seconds=d.get("duration_seconds", 0),
        size_bytes=d.get("size_bytes", 0),
        stream_count=d.get("stream_count", 0),
        stream_fingerprint=d.get("stream_fingerprint", ""),
        chapter_count=d.get("chapter_count", 0),
        chapter_durations=d.get("chapter_durations", []),
        title_tag=d.get("title_tag"),
        max_width=d.get("max_width", 0),
        max_height=d.get("max_height", 0),
        organized_tag=d.get("organized_tag"),
        perceptual_hash=d.get("perceptual_hash"),
    )
