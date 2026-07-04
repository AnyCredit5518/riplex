"""Rip output folder and manifest I/O.

Handles creating disc subfolder structures, scanning for ripped discs,
building rip manifests, and constructing ScannedDisc objects from
rip manifests (bypassing ffprobe).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    *,
    season_number: int | None = None,
) -> Path:
    """Build the output path for a rip, using config to resolve the base.

    Returns e.g. ``E:/Media/Rips/Batman Begins (2005)/Disc 1``, or for a
    TV rip with a known season number, ``E:/Media/Rips/Psych (2006)/
    Season 01/Disc 1``. Falls back to ``{output_root}/Rips/{folder_base}``
    if rip_output is not configured.

    Nesting TV rips under ``Season NN`` keeps rip folders for different
    seasons of the same show from colliding on the ``Disc N`` name.
    Movies (and TV rips without a known season) keep the flat layout.
    """
    from riplex.config import get_output_root, get_rip_output
    from riplex.normalize import sanitize_filename, season_folder_name

    folder_base = sanitize_filename(f"{canonical} ({year})")
    rip_output = get_rip_output()
    if rip_output:
        work_root = Path(rip_output) / folder_base
    else:
        output_root = get_output_root()
        work_root = Path(output_root) / "Rips" / folder_base

    if season_number is not None:
        rip_root = work_root / season_folder_name(season_number)
    else:
        rip_root = work_root

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


@dataclass
class SessionWork:
    """One work-folder inside a multi-work orchestrate session.

    Mirrors a DiscGroup: a work has a title, year, media_type, and the
    disc numbers (from the shared dvdcompare release) it owns. ``folder``
    is the leaf folder name under the rip output root (already
    sanitized); the caller resolves it against the root.

    ``source_id`` is the TMDb id in ``<media_type>:<id>`` form
    (e.g. ``tv:1447``). Persisted in the session marker so resume can
    hydrate a real ``MetadataSearchResult`` without re-running a
    fuzzy title search — organize needs it to fetch show/movie detail.
    """

    title: str
    year: int
    media_type: str  # "movie" or "tv"
    folder: str
    disc_numbers: list[int] = field(default_factory=list)
    source_id: str = ""


SESSION_MARKER_NAME = "_riplex_session.json"


def _session_root() -> Path:
    """Return the configured rip output root (or the legacy fallback)."""
    from riplex.config import get_output_root, get_rip_output

    rip_output = get_rip_output()
    if rip_output:
        return Path(rip_output)
    return Path(get_output_root()) / "Rips"


def write_session_marker(
    works: list[SessionWork],
    *,
    release_name: str,
) -> list[Path]:
    """Write ``_riplex_session.json`` into each work-folder of a session.

    Called once at orchestrate start, before any disc is ripped. The
    marker lets ``find_existing_session`` discover *sibling* folders on
    resume so a multi-work release (e.g. Psych: TV series + films disc)
    shows a unified queue of completed vs. remaining discs. Single-work
    releases still get a one-entry marker so resume behavior is uniform.

    Idempotent: overwrites any existing marker with the same works list.
    Missing folders are created. Returns the paths that were written.
    """
    root = _session_root()
    payload = {
        "type": "riplex_session",
        "release_name": release_name,
        "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "works": [
            {
                "title": w.title,
                "year": w.year,
                "media_type": w.media_type,
                "folder": w.folder,
                "disc_numbers": list(w.disc_numbers),
                "source_id": w.source_id,
            }
            for w in works
        ],
    }
    written: list[Path] = []
    for w in works:
        folder = root / w.folder
        folder.mkdir(parents=True, exist_ok=True)
        marker = folder / SESSION_MARKER_NAME
        try:
            marker.write_text(
                json.dumps(payload, indent=2), encoding="utf-8",
            )
            written.append(marker)
        except OSError as exc:
            log.warning("Failed to write session marker %s: %s", marker, exc)
    return written


def read_session_marker(folder: Path) -> dict | None:
    """Return the parsed session marker for ``folder`` or None."""
    marker = folder / SESSION_MARKER_NAME
    if not marker.exists():
        return None
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Failed to read session marker %s: %s", marker, exc)
        return None
    if data.get("type") != "riplex_session":
        return None
    return data


@dataclass
class ExistingSession:
    """Metadata recovered from an existing rip manifest on disk.

    ``works`` and ``all_ripped_discs`` are set when the recovered
    session had a ``_riplex_session.json`` marker naming sibling
    folders. ``works`` is empty and ``all_ripped_discs == ripped_discs``
    for legacy single-work sessions that predate the marker.

    ``source_id`` is the TMDb id for the resolved work in
    ``<media_type>:<id>`` form, read from the marker so resume can
    rebuild a real ``MetadataSearchResult`` without a fuzzy title
    search. Empty for legacy sessions written before the marker
    carried this field.
    """

    title: str
    year: int
    media_type: str  # "movie" or "tv"
    release_name: str
    disc_format: str | None
    rip_root: Path
    ripped_discs: set[int]
    works: list[SessionWork] = field(default_factory=list)
    all_ripped_discs: set[int] = field(default_factory=set)
    source_id: str = ""


_SEASON_FOLDER_RE = re.compile(r"^Season\s+\d+$", re.IGNORECASE)


def _iter_candidate_work_folders(root: Path):
    """Yield every folder that could hold a rip session, at any supported depth.

    The rip layout is either flat (``<root>/Psych (2006)/Disc N``) or
    season-nested (``<root>/Psych (2006)/Season 01/Disc N``). Callers
    that walk work-folders (``find_existing_session``) need to see both.

    Yields, for each top-level ``<root>/title/`` directory:
    * ``title/`` itself (for the flat layout and for legacy sessions
      whose marker still lives at the title root), and
    * each ``title/Season NN/`` subdirectory (for the nested TV layout).

    Skips ``_``-prefixed folders on either level.
    """
    if not root.exists():
        return
    for title_folder in root.iterdir():
        if not title_folder.is_dir() or title_folder.name.startswith("_"):
            continue
        yield title_folder
        for sub in title_folder.iterdir():
            if not sub.is_dir() or sub.name.startswith("_"):
                continue
            if _SEASON_FOLDER_RE.match(sub.name):
                yield sub


def find_existing_session(title: str) -> ExistingSession | None:
    """Scan the rip output root for a session matching *title*.

    A session matches if either:

    1. Some ``_rip_manifest.json`` under a work-folder has ``title`` equal
       to the requested title (case-insensitive), or
    2. Some ``_riplex_session.json`` marker lists a work whose ``title``
       matches — even if that work's folder doesn't yet contain any
       ripped discs. This lets resume work regardless of which physical
       disc from a multi-work release the user inserts first: the first
       disc of the first-ripped work writes markers into every sibling
       folder, so inserting any other work's disc later still resolves
       to the same session.

    When a session marker is present, ``all_ripped_discs`` aggregates
    every sibling folder's ``find_ripped_discs`` output so callers can
    present a unified resume queue. Legacy folders without a marker
    degrade to today's single-folder behavior.
    """
    root = _session_root()

    if not root.exists():
        return None

    title_lower = title.strip().lower()

    # --- Pass 1: match on any rip manifest's title. -------------------
    for title_folder in _iter_candidate_work_folders(root):
        primary_manifest: dict | None = None
        for disc_folder in title_folder.iterdir():
            manifest_path = disc_folder / "_rip_manifest.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if manifest.get("title", "").strip().lower() == title_lower:
                primary_manifest = manifest
                break
        if primary_manifest is None:
            continue

        ripped = find_ripped_discs(title_folder)
        works, all_ripped = _fan_out_marker(root, title_folder, ripped)

        # The marker (if present) knows this work's TMDb source_id;
        # look it up by matching the folder that we resolved from.
        source_id = ""
        for w in works:
            if w.folder and (root / w.folder) == title_folder:
                source_id = w.source_id
                break

        return ExistingSession(
            title=primary_manifest.get("title", ""),
            year=primary_manifest.get("year", 0),
            media_type=primary_manifest.get("type", "movie"),
            release_name=primary_manifest.get("release", ""),
            disc_format=primary_manifest.get("format"),
            rip_root=title_folder,
            ripped_discs=ripped,
            works=works,
            all_ripped_discs=all_ripped,
            source_id=source_id,
        )

    # --- Pass 2: match on any session marker's works[*].title. --------
    # Handles the case where the user has ripped one work of a multi-work
    # release (which wrote markers into every sibling) and then inserts
    # a disc from a sibling work whose folder has no rip manifest yet.
    for title_folder in _iter_candidate_work_folders(root):
        marker = read_session_marker(title_folder)
        if not marker:
            continue
        matching_work: dict | None = None
        for entry in marker.get("works", []):
            if entry.get("title", "").strip().lower() == title_lower:
                matching_work = entry
                break
        if matching_work is None:
            continue

        work_folder_name = matching_work.get("folder", "")
        work_folder = root / work_folder_name if work_folder_name else title_folder
        if not work_folder.exists():
            work_folder = title_folder  # marker's folder still counts as authoritative

        ripped = find_ripped_discs(work_folder)
        works, all_ripped = _fan_out_marker(root, work_folder, ripped, marker=marker)

        # Try to borrow disc_format from any sibling's rip manifest.
        # The marker itself doesn't carry it — but every work in the
        # session shares the same physical release, so any sibling's
        # first manifest is authoritative.
        disc_format: str | None = None
        for w in works:
            if not w.folder:
                continue
            sibling = root / w.folder
            if not sibling.exists():
                continue
            for disc_folder in sibling.iterdir():
                manifest_path = disc_folder / "_rip_manifest.json"
                if not manifest_path.exists():
                    continue
                try:
                    data = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                disc_format = data.get("format")
                break
            if disc_format:
                break

        return ExistingSession(
            title=matching_work.get("title", ""),
            year=matching_work.get("year", 0),
            media_type=matching_work.get("media_type", "movie"),
            release_name=marker.get("release_name", ""),
            disc_format=disc_format,
            rip_root=work_folder,
            ripped_discs=ripped,
            works=works,
            all_ripped_discs=all_ripped,
            source_id=matching_work.get("source_id", ""),
        )

    return None


def _fan_out_marker(
    root: Path,
    title_folder: Path,
    ripped: set[int],
    *,
    marker: dict | None = None,
) -> tuple[list[SessionWork], set[int]]:
    """Read the session marker in ``title_folder`` (or use the provided
    one) and aggregate every sibling work-folder's ripped discs.

    Returns ``(works, all_ripped)``. Legacy folders without a marker
    yield ``([], set(ripped))``.
    """
    if marker is None:
        marker = read_session_marker(title_folder)
    works: list[SessionWork] = []
    all_ripped: set[int] = set(ripped)
    if not marker:
        return works, all_ripped
    for entry in marker.get("works", []):
        w = SessionWork(
            title=entry.get("title", ""),
            year=entry.get("year", 0),
            media_type=entry.get("media_type", "movie"),
            folder=entry.get("folder", ""),
            disc_numbers=list(entry.get("disc_numbers", [])),
            source_id=entry.get("source_id", ""),
        )
        works.append(w)
        if not w.folder:
            continue
        sibling = root / w.folder
        if sibling == title_folder:
            continue
        all_ripped.update(find_ripped_discs(sibling))
    return works, all_ripped



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
