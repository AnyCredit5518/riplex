"""Interface to makemkvcon for reading disc title information."""

from __future__ import annotations

import logging
import platform
import re
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

# On Windows, prevent subprocess calls from spawning a visible console window.
_SUBPROCESS_FLAGS: dict = (
    {"creationflags": subprocess.CREATE_NO_WINDOW}
    if platform.system() == "Windows"
    else {}
)

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
    subtitle_tracks: list[str] = field(default_factory=list)  # e.g. ["English", "Spanish"]
    stream_count: int = 0  # total streams (video + audio + subtitle)
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

        # Collect audio and subtitle track descriptions
        audio_tracks: list[str] = []
        subtitle_tracks: list[str] = []
        stream_ids: set[int] = set()
        for (sid, aid), val in sorted(streams.items()):
            stream_ids.add(sid)
            if aid == 30 and sid > 0:  # attr 30 = display string
                stype = streams.get((sid, 1), "")
                if stype and "Audio" in stype:
                    audio_tracks.append(val)
                elif stype and "Subtitle" in stype:
                    subtitle_tracks.append(val)

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
            subtitle_tracks=subtitle_tracks,
            stream_count=len(stream_ids),
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

    .. deprecated:: Use :pyclass:`MakeMKV` instead.
    """
    return MakeMKV(makemkvcon).disc_info(drive)


def run_drive_list(makemkvcon: Path | None = None) -> list[DriveInfo]:
    """Run makemkvcon -r info list and return available drives.

    .. deprecated:: Use :pyclass:`MakeMKV` instead.
    """
    return MakeMKV(makemkvcon).drive_list()


def eject_disc(drive_letter: str) -> bool:
    """Eject the disc from the given drive (e.g. "D:").

    .. deprecated:: Use :pyclass:`MakeMKV` instead.
    """
    return MakeMKV().eject(drive_letter)


def wait_for_disc(
    drive_index: int,
    makemkvcon: Path | None = None,
    poll_interval: float = 5.0,
    timeout: float = 600.0,
    previous_label: str = "",
) -> DriveInfo | None:
    """Poll until a disc is detected in the drive (different from previous_label).

    .. deprecated:: Use :pyclass:`MakeMKV` instead.
    """
    return MakeMKV(makemkvcon).wait_for_disc(
        drive_index, poll_interval, timeout, previous_label,
    )


# ---- ripping ----

@dataclass
class RipProgress:
    """Progress update from a makemkvcon rip."""

    title_index: int
    current: int  # current progress value
    total: int  # total for this title
    max_val: int  # overall max


@dataclass
class RipResult:
    """Result of ripping a single title."""

    title_index: int
    success: bool
    output_file: str  # path to the output MKV
    error_message: str = ""


# ---------------------------------------------------------------------------
# MakeMKV class — wraps makemkvcon subprocess calls
# ---------------------------------------------------------------------------

class MakeMKV:
    """High-level interface to the makemkvcon command-line tool.

    Instantiate once with the path to the executable (auto-detected if
    omitted), then call methods for disc scanning, ripping, and drive
    management.
    """

    def __init__(self, exe: Path | None = None) -> None:
        self.exe: Path | None = exe or find_makemkvcon()

    # -- helpers ----------------------------------------------------------

    def _require_exe(self) -> Path:
        if not self.exe:
            raise FileNotFoundError(
                "makemkvcon not found. Install MakeMKV or pass the path."
            )
        return self.exe

    @staticmethod
    def _resolve_source(drive: int | str) -> str:
        if isinstance(drive, int):
            return f"disc:{drive}"
        if drive.startswith("disc:") or drive.startswith("dev:"):
            return drive
        return f"dev:{drive}"

    # -- public API -------------------------------------------------------

    def disc_info(self, drive: int | str) -> DiscInfo:
        """Read disc info from *drive* (index or device name)."""
        exe = self._require_exe()
        source = self._resolve_source(drive)

        cmd = [str(exe), "-r", "info", source]
        log.info("Running: %s", " ".join(cmd))

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            **_SUBPROCESS_FLAGS,
        )

        output = result.stdout + result.stderr
        if "TCOUNT:" not in output:
            raise RuntimeError(
                f"makemkvcon did not produce title info. Output:\n{output[:500]}"
            )
        return parse_disc_info(output)

    def drive_list(self) -> list[DriveInfo]:
        """List available optical drives."""
        exe = self._require_exe()

        cmd = [str(exe), "-r", "info", "list"]
        log.info("Running: %s", " ".join(cmd))

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            **_SUBPROCESS_FLAGS,
        )
        output = result.stdout + result.stderr
        return parse_drive_list(output)

    def resolve_drive(self, drive_arg: str = "auto") -> DriveInfo:
        """Resolve a drive argument to a :class:`DriveInfo`.

        When *drive_arg* is ``"auto"``, scans drives and returns the first
        one with a disc inserted.  Otherwise interprets *drive_arg* as a
        drive index (int string) or device name and looks it up.

        Raises :class:`RuntimeError` if no matching drive is found.
        """
        drives = self.drive_list()
        if drive_arg == "auto":
            active = [d for d in drives if d.has_disc]
            if not active:
                raise RuntimeError("No disc found in any drive.")
            return active[0]

        # Explicit drive — by index or device name
        try:
            idx = int(drive_arg)
            for d in drives:
                if d.index == idx:
                    return d
        except ValueError:
            for d in drives:
                if d.device == drive_arg:
                    return d
        raise RuntimeError(f"Drive '{drive_arg}' not found.")

    def eject(self, drive_letter: str) -> bool:
        """Eject the disc from *drive_letter* (e.g. ``"D:"``)."""
        import platform as _plat

        drive = drive_letter.rstrip("\\")
        if _plat.system() != "Windows":
            try:
                subprocess.run(["eject", drive], timeout=10, capture_output=True)
                return True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                return False

        ps_cmd = (
            f'(New-Object -comObject Shell.Application)'
            f'.NameSpace(17).ParseName("{drive}").InvokeVerb("Eject")'
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=15,
                **_SUBPROCESS_FLAGS,
            )
            log.info("Eject %s: exit %d", drive, result.returncode)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, OSError) as exc:
            log.warning("Eject failed for %s: %s", drive, exc)
            return False

    def wait_for_disc(
        self,
        drive_index: int,
        poll_interval: float = 5.0,
        timeout: float = 600.0,
        previous_label: str = "",
    ) -> DriveInfo | None:
        """Poll until a new disc is detected (label differs from *previous_label*)."""
        import time as _time

        deadline = _time.monotonic() + timeout
        while _time.monotonic() < deadline:
            try:
                drives = self.drive_list()
            except (RuntimeError, FileNotFoundError):
                pass
            else:
                for d in drives:
                    if d.index == drive_index and d.disc_label:
                        if d.disc_label != previous_label:
                            return d
            _time.sleep(poll_interval)
        return None

    def resolve_drive(self, drive_arg: str = "auto") -> DriveInfo:
        """Resolve a drive argument to a DriveInfo with a disc present.

        When *drive_arg* is ``"auto"``, scans all drives and picks the
        first one with a disc inserted.  Otherwise interprets *drive_arg*
        as a drive index.

        Raises RuntimeError if no drive with a disc is found.
        """
        if drive_arg == "auto":
            drives = self.drive_list()
            active = [d for d in drives if d.has_disc]
            if not active:
                raise RuntimeError("No disc found in any drive.")
            return active[0]

        idx = int(drive_arg)
        drives = self.drive_list()
        for d in drives:
            if d.index == idx:
                return d
        raise RuntimeError(f"Drive {idx} not found.")

    def rip(
        self,
        drive: int | str,
        title_index: int,
        output_dir: Path,
        progress_callback=None,
        cancel_event: threading.Event | None = None,
    ) -> RipResult:
        """Rip a single title from disc via ``makemkvcon mkv``."""
        exe = self._require_exe()
        source = self._resolve_source(drive)

        output_dir.mkdir(parents=True, exist_ok=True)
        cmd = [str(exe), "-r", "--progress=-same", "mkv", source,
               str(title_index), str(output_dir)]
        log.info("Running: %s", " ".join(cmd))

        output_file = ""
        raw_lines: list[str] = []

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            **_SUBPROCESS_FLAGS,
        )

        try:
            for line in proc.stdout:
                if cancel_event and cancel_event.is_set():
                    proc.terminate()
                    proc.wait(timeout=5)
                    return RipResult(
                        title_index=title_index,
                        success=False,
                        output_file="",
                        error_message="Cancelled by user",
                    )
                line = line.rstrip("\n\r")
                log.debug("makemkvcon: %s", line)
                raw_lines.append(line)

                progress = _parse_progress(line)
                if progress and progress_callback:
                    progress.title_index = title_index
                    progress_callback(progress)

            proc.wait()
        except Exception:
            proc.kill()
            proc.wait()
            raise

        rip_log_path = output_dir / f"_makemkvcon_t{title_index:02d}.log"
        try:
            rip_log_path.write_text("\n".join(raw_lines) + "\n", encoding="utf-8")
        except OSError as exc:
            log.warning("Failed to write rip log %s: %s", rip_log_path, exc)

        mkv_files = sorted(output_dir.glob("*.mkv"), key=lambda p: p.stat().st_mtime)
        if mkv_files:
            output_file = str(mkv_files[-1])

        success = proc.returncode == 0
        error_msg = ""
        if not success:
            error_msg = f"makemkvcon exited with code {proc.returncode}"

        return RipResult(
            title_index=title_index,
            success=success,
            output_file=output_file,
            error_message=error_msg,
        )


def _parse_progress(line: str) -> RipProgress | None:
    """Parse a PRGV line from makemkvcon robot output.

    Format: PRGV:current,total,max
    """
    if not line.startswith("PRGV:"):
        return None
    parts = line[5:].split(",")
    if len(parts) < 3:
        return None
    try:
        return RipProgress(
            title_index=-1,  # caller sets this
            current=int(parts[0]),
            total=int(parts[1]),
            max_val=int(parts[2]),
        )
    except ValueError:
        return None


def run_rip(
    drive: int | str,
    title_index: int,
    output_dir: Path,
    makemkvcon: Path | None = None,
    progress_callback=None,
    cancel_event: threading.Event | None = None,
) -> RipResult:
    """Rip a single title from a disc via makemkvcon mkv.

    .. deprecated:: Use :pyclass:`MakeMKV` instead.
    """
    return MakeMKV(makemkvcon).rip(
        drive, title_index, output_dir, progress_callback, cancel_event
    )


# ---------------------------------------------------------------------------
# Helpers for manifest enrichment
# ---------------------------------------------------------------------------

_CODEC_MAP = {
    "mpegH": "hevc",
    "MpegH": "hevc",
    "mpeg4": "h264",
    "Mpeg4": "h264",
    "V_MPEGH": "hevc",
    "V_MPEG4": "h264",
}


def build_stream_fingerprint(title: DiscTitle) -> str:
    """Build a stream fingerprint string from DiscTitle metadata.

    Approximates the scanner's ffprobe-based fingerprint using info
    from makemkvcon SINFO output. Format:
        hevc:3840x2160|truehd:eng:8ch|ac3:eng:2ch|sub:eng|sub:spa
    """
    parts: list[str] = []

    # Video stream
    codec = _CODEC_MAP.get(title.video_codec, title.video_codec.lower())
    parts.append(f"{codec}:{title.resolution}")

    # Audio tracks: parse display strings like "TrueHD English 7.1"
    for track in title.audio_tracks:
        tokens = track.split()
        if not tokens:
            continue
        acodec = tokens[0].lower()
        lang = ""
        channels = ""
        for tok in tokens[1:]:
            # Channel layout like "7.1", "5.1", "2.0", "Stereo", "Mono"
            if re.match(r"\d+\.\d+$", tok):
                ch_num = int(tok.split(".")[0]) + int(tok.split(".")[1])
                channels = f"{ch_num}ch"
            elif tok.lower() in ("stereo",):
                channels = "2ch"
            elif tok.lower() in ("mono",):
                channels = "1ch"
            elif len(tok) >= 3 and tok[0].isupper() and tok[1:].islower():
                # Language name like "English", "Spanish"
                lang = tok[:3].lower()
        parts.append(f"{acodec}:{lang}:{channels}" if lang else f"{acodec}::{channels}")

    # Subtitle tracks: parse display strings
    for track in title.subtitle_tracks:
        tokens = track.split()
        lang = ""
        for tok in tokens:
            if len(tok) >= 3 and tok[0].isupper() and tok[1:].islower():
                lang = tok[:3].lower()
                break
        parts.append(f"sub:{lang}")

    return "|".join(parts)


def probe_chapter_durations(mkv_path: str | Path) -> list[int]:
    """Extract per-chapter durations from a ripped MKV using ffprobe.

    Returns a list of chapter durations in seconds. Returns empty list
    if ffprobe is unavailable or the file has no chapters.
    """
    import shutil

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        log.debug("ffprobe not found, skipping chapter duration extraction")
        return []

    cmd = [
        ffprobe, "-v", "quiet",
        "-print_format", "json",
        "-show_chapters",
        str(mkv_path),
    ]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            **_SUBPROCESS_FLAGS,
        )
        if proc.returncode != 0:
            log.debug("ffprobe failed for %s: exit %d", mkv_path, proc.returncode)
            return []

        import json
        data = json.loads(proc.stdout)
        chapters = data.get("chapters", [])
        durations: list[int] = []
        for ch in chapters:
            try:
                dur = float(ch["end_time"]) - float(ch["start_time"])
                durations.append(round(dur))
            except (KeyError, ValueError):
                durations.append(0)
        return durations
    except (subprocess.TimeoutExpired, OSError, ValueError) as exc:
        log.debug("ffprobe chapter extraction failed for %s: %s", mkv_path, exc)
        return []
