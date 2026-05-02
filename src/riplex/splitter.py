"""Chapter-based MKV splitting using mkvmerge."""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# On Windows, prevent subprocess calls from spawning a visible console window.
_SUBPROCESS_FLAGS: dict = (
    {"creationflags": subprocess.CREATE_NO_WINDOW}
    if platform.system() == "Windows"
    else {}
)


@dataclass
class Chapter:
    """A single chapter from an MKV file."""

    index: int  # 0-based
    title: str
    start_seconds: float
    end_seconds: float

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


def find_mkvmerge() -> str | None:
    """Locate the mkvmerge executable.

    Checks PATH first, then common install locations on Windows.
    Returns the path string, or None if not found.
    """
    path = shutil.which("mkvmerge")
    if path:
        return path
    for candidate in [
        r"C:\Program Files\MKVToolNix\mkvmerge.exe",
        r"C:\Program Files (x86)\MKVToolNix\mkvmerge.exe",
    ]:
        if Path(candidate).is_file():
            return candidate
    return None


def get_chapters(file_path: str) -> list[Chapter]:
    """Extract chapter information from an MKV file using ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_chapters",
            file_path,
        ],
        capture_output=True,
        text=True,
        **_SUBPROCESS_FLAGS,
    )
    if result.returncode != 0:
        return []
    data = json.loads(result.stdout)
    chapters: list[Chapter] = []
    for i, ch in enumerate(data.get("chapters", [])):
        title = ch.get("tags", {}).get("title", f"Chapter {i + 1}")
        chapters.append(
            Chapter(
                index=i,
                title=title,
                start_seconds=float(ch["start_time"]),
                end_seconds=float(ch["end_time"]),
            )
        )
    return chapters


def split_by_chapters(
    source: str,
    output_dir: str,
    output_names: list[str] | None = None,
) -> list[str]:
    """Split an MKV file by chapters using mkvmerge.

    *source* is the path to the MKV file to split.
    *output_dir* is the directory to write split files into.
    *output_names* is an optional list of filenames (one per chapter).
    If not provided, files are named ``split-001.mkv``, etc.

    Returns a list of absolute paths to the split files, in chapter order.
    Raises ``RuntimeError`` if mkvmerge is not found or the split fails.
    """
    mkvmerge = find_mkvmerge()
    if mkvmerge is None:
        raise RuntimeError(
            "mkvmerge not found. Install MKVToolNix to enable chapter splitting."
        )

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # mkvmerge names splits as base-001.mkv, base-002.mkv, ...
    temp_base = out_path / "split.mkv"
    result = subprocess.run(
        [mkvmerge, "--split", "chapters:all", "-o", str(temp_base), source],
        capture_output=True,
        text=True,
        **_SUBPROCESS_FLAGS,
    )
    if result.returncode != 0:
        raise RuntimeError(f"mkvmerge split failed: {result.stderr}")

    # Collect the generated files in order
    split_files = sorted(out_path.glob("split-*.mkv"))
    if not split_files:
        raise RuntimeError("mkvmerge produced no output files.")

    # Rename to desired output names if provided
    if output_names:
        if len(output_names) != len(split_files):
            raise RuntimeError(
                f"Expected {len(output_names)} output names but got "
                f"{len(split_files)} split files."
            )
        final_paths: list[str] = []
        for split_file, name in zip(split_files, output_names):
            dest = out_path / name
            split_file.rename(dest)
            final_paths.append(str(dest))
        return final_paths

    return [str(f) for f in split_files]
