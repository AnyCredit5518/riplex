"""Interface to makemkvcon for reading disc title information."""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# Default search paths for makemkvcon on Windows
_MAKEMKVCON_SEARCH_PATHS = [
    Path(r"C:\Program Files\MakeMKV\makemkvcon64.exe"),
    Path(r"C:\Program Files (x86)\MakeMKV\makemkvcon64.exe"),
    Path(r"C:\Program Files\MakeMKV\makemkvcon.exe"),
    Path(r"C:\Program Files (x86)\MakeMKV\makemkvcon.exe"),
]


def find_makemkvcon() -> Path | None:
    """Locate makemkvcon executable, checking PATH then common install paths."""
    import shutil

    path = shutil.which("makemkvcon64") or shutil.which("makemkvcon")
    if path:
        return Path(path)
    for candidate in _MAKEMKVCON_SEARCH_PATHS:
        if candidate.exists():
            return candidate
    return None


@dataclass
class DiscTitle:
    """A single title (playlist) on a disc as reported by makemkvcon."""

    index: int
    name: str
    duration_seconds: int
    chapters: int
    size_bytes: int
    filename: str  # suggested MKV filename
    playlist: str  # e.g. "00024.mpls"
    resolution: str  # e.g. "3840x2160", "1920x1080"
    video_codec: str  # e.g. "MpegH", "Mpeg4"
    audio_tracks: list[str] = field(default_factory=list)
    segment_count: int = 1
    segment_map: str = ""


@dataclass
class DriveInfo:
    """Information about a disc drive from makemkvcon list."""

    index: int
    name: str  # drive hardware name
    disc_label: str  # volume label (e.g. "FROZEN_PLANET_II_D2")
    device: str  # OS device name (e.g. "D:")
    has_disc: bool


@dataclass
class DiscInfo:
    """Parsed disc information from makemkvcon -r info."""

    disc_name: str
    disc_type: str  # e.g. "Blu-ray disc"
    titles: list[DiscTitle] = field(default_factory=list)


def _parse_duration(duration_str: str) -> int:
    """Parse 'H:MM:SS' or 'M:SS' to total seconds."""
    parts = duration_str.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    return 0


def parse_disc_info(output: str) -> DiscInfo:
    """Parse makemkvcon -r info output into structured DiscInfo.

    The robot-mode output consists of lines like:
        CINFO:attr_id,attr_code,"value"
        TINFO:title_id,attr_id,attr_code,"value"
        SINFO:title_id,stream_id,attr_id,attr_code,"value"
        TCOUNT:N
        MSG:...
        DRV:...
    """
    disc_name = ""
    disc_type = ""

    # Collect TINFO and SINFO keyed by title index
    tinfo: dict[int, dict[int, str]] = {}
    sinfo: dict[int, dict[tuple[int, int], str]] = {}

    for line in output.splitlines():
        line = line.strip()

        if line.startswith("CINFO:"):
            parts = _split_robot_line(line[6:])
            if not parts:
                continue
            attr_id = int(parts[0])
            value = parts[2] if len(parts) > 2 else ""
            if attr_id == 1:
                disc_type = value
            elif attr_id == 2:
                disc_name = value

        elif line.startswith("TINFO:"):
            parts = _split_robot_line(line[6:])
            if not parts or len(parts) < 4:
                continue
            title_id = int(parts[0])
            attr_id = int(parts[1])
            value = parts[3]
            tinfo.setdefault(title_id, {})[attr_id] = value

        elif line.startswith("SINFO:"):
            parts = _split_robot_line(line[6:])
            if not parts or len(parts) < 5:
                continue
            title_id = int(parts[0])
            stream_id = int(parts[1])
            attr_id = int(parts[2])
            value = parts[4]
            sinfo.setdefault(title_id, {})[(stream_id, attr_id)] = value

    # Build DiscTitle objects
    titles: list[DiscTitle] = []
    for tid in sorted(tinfo):
        t = tinfo[tid]
        # Get resolution and codec from stream 0 (video)
        streams = sinfo.get(tid, {})
        resolution = streams.get((0, 19), "")  # SINFO attr 19 = resolution
        video_codec = streams.get((0, 6), "")  # SINFO attr 6 = codec short name

        # Collect audio track descriptions
        audio_tracks: list[str] = []
        for (sid, aid), val in sorted(streams.items()):
            if aid == 30 and sid > 0:  # attr 30 = display string
                stype = streams.get((sid, 1), "")
                if stype and "Audio" in stype:
                    audio_tracks.append(val)

        title = DiscTitle(
            index=tid,
            name=t.get(2, ""),
            duration_seconds=_parse_duration(t.get(9, "0:00")),
            chapters=int(t.get(8, "0")),
            size_bytes=int(t.get(11, "0")),
            filename=t.get(27, ""),
            playlist=t.get(16, ""),
            resolution=resolution,
            video_codec=video_codec,
            audio_tracks=audio_tracks,
            segment_count=int(t.get(25, "1")),
            segment_map=t.get(26, ""),
        )
        titles.append(title)

    return DiscInfo(disc_name=disc_name, disc_type=disc_type, titles=titles)


def parse_drive_list(output: str) -> list[DriveInfo]:
    """Parse makemkvcon -r info list output into DriveInfo objects."""
    drives: list[DriveInfo] = []
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("DRV:"):
            continue
        parts = _split_robot_line(line[4:])
        if not parts or len(parts) < 7:
            continue
        index = int(parts[0])
        flags = int(parts[1])
        has_disc = (flags & 2) != 0  # bit 1 = disc inserted
        drives.append(DriveInfo(
            index=index,
            name=parts[4],
            disc_label=parts[5],
            device=parts[6],
            has_disc=has_disc,
        ))
    return drives


def _split_robot_line(text: str) -> list[str]:
    """Split a makemkvcon robot-mode CSV line, respecting quoted strings."""
    parts: list[str] = []
    current = ""
    in_quotes = False
    for ch in text:
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == "," and not in_quotes:
            parts.append(current)
            current = ""
        else:
            current += ch
    parts.append(current)
    return parts


def run_disc_info(drive: int | str, makemkvcon: Path | None = None) -> DiscInfo:
    """Run makemkvcon -r info disc:N and return parsed DiscInfo.

    *drive* can be an integer (disc index) or a string like "disc:0" or "D:".
    """
    exe = makemkvcon or find_makemkvcon()
    if not exe:
        raise FileNotFoundError(
            "makemkvcon not found. Install MakeMKV or pass --makemkvcon path."
        )

    if isinstance(drive, int):
        source = f"disc:{drive}"
    elif drive.startswith("disc:") or drive.startswith("dev:"):
        source = drive
    else:
        source = f"dev:{drive}"

    cmd = [str(exe), "-r", "info", source]
    log.info("Running: %s", " ".join(cmd))

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300,
    )

    # makemkvcon often exits with code 1 even on success
    output = result.stdout + result.stderr
    if "TCOUNT:" not in output:
        raise RuntimeError(
            f"makemkvcon did not produce title info. Output:\n{output[:500]}"
        )

    return parse_disc_info(output)


def run_drive_list(makemkvcon: Path | None = None) -> list[DriveInfo]:
    """Run makemkvcon -r info list and return available drives."""
    exe = makemkvcon or find_makemkvcon()
    if not exe:
        raise FileNotFoundError("makemkvcon not found.")

    cmd = [str(exe), "-r", "info", "list"]
    log.info("Running: %s", " ".join(cmd))

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = result.stdout + result.stderr
    return parse_drive_list(output)
