"""MKV organized tagging via mkvpropedit.

Stamps processed files with a riplex global tag so re-runs can skip
them.  Reading the tag back is done via ffprobe (already called by the
scanner) or mkvmerge -J as a fallback.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


def find_mkvpropedit() -> str | None:
    """Locate the mkvpropedit executable.

    Checks PATH first, then common MKVToolNix install locations on Windows.
    Returns the path string, or None if not found.
    """
    path = shutil.which("mkvpropedit")
    if path:
        return path
    for candidate in [
        r"C:\Program Files\MKVToolNix\mkvpropedit.exe",
        r"C:\Program Files (x86)\MKVToolNix\mkvpropedit.exe",
    ]:
        if Path(candidate).is_file():
            return candidate
    return None


def tag_organized(file_path: str, label: str) -> bool:
    """Write a riplex global tag to an MKV file via mkvpropedit.

    The tag value is ``organized:<ISO date>|<label>``.
    Returns True on success, False on failure.
    """
    exe = find_mkvpropedit()
    if exe is None:
        log.warning("mkvpropedit not found, cannot tag %s", file_path)
        return False

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tag_value = f"organized:{stamp}|{label}"

    # mkvpropedit uses an XML tag file for global tags
    tag_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Tags>\n"
        "  <Tag>\n"
        "    <Targets />\n"
        "    <Simple>\n"
        "      <Name>RIPLEX</Name>\n"
        f"      <String>{_escape_xml(tag_value)}</String>\n"
        "    </Simple>\n"
        "  </Tag>\n"
        "</Tags>\n"
    )

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False, encoding="utf-8",
        ) as tmp:
            tmp.write(tag_xml)
            tmp_path = tmp.name

        result = subprocess.run(
            [exe, str(file_path), "--tags", f"global:{tmp_path}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            log.warning("mkvpropedit failed for %s: %s", file_path, result.stderr.strip())
            return False

        log.debug("Tagged %s: %s", file_path, tag_value)
        return True

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        log.warning("Failed to tag %s: %s", file_path, exc)
        return False
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except (NameError, OSError):
            pass


def read_organized_tag(file_path: str) -> str | None:
    """Read the riplex tag from an MKV file via mkvmerge -J.

    Returns the tag value string, or None if not found or on error.
    This is a fallback for when ffprobe doesn't expose the tag (the scanner
    normally reads it via ffprobe format_tags).
    """
    mkvmerge = shutil.which("mkvmerge")
    if mkvmerge is None:
        for candidate in [
            r"C:\Program Files\MKVToolNix\mkvmerge.exe",
            r"C:\Program Files (x86)\MKVToolNix\mkvmerge.exe",
        ]:
            if Path(candidate).is_file():
                mkvmerge = candidate
                break
    if mkvmerge is None:
        return None

    try:
        result = subprocess.run(
            [mkvmerge, "-J", str(file_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)
        for tag_group in data.get("global_tags", []):
            for tag in tag_group.get("tags", []):
                name = tag.get("name", "").upper()
                if name in ("RIPLEX", "PLEX_PLANNER"):
                    return tag.get("value")
        return None

    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError, OSError):
        return None


def _escape_xml(text: str) -> str:
    """Escape special characters for XML text content."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
