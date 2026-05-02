"""Scan MakeMKV rip folders and extract MKV metadata via ffprobe."""

from __future__ import annotations

import json
import logging
import platform
import subprocess
from pathlib import Path
from typing import Callable

from riplex.dedup import compute_dhash
from riplex.models import ScannedDisc, ScannedFile

log = logging.getLogger(__name__)

# On Windows, prevent subprocess calls from spawning a visible console window.
_SUBPROCESS_FLAGS: dict = (
    {"creationflags": subprocess.CREATE_NO_WINDOW}
    if platform.system() == "Windows"
    else {}
)


def _probe_file(path: Path) -> ScannedFile:
    """Extract metadata from a single MKV file using ffprobe.

    Returns a populated :class:`ScannedFile` with duration, size, stream
    fingerprint, and chapter count.  Falls back to zero/empty values on error.
    """
    name = path.name
    abs_path = str(path)

    # Get file size directly (fast, no subprocess)
    try:
        size_bytes = path.stat().st_size
    except OSError:
        size_bytes = 0

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_entries",
                "format=duration,nb_streams"
                ":stream=codec_type,codec_name,width,height,channels"
                ":stream_tags=language"
                ":format_tags=title,RIPLEX,PLEX_PLANNER",
                "-show_chapters",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            **_SUBPROCESS_FLAGS,
        )
        if result.returncode != 0:
            return ScannedFile(name=name, path=abs_path, size_bytes=size_bytes)

        data = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return ScannedFile(name=name, path=abs_path, size_bytes=size_bytes)

    # Duration
    try:
        duration = int(float(data["format"]["duration"]))
    except (KeyError, ValueError):
        duration = 0

    # Stream count
    try:
        stream_count = int(data["format"]["nb_streams"])
    except (KeyError, ValueError):
        stream_count = 0

    # Format tags (title, organized marker)
    format_tags = data.get("format", {}).get("tags", {})
    title_tag = format_tags.get("title") or format_tags.get("TITLE")
    organized_tag = (
        format_tags.get("RIPLEX") or format_tags.get("riplex")
        or format_tags.get("PLEX_PLANNER") or format_tags.get("plex_planner")
    )

    # Stream fingerprint: compact string describing the stream layout
    fingerprint_parts: list[str] = []
    max_width = 0
    max_height = 0
    for s in data.get("streams", []):
        ct = s.get("codec_type", "?")
        cn = s.get("codec_name", "?")
        lang = s.get("tags", {}).get("language", "")
        if ct == "video":
            w = s.get("width", 0)
            h = s.get("height", 0)
            if w > max_width:
                max_width = w
            if h > max_height:
                max_height = h
            fingerprint_parts.append(f"{cn}:{w}x{h}")
        elif ct == "audio":
            ch = s.get("channels", 0)
            fingerprint_parts.append(f"{cn}:{lang}:{ch}ch")
        elif ct == "subtitle":
            fingerprint_parts.append(f"sub:{lang}")
    fingerprint = "|".join(fingerprint_parts)

    # Chapters
    chapters_raw = data.get("chapters", [])
    chapter_count = len(chapters_raw)
    chapter_durations: list[int] = []
    for ch in chapters_raw:
        try:
            ch_dur = float(ch["end_time"]) - float(ch["start_time"])
            chapter_durations.append(round(ch_dur))
        except (KeyError, ValueError):
            chapter_durations.append(0)

    phash = compute_dhash(abs_path, duration)

    sf = ScannedFile(
        name=name,
        path=abs_path,
        duration_seconds=duration,
        size_bytes=size_bytes,
        stream_count=stream_count,
        stream_fingerprint=fingerprint,
        chapter_count=chapter_count,
        chapter_durations=chapter_durations,
        title_tag=title_tag,
        max_width=max_width,
        max_height=max_height,
        organized_tag=organized_tag,
        perceptual_hash=phash,
    )
    log.debug(
        "Probed %s: %ds, %d streams, fp=%s, %d chapters, chd=%s, title=%s, res=%dx%d",
        name, duration, stream_count, fingerprint, chapter_count, chapter_durations,
        title_tag, max_width, max_height,
    )
    return sf


def scan_folder(
    folder: Path,
    *,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> list[ScannedDisc]:
    """Scan a MakeMKV rip folder and return disc groupings with durations.

    Handles both flat layouts (all MKVs in one folder) and multi-disc
    layouts (subfolders per disc like "Special Features/", "Disc 1/").

    *on_progress*, if provided, is called as ``on_progress(current, total, filename)``
    after each file is probed.

    Returns a list of :class:`ScannedDisc` objects, one per subfolder
    (or one for the root if files are at the top level).
    """
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"Not a directory: {folder}")

    # Check for ffprobe availability
    try:
        subprocess.run(
            ["ffprobe", "-version"],
            capture_output=True,
            timeout=5,
            **_SUBPROCESS_FLAGS,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "ffprobe not found. Install FFmpeg to enable MKV duration scanning."
        )

    log.debug("Scanning folder: %s", folder)

    # Collect MKVs at the root level
    root_mkvs = sorted(folder.glob("*.mkv"))

    # Collect MKVs in immediate subfolders
    subfolders: dict[str, list[Path]] = {}
    for sub in sorted(folder.iterdir()):
        if sub.is_dir() and not sub.name.startswith("_"):
            mkvs = sorted(sub.glob("*.mkv"))
            if mkvs:
                subfolders[sub.name] = mkvs

    discs: list[ScannedDisc] = []

    # Count total files for progress reporting
    all_files = list(root_mkvs)
    for mkvs in subfolders.values():
        all_files.extend(mkvs)
    total = len(all_files)
    scanned_count = 0

    # Root-level files become disc group with folder name
    if root_mkvs:
        files = []
        for p in root_mkvs:
            files.append(_probe_file(p))
            scanned_count += 1
            if on_progress:
                on_progress(scanned_count, total, p.name)
        discs.append(ScannedDisc(folder_name=folder.name, files=files))
        log.debug("Root disc group '%s': %d files", folder.name, len(files))

    # Each subfolder becomes its own disc group
    for sub_name, mkvs in subfolders.items():
        files = []
        for p in mkvs:
            files.append(_probe_file(p))
            scanned_count += 1
            if on_progress:
                on_progress(scanned_count, total, p.name)
        discs.append(ScannedDisc(folder_name=sub_name, files=files))
        log.debug("Subfolder disc group '%s': %d files", sub_name, len(files))

    log.debug("Scan complete: %d disc group(s), %d total files",
              len(discs), sum(len(d.files) for d in discs))
    return discs
