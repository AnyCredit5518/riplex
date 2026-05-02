"""Rip output folder and manifest I/O.

Handles creating disc subfolder structures, scanning for ripped discs,
building rip manifests, and constructing ScannedDisc objects from
rip manifests (bypassing ffprobe).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from riplex.models import ScannedDisc, ScannedFile

if TYPE_CHECKING:
    from riplex.disc.makemkv import DiscInfo, RipResult

log = logging.getLogger(__name__)


def build_rip_path(
    canonical: str,
    year: int,
    disc_number: int | None = None,
) -> Path:
    """Build the output path for a rip, using config to resolve the base.

    Returns e.g. ``E:/Media/Rips/Batman Begins (2005)/Disc 1``.
    Falls back to ``{output_root}/Rips/{folder_base}`` if rip_output
    is not configured.
    """
    from riplex.config import get_output_root, get_rip_output

    folder_base = f"{canonical} ({year})"
    rip_output = get_rip_output()
    if rip_output:
        rip_root = Path(rip_output) / folder_base
    else:
        output_root = get_output_root()
        rip_root = Path(output_root) / "Rips" / folder_base

    if disc_number:
        return rip_root / f"Disc {disc_number}"
    return rip_root


def create_rip_folders(makemkv_root: Path, discs: list) -> list[Path]:
    """Create the recommended disc subfolder structure.

    Returns list of created directories.
    """
    created: list[Path] = []
    for disc in discs:
        folder = makemkv_root / f"Disc {disc.number}"
        if not folder.exists():
            folder.mkdir(parents=True, exist_ok=True)
            created.append(folder)
    return created


def find_ripped_discs(output_dir: Path) -> set[int]:
    """Scan output_dir for Disc N subdirectories with a _rip_manifest.json."""
    ripped: set[int] = set()
    if not output_dir.exists():
        return ripped
    for child in output_dir.iterdir():
        if child.is_dir() and (child / "_rip_manifest.json").exists():
            m = re.match(r"Disc\s+(\d+)", child.name, re.IGNORECASE)
            if m:
                ripped.add(int(m.group(1)))
    return ripped


def build_scanned_from_manifests(rip_root: Path) -> list[ScannedDisc]:
    """Build ScannedDisc objects from rip manifest files (skip ffprobe).

    Reads _rip_manifest.json from each Disc N subfolder and constructs
    ScannedFile objects using metadata captured at rip time.
    """
    discs: list[ScannedDisc] = []
    for child in sorted(rip_root.iterdir()):
        manifest_path = child / "_rip_manifest.json"
        if not child.is_dir() or not manifest_path.exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Failed to read manifest %s: %s", manifest_path, exc)
            continue

        files: list[ScannedFile] = []
        for entry in manifest.get("files", []):
            filename = entry.get("filename", "")
            if not filename:
                continue
            file_path = child / filename
            # Parse resolution into width/height
            res = entry.get("resolution", "")
            width, height = 0, 0
            if "x" in res:
                parts = res.split("x")
                try:
                    width, height = int(parts[0]), int(parts[1])
                except ValueError:
                    pass

            sf = ScannedFile(
                name=filename,
                path=str(file_path),
                duration_seconds=entry.get("duration", 0),
                size_bytes=entry.get("size_bytes", 0),
                stream_count=entry.get("stream_count", 0),
                stream_fingerprint=entry.get("stream_fingerprint", ""),
                chapter_count=entry.get("chapter_count", 0),
                chapter_durations=entry.get("chapter_durations", []),
                max_width=width,
                max_height=height,
                classification=entry.get("classification", ""),
            )
            files.append(sf)

        if files:
            discs.append(ScannedDisc(folder_name=child.name, files=files))

    return discs


# ---------------------------------------------------------------------------
# Manifest construction
# ---------------------------------------------------------------------------

def _classify_and_strip(
    title,
    all_titles: list,
    dvd_entries: list,
    is_movie: bool,
    movie_runtime: int | None,
    total_episode_runtime: int,
    episode_count: int,
) -> str:
    """Classify a disc title and strip the action suffix."""
    from riplex.disc.analysis import classify_title

    classification = classify_title(
        title, all_titles, dvd_entries,
        is_movie, movie_runtime,
        total_episode_runtime, episode_count,
    )
    if " - " in classification:
        classification = classification[:classification.rindex(" - ")]
    return classification


def build_rip_manifest(
    *,
    canonical: str,
    year: int,
    is_movie: bool,
    disc_number: int | None,
    volume_label: str,
    disc_format: str | None,
    release_name: str,
    disc_info: DiscInfo,
    rip_results: list[RipResult],
    dvd_entries: list,
    movie_runtime: int | None,
    total_episode_runtime: int,
    episode_count: int,
) -> dict:
    """Build the rip manifest dict from rip results.

    This is the canonical manifest builder used after ripping a disc.
    It probes chapter durations from the ripped files.
    """
    from riplex.disc.makemkv import build_stream_fingerprint, probe_chapter_durations

    manifest: dict = {
        "title": canonical,
        "year": year,
        "type": "movie" if is_movie else "tv",
        "disc_number": disc_number,
        "disc_label": volume_label,
        "format": disc_format,
        "release": release_name,
        "files": [],
    }
    for r in rip_results:
        if not r.success:
            continue
        t = next((t for t in disc_info.titles if t.index == r.title_index), None)
        classification = ""
        if t:
            classification = _classify_and_strip(
                t, disc_info.titles, dvd_entries,
                is_movie, movie_runtime,
                total_episode_runtime, episode_count,
            )
        manifest["files"].append({
            "filename": Path(r.output_file).name if r.output_file else "",
            "title_index": r.title_index,
            "duration": t.duration_seconds if t else 0,
            "resolution": t.resolution if t else "",
            "size_bytes": t.size_bytes if t else 0,
            "classification": classification,
            "stream_count": t.stream_count if t else 0,
            "stream_fingerprint": build_stream_fingerprint(t) if t else "",
            "chapter_count": t.chapters if t else 0,
            "chapter_durations": (
                probe_chapter_durations(r.output_file)
                if r.output_file else []
            ),
        })
    return manifest


def build_snapshot_manifest(
    *,
    canonical: str,
    year: int,
    is_movie: bool,
    disc_number: int,
    volume_label: str,
    disc_format: str | None,
    release_name: str,
    disc_info: DiscInfo,
    titles: list,
    dvd_entries: list,
    movie_runtime: int | None,
    total_episode_runtime: int,
    episode_count: int,
) -> dict:
    """Build a manifest dict from disc info without ripping.

    Used in snapshot mode to capture disc metadata for later replay.
    """
    from riplex.disc.makemkv import build_stream_fingerprint

    manifest: dict = {
        "title": canonical,
        "year": year,
        "type": "movie" if is_movie else "tv",
        "disc_number": disc_number,
        "disc_label": volume_label,
        "format": disc_format,
        "release": release_name,
        "files": [],
    }
    for t in titles:
        classification = _classify_and_strip(
            t, disc_info.titles, dvd_entries,
            is_movie, movie_runtime,
            total_episode_runtime, episode_count,
        )
        manifest["files"].append({
            "filename": f"{canonical.replace(' ', '_')}_t{t.index:02d}.mkv",
            "title_index": t.index,
            "duration": t.duration_seconds,
            "resolution": t.resolution,
            "size_bytes": t.size_bytes,
            "classification": classification,
            "stream_count": t.stream_count,
            "stream_fingerprint": build_stream_fingerprint(t),
            "chapter_count": t.chapters,
            "chapter_durations": [],
        })
    return manifest


def write_manifest(output_dir: Path, manifest: dict) -> Path:
    """Write a manifest dict to ``_rip_manifest.json`` and return the path."""
    manifest_path = output_dir / "_rip_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path
