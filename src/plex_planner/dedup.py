"""Duplicate detection for MKV files from MakeMKV rips.

Tier 1 (fast, always runs): Groups files by approximate duration, then
confirms duplicates via file-size similarity and stream-layout match.

Tier 2 (opt-in): Extracts a single video frame via ffmpeg at 25% of
duration, computes a perceptual difference hash (dhash), and compares
hamming distance to confirm visual duplicates.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

from plex_planner.models import ScannedDisc, ScannedFile

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DURATION_TOLERANCE_S = 5  # seconds
_SIZE_RATIO_THRESHOLD = 0.98  # files must be within 2% of each other
_DHASH_HAMMING_THRESHOLD = 10  # bits (64-bit hash, <=10 = visually similar)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class DuplicateGroup:
    """A set of files detected as duplicates of the same content."""

    keep: ScannedFile  # the recommended file to keep (largest)
    duplicates: list[ScannedFile] = field(default_factory=list)


@dataclass
class CompilationGroup:
    """A file detected as a 'play all' compilation of individual files."""

    compilation: ScannedFile  # the combined file to discard
    parts: list[ScannedFile] = field(default_factory=list)  # individual files to keep


# ---------------------------------------------------------------------------
# Tier 1: metadata fingerprint
# ---------------------------------------------------------------------------


def _duration_close(a: ScannedFile, b: ScannedFile) -> bool:
    return abs(a.duration_seconds - b.duration_seconds) <= _DURATION_TOLERANCE_S


def _size_similar(a: ScannedFile, b: ScannedFile) -> bool:
    if a.size_bytes == 0 or b.size_bytes == 0:
        return False
    ratio = min(a.size_bytes, b.size_bytes) / max(a.size_bytes, b.size_bytes)
    return ratio >= _SIZE_RATIO_THRESHOLD


def _streams_match(a: ScannedFile, b: ScannedFile) -> bool:
    if not a.stream_fingerprint or not b.stream_fingerprint:
        return False
    return a.stream_fingerprint == b.stream_fingerprint


def find_duplicates_tier1(files: list[ScannedFile]) -> list[DuplicateGroup]:
    """Detect duplicates using metadata fingerprinting (fast).

    Two files are considered duplicates when ALL of:
      - Duration within 5 seconds
      - File size within 2%
      - Identical stream layout (codec, resolution, channels, languages)
    """
    if len(files) < 2:
        return []

    # Union-find to group duplicates transitively
    parent: dict[str, str] = {f.path: f.path for f in files}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for a, b in combinations(files, 2):
        if (
            _duration_close(a, b)
            and _size_similar(a, b)
            and _streams_match(a, b)
        ):
            log.debug("Tier1 duplicate pair: %s <-> %s (dur=%ds/%ds)",
                      a.name, b.name, a.duration_seconds, b.duration_seconds)
            union(a.path, b.path)

    # Collect groups
    groups: dict[str, list[ScannedFile]] = {}
    for f in files:
        root = find(f.path)
        groups.setdefault(root, []).append(f)

    result: list[DuplicateGroup] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        # Keep the largest file
        members.sort(key=lambda f: f.size_bytes, reverse=True)
        result.append(DuplicateGroup(keep=members[0], duplicates=members[1:]))

    return result


# ---------------------------------------------------------------------------
# Compilation detection: "play all" files that combine individual titles
# ---------------------------------------------------------------------------

_COMPILATION_DURATION_TOLERANCE_S = 10  # total sum tolerance


def find_compilations(files: list[ScannedFile]) -> list[CompilationGroup]:
    """Detect 'play all' compilation files among a set of files.

    A compilation is a file with N chapters (N > 1) where each chapter's
    duration matches the duration of a distinct individual file with the
    same stream layout.

    Returns a list of :class:`CompilationGroup` objects.
    """
    if len(files) < 3:  # need at least 1 compilation + 2 parts
        log.debug("find_compilations: skipping, only %d files (need >=3)", len(files))
        return []

    # Group files by stream fingerprint (compilations share layout with parts)
    by_fingerprint: dict[str, list[ScannedFile]] = {}
    for f in files:
        if f.stream_fingerprint:
            by_fingerprint.setdefault(f.stream_fingerprint, []).append(f)

    results: list[CompilationGroup] = []
    seen_compilations: set[str] = set()

    for fp, fp_files in by_fingerprint.items():
        if len(fp_files) < 3:
            log.debug("Fingerprint group '%s': %d files, skipping (need >=3)",
                      fp, len(fp_files))
            continue

        log.debug("Fingerprint group '%s': %d files", fp, len(fp_files))

        # Candidates for compilation: files with multiple chapters and durations
        candidates = [
            f for f in fp_files
            if f.chapter_count > 1 and len(f.chapter_durations) == f.chapter_count
        ]
        # Candidates for parts: all files (including those with chapters)
        parts_pool = fp_files

        for candidate in candidates:
            others = [f for f in parts_pool if f.path != candidate.path]
            if len(others) < 2:
                log.debug("Compilation candidate %s: only %d other files, skipping",
                          candidate.name, len(others))
                continue

            log.debug("Compilation candidate %s: %d chapters %s, %d other files",
                      candidate.name, candidate.chapter_count,
                      candidate.chapter_durations, len(others))
            match = _match_chapters_to_files(
                candidate.chapter_durations, others,
            )
            if match and candidate.path not in seen_compilations:
                log.debug("Compilation detected: %s -> parts: %s",
                          candidate.name, [p.name for p in match])
                seen_compilations.add(candidate.path)
                results.append(
                    CompilationGroup(compilation=candidate, parts=match)
                )
            elif not match:
                log.debug("Compilation candidate %s: chapter matching failed",
                          candidate.name)

    return results


def _match_chapters_to_files(
    chapter_durations: list[int],
    files: list[ScannedFile],
    tolerance: int = _COMPILATION_DURATION_TOLERANCE_S,
) -> list[ScannedFile] | None:
    """Match chapters to distinct files by runtime.

    Tries two strategies:

    1. **One-to-one**: each chapter matches exactly one file by duration.
    2. **Grouped**: consecutive runs of chapters sum to a file's duration
       (covers compilations where each part has its own internal chapters).

    Returns a list of files in chapter order, or None if not all chapters
    can be matched.
    """
    # Strategy 1: one chapter = one file
    result = _match_chapters_one_to_one(chapter_durations, files, tolerance)
    if result is not None:
        log.debug("Chapter match strategy 1 (one-to-one) succeeded")
        return result

    # Strategy 2: consecutive chapter groups = one file each
    log.debug("Strategy 1 failed, trying grouped matching")
    return _match_chapters_grouped(chapter_durations, files, tolerance)


def _match_chapters_one_to_one(
    chapter_durations: list[int],
    files: list[ScannedFile],
    tolerance: int,
) -> list[ScannedFile] | None:
    """Match each chapter duration to a distinct file."""
    available = list(files)
    matched: list[ScannedFile] = []

    for ch_dur in chapter_durations:
        best = None
        best_delta = tolerance + 1
        for f in available:
            delta = abs(f.duration_seconds - ch_dur)
            if delta <= tolerance and delta < best_delta:
                best = f
                best_delta = delta
        if best is None:
            return None
        matched.append(best)
        available.remove(best)

    return matched


def _match_chapters_grouped(
    chapter_durations: list[int],
    files: list[ScannedFile],
    tolerance: int,
) -> list[ScannedFile] | None:
    """Match consecutive groups of chapters to files by summed duration.

    Uses a greedy approach: starting from the first unmatched chapter,
    try extending the group from 1 chapter up to the remaining count,
    checking if the sum matches any available file.
    """
    available = list(files)
    matched: list[ScannedFile] = []
    i = 0

    while i < len(chapter_durations):
        found = False
        # Try groups from largest to smallest to prefer fewer, bigger matches
        max_span = len(chapter_durations) - i
        for span in range(max_span, 0, -1):
            group_sum = sum(chapter_durations[i : i + span])
            best = None
            best_delta = tolerance + 1
            for f in available:
                delta = abs(f.duration_seconds - group_sum)
                if delta <= tolerance and delta < best_delta:
                    best = f
                    best_delta = delta
            if best is not None:
                log.debug(
                    "Grouped match: chapters[%d:%d] sum=%ds -> %s (%ds, delta=%ds)",
                    i, i + span, group_sum, best.name, best.duration_seconds, best_delta,
                )
                matched.append(best)
                available.remove(best)
                i += span
                found = True
                break
        if not found:
            log.debug("Grouped match failed at chapter index %d", i)
            return None

    # Must match at least 2 files to be a valid compilation
    if len(matched) < 2:
        log.debug("Grouped match produced only %d file(s), need >=2", len(matched))
        return None
    log.debug("Grouped match succeeded: %d parts", len(matched))
    return matched


# ---------------------------------------------------------------------------
# Tier 2: perceptual hash (dhash via ffmpeg frame extraction)
# ---------------------------------------------------------------------------


def _extract_frame_bytes(path: str, timestamp: int) -> bytes | None:
    """Extract a single PNG frame at *timestamp* seconds using ffmpeg."""
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-ss", str(timestamp),
                "-i", path,
                "-frames:v", "1",
                "-vf", "scale=9:8:flags=area,format=gray",
                "-f", "rawvideo",
                "-pix_fmt", "gray",
                "pipe:1",
            ],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0 or not result.stdout:
            return None
        return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _dhash(gray_9x8: bytes) -> int:
    """Compute a 64-bit difference hash from 9x8 grayscale raw bytes.

    Compares each pixel to its right neighbour across each row.
    9 columns x 8 rows = 72 pixels, producing 8 comparisons x 8 rows = 64 bits.
    """
    if len(gray_9x8) != 72:
        return 0
    h = 0
    for row in range(8):
        for col in range(8):
            offset = row * 9 + col
            if gray_9x8[offset] < gray_9x8[offset + 1]:
                h |= 1 << (row * 8 + col)
    return h


def _hamming(a: int, b: int) -> int:
    """Count differing bits between two integers."""
    return bin(a ^ b).count("1")


def compute_dhash(path: str, duration_seconds: int) -> int | None:
    """Compute a perceptual dhash for a video file.

    Extracts a frame at 25% of the file's duration to avoid intros/credits.
    Returns a 64-bit hash integer, or None on failure.
    """
    ts = max(1, duration_seconds // 4)
    raw = _extract_frame_bytes(path, ts)
    if raw is None:
        return None
    return _dhash(raw)


def confirm_duplicates_tier2(group: DuplicateGroup) -> DuplicateGroup | None:
    """Use perceptual hashing to confirm a tier-1 duplicate group.

    Returns the group unchanged if confirmed, or None if the visual
    hashes don't match (meaning they aren't real duplicates).
    """
    keep_hash = compute_dhash(group.keep.path, group.keep.duration_seconds)
    if keep_hash is None:
        return group  # can't disprove, keep the tier-1 result

    confirmed_dupes: list[ScannedFile] = []
    for dup in group.duplicates:
        dup_hash = compute_dhash(dup.path, dup.duration_seconds)
        if dup_hash is None or _hamming(keep_hash, dup_hash) <= _DHASH_HAMMING_THRESHOLD:
            confirmed_dupes.append(dup)

    if not confirmed_dupes:
        return None
    return DuplicateGroup(keep=group.keep, duplicates=confirmed_dupes)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def find_duplicates(
    scanned: list[ScannedDisc],
    *,
    use_perceptual_hash: bool = False,
) -> list[DuplicateGroup]:
    """Find duplicate files across all scanned discs.

    Args:
        scanned: Disc groups from :func:`scanner.scan_folder`.
        use_perceptual_hash: If True, run tier-2 visual confirmation on
            tier-1 candidates (adds ~1s per candidate file).

    Returns:
        List of :class:`DuplicateGroup` objects. Each group has a
        recommended *keep* file and one or more *duplicates* to discard.
    """
    all_files = [f for d in scanned for f in d.files]
    groups = find_duplicates_tier1(all_files)

    if use_perceptual_hash:
        confirmed: list[DuplicateGroup] = []
        for g in groups:
            result = confirm_duplicates_tier2(g)
            if result is not None:
                confirmed.append(result)
        groups = confirmed

    return groups


def find_all_redundant(
    scanned: list[ScannedDisc],
    *,
    use_perceptual_hash: bool = False,
) -> tuple[list[DuplicateGroup], list[CompilationGroup]]:
    """Find both exact duplicates and compilation ('play all') files.

    Runs compilation detection per disc group so compilations are only
    matched against files from the same disc/folder.

    Returns:
        A tuple of (duplicate_groups, compilation_groups).
    """
    duplicates = find_duplicates(
        scanned, use_perceptual_hash=use_perceptual_hash,
    )
    log.debug("find_all_redundant: %d duplicate group(s) found", len(duplicates))

    # Remove exact duplicates first so they don't confuse compilation detection
    deduped = remove_duplicates(scanned, duplicates)

    # Run compilation detection per disc group
    compilations: list[CompilationGroup] = []
    for disc in deduped:
        log.debug("Running compilation detection on disc '%s' (%d files)",
                  disc.folder_name, len(disc.files))
        compilations.extend(find_compilations(disc.files))

    log.debug("find_all_redundant: %d compilation(s) found", len(compilations))

    return duplicates, compilations


def remove_duplicates(
    scanned: list[ScannedDisc],
    groups: list[DuplicateGroup],
    compilations: list[CompilationGroup] | None = None,
) -> list[ScannedDisc]:
    """Return a copy of *scanned* with duplicate and compilation files removed.

    For each duplicate group, keeps the recommended file and drops the rest.
    For each compilation group, drops the combined file (keeps individual parts).
    """
    discard_paths = {
        f.path for g in groups for f in g.duplicates
    }
    if compilations:
        for c in compilations:
            discard_paths.add(c.compilation.path)

    if not discard_paths:
        return scanned

    result: list[ScannedDisc] = []
    for disc in scanned:
        filtered = [f for f in disc.files if f.path not in discard_paths]
        if filtered:
            result.append(ScannedDisc(folder_name=disc.folder_name, files=filtered))
    return result
