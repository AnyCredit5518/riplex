"""Organizer: compute destination paths and move/rename files."""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from plex_planner.models import (
    MatchCandidate,
    OrganizeResult,
    PlannedEpisode,
    PlannedMovie,
    PlannedShow,
    ScannedFile,
)
from plex_planner.normalize import (
    episode_file_name,
    movie_folder_name,
    sanitize_filename,
    season_folder_name,
    show_folder_name,
)
from plex_planner.splitter import split_by_chapters

log = logging.getLogger(__name__)

# Map dvdcompare feature_type strings to Plex extras folder names
_EXTRAS_FOLDER_MAP: dict[str, str] = {
    "documentary": "Featurettes",
    "featurette": "Featurettes",
    "featurettes": "Featurettes",
    "behind-the-scenes montage": "Behind The Scenes",
    "behind-the-scenes": "Behind The Scenes",
    "interviews": "Interviews",
    "interview": "Interviews",
    "deleted scene": "Deleted Scenes",
    "deleted scenes": "Deleted Scenes",
    "trailer": "Trailers",
    "trailers": "Trailers",
}


@dataclass
class FileMove:
    """A planned file move from source to destination."""

    source: str
    destination: str
    label: str  # what this file was matched to
    confidence: str


@dataclass
class SplitMove:
    """A file that needs chapter-based splitting before moving."""

    source: str
    chapter_destinations: list[str]  # one destination per chapter
    chapter_labels: list[str]  # one label per chapter
    confidence: str
    original_label: str = ""  # the dvdcompare match label


@dataclass
class OrganizePlan:
    """The complete plan for organizing files."""

    moves: list[FileMove] = field(default_factory=list)
    splits: list[SplitMove] = field(default_factory=list)
    unmatched: list[ScannedFile] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def _extras_folder(feature_type: str) -> str:
    """Map a feature type to a Plex extras folder name."""
    if not feature_type:
        return "Other"
    return _EXTRAS_FOLDER_MAP.get(feature_type.lower(), "Other")


def _extract_feature_type(label: str) -> str:
    """Extract the feature type from a match label like 'Disc 3: Title (documentary)'."""
    if "(" in label and label.endswith(")"):
        return label[label.rfind("(") + 1 : -1]
    return ""


_TRAILER_PATTERN = re.compile(
    r"^(trailer|teaser|tv\s*spot|promo)", re.IGNORECASE,
)


def _infer_extras_folder(title: str) -> str:
    """Infer a Plex extras folder from the title when no type annotation exists."""
    if _TRAILER_PATTERN.search(title.lstrip("-").strip().strip('"')):
        return "Trailers"
    return "Featurettes"


def _find_episode_by_title(
    plan: PlannedShow, title: str,
) -> PlannedEpisode | None:
    """Find an episode in a PlannedShow by case-insensitive title match."""
    title_lower = title.lower().strip()
    for season in plan.seasons:
        for ep in season.episodes:
            if ep.title.lower().strip() == title_lower:
                return ep
    return None


# Type alias for disc targets: (label, runtime_seconds, disc_number)
DiscTarget = tuple[str, int, int | None]


def _match_chapters_to_pool(
    chapter_durations: list[int],
    pool: dict[str, int],
    tolerance: int = 15,
) -> list[tuple[str, int]] | None:
    """Match each chapter duration to a distinct missing entry by runtime.

    Returns a list of ``(label, runtime)`` in chapter order, or ``None``
    if any chapter cannot be matched.
    """
    available = dict(pool)
    result: list[tuple[str, int]] = []
    for ch_dur in chapter_durations:
        best_label: str | None = None
        best_delta = tolerance + 1
        for label, runtime in available.items():
            delta = abs(ch_dur - runtime)
            if delta <= tolerance and delta < best_delta:
                best_delta = delta
                best_label = label
        if best_label is None:
            return None
        result.append((best_label, available[best_label]))
        del available[best_label]
    return result


def _apply_chapter_to_missing_splits(
    moves: list[FileMove],
    missing_labels: list[str],
    disc_targets: Sequence[DiscTarget],
    scanned_files: dict[str, ScannedFile],
    plan: PlannedMovie | PlannedShow,
    base: Path,
    tolerance: int = 15,
) -> tuple[list[FileMove], list[SplitMove], list[str]]:
    """Convert moves whose chapters match missing disc entries into splits.

    For each move whose file has N chapters, if those N chapter durations
    each match a distinct missing entry's runtime (within *tolerance*
    seconds), the move is replaced by a :class:`SplitMove`.  The original
    match label is released back into the missing pool, potentially
    enabling further conversions in subsequent iterations.

    Returns ``(remaining_moves, new_splits, updated_missing)``.
    """
    target_runtimes = {label: runtime for label, runtime, _ in disc_targets}

    # Build pool of missing entries that have a known runtime
    missing_pool: dict[str, int] = {}
    missing_no_runtime: list[str] = []
    for label in missing_labels:
        runtime = target_runtimes.get(label, 0)
        if runtime > 0:
            missing_pool[label] = runtime
        else:
            missing_no_runtime.append(label)

    remaining_moves = list(moves)
    all_splits: list[SplitMove] = []

    changed = True
    while changed:
        changed = False
        next_moves: list[FileMove] = []
        for move in remaining_moves:
            file_name = Path(move.source).name
            sf = scanned_files.get(file_name)
            if sf and len(sf.chapter_durations) > 1:
                log.debug("Chapter-to-missing: checking %s (%d chapters) against %d missing entries",
                          file_name, len(sf.chapter_durations), len(missing_pool))
                matches = _match_chapters_to_pool(
                    sf.chapter_durations, missing_pool, tolerance,
                )
                if matches is not None:
                    log.debug("Chapter-to-missing: %s matched -> %s",
                              file_name, [m[0] for m in matches])
                    # Build destinations via _compute_destination
                    dests: list[str] = []
                    labels: list[str] = []
                    valid = True
                    for label, runtime in matches:
                        candidate = MatchCandidate(
                            file_name=file_name,
                            file_duration_seconds=runtime,
                            matched_label=label,
                            matched_runtime_seconds=runtime,
                            delta_seconds=0,
                            confidence=move.confidence,
                        )
                        dest = _compute_destination(candidate, plan, base)
                        if dest is None:
                            valid = False
                            break
                        dests.append(str(dest))
                        labels.append(label)

                    if valid:
                        all_splits.append(
                            SplitMove(
                                source=move.source,
                                chapter_destinations=dests,
                                chapter_labels=labels,
                                confidence=move.confidence,
                                original_label=move.label,
                            )
                        )
                        # Remove consumed missing entries
                        for label, _ in matches:
                            missing_pool.pop(label, None)
                        # Release the original match back to missing
                        orig_runtime = target_runtimes.get(move.label, 0)
                        if orig_runtime > 0:
                            missing_pool[move.label] = orig_runtime
                        else:
                            missing_no_runtime.append(move.label)
                        changed = True
                        continue
            next_moves.append(move)
        remaining_moves = next_moves

    updated_missing = list(missing_pool.keys()) + missing_no_runtime
    return remaining_moves, all_splits, updated_missing


_MIN_EXTRAS_DURATION = 60  # seconds; shorter files are likely menus/bumpers


def build_organize_plan(
    result: OrganizeResult,
    plan: PlannedMovie | PlannedShow,
    output_root: Path,
    scanned_files_by_name: dict[str, str] | None = None,
    scanned_files: dict[str, ScannedFile] | None = None,
    disc_targets: Sequence[DiscTarget] | None = None,
    unmatched_policy: str = "ignore",
) -> OrganizePlan:
    """Build a plan of file moves from match results.

    *scanned_files_by_name* maps file names to absolute source paths.
    *scanned_files* maps file names to full ScannedFile objects (enables
    chapter-based split detection for TV shows).
    *disc_targets* is a list of ``(label, runtime_seconds, disc_number)``
    tuples from :func:`collect_disc_targets`; when provided, matched
    files whose chapters align with missing entries are converted to
    :class:`SplitMove` instances.
    """
    if scanned_files_by_name is None:
        scanned_files_by_name = {}
    if scanned_files is None:
        scanned_files = {}

    # Merge path info: scanned_files takes precedence
    path_map = dict(scanned_files_by_name)
    for name, sf in scanned_files.items():
        path_map.setdefault(name, sf.path)

    moves: list[FileMove] = []
    splits: list[SplitMove] = []
    unmatched = list(result.unmatched)

    if isinstance(plan, PlannedMovie):
        base = output_root / "Movies" / movie_folder_name(plan.canonical_title, plan.year)
    else:
        base = output_root / "TV Shows" / show_folder_name(plan.canonical_title, plan.year)
    log.debug("Base output path: %s", base)

    # Collect Season 00 episodes for TV split detection
    season0_episodes: list[PlannedEpisode] = []
    if isinstance(plan, PlannedShow):
        for season in plan.seasons:
            if season.season_number == 0:
                season0_episodes = sorted(
                    season.episodes, key=lambda e: e.episode_number,
                )
                break

    for candidate in result.matched:
        source = path_map.get(candidate.file_name, "")

        # Detect split candidate: TV extra with chapter count matching Season 00
        if isinstance(plan, PlannedShow) and season0_episodes:
            feature_type = _extract_feature_type(candidate.matched_label)
            sf = scanned_files.get(candidate.file_name)
            if feature_type and sf and sf.chapter_count > 1:
                if sf.chapter_count == len(season0_episodes):
                    # Guard: file duration must be close to the sum of
                    # Season 00 runtimes to avoid splitting a single
                    # special that just has navigation chapters.
                    total_s0_runtime = sum(
                        ep.runtime_seconds for ep in season0_episodes
                    )
                    if total_s0_runtime <= 0 or not (
                        0.75 <= sf.duration_seconds / total_s0_runtime <= 1.25
                    ):
                        log.debug("Season 00 split rejected for %s: duration %ds vs total S00 %ds",
                                  candidate.file_name, sf.duration_seconds, total_s0_runtime)
                        pass  # duration mismatch; fall through to normal move
                    else:
                        log.debug("Season 00 split detected for %s: %d chapters -> %d S00 episodes",
                                  candidate.file_name, sf.chapter_count, len(season0_episodes))
                        dests: list[str] = []
                        labels: list[str] = []
                        for ep in season0_episodes:
                            fname = episode_file_name(
                                plan.canonical_title, plan.year,
                                ep.season_number, ep.episode_number, ep.title,
                            )
                            dest = base / season_folder_name(ep.season_number) / fname
                            dests.append(str(dest))
                            labels.append(
                                f"s{ep.season_number:02d}e{ep.episode_number:02d} - {ep.title}"
                            )
                        splits.append(
                            SplitMove(
                                source=source,
                                chapter_destinations=dests,
                                chapter_labels=labels,
                                confidence=candidate.confidence,
                                original_label=candidate.matched_label,
                            )
                        )
                        continue

        dest = _compute_destination(candidate, plan, base)
        if dest is None:
            # Could not resolve to a valid Plex path; treat as unmatched.
            log.debug("No valid destination for '%s' (label='%s'), treating as unmatched",
                      candidate.file_name, candidate.matched_label)
            unmatched.append(
                ScannedFile(name=candidate.file_name, path=source,
                            duration_seconds=candidate.file_duration_seconds),
            )
            continue
        log.debug("Destination for '%s': %s (label='%s')",
                  candidate.file_name, dest, candidate.matched_label)
        moves.append(
            FileMove(
                source=source,
                destination=str(dest),
                label=candidate.matched_label,
                confidence=candidate.confidence,
            )
        )

    # Post-process: detect moves whose chapters match missing entries
    final_missing = list(result.missing)
    if disc_targets and scanned_files:
        log.debug("Running chapter-to-missing split detection (%d moves, %d missing)",
                  len(moves), len(result.missing))
        moves, chapter_splits, final_missing = _apply_chapter_to_missing_splits(
            moves, result.missing, disc_targets, scanned_files, plan, base,
        )
        if chapter_splits:
            log.debug("Chapter-to-missing produced %d split(s)", len(chapter_splits))
        splits.extend(chapter_splits)

    # Route unmatched files to extras if policy requests it
    if unmatched_policy == "extras":
        log.debug("Routing %d unmatched file(s) with extras policy (min %ds)",
                  len(unmatched), _MIN_EXTRAS_DURATION)
        extras_routed: list[ScannedFile] = []
        extra_num = 0
        for f in unmatched:
            if f.duration_seconds >= _MIN_EXTRAS_DURATION:
                extra_num += 1
                dest = base / "Other" / f"Extra {extra_num}.mkv"
                log.debug("Unmatched extra: %s (%ds) -> %s",
                          f.name, f.duration_seconds, dest)
                moves.append(
                    FileMove(
                        source=f.path,
                        destination=str(dest),
                        label=f"(unmatched extra) {f.name}",
                        confidence="none",
                    )
                )
            else:
                log.debug("Unmatched too short for extra: %s (%ds < %ds)",
                          f.name, f.duration_seconds, _MIN_EXTRAS_DURATION)
                extras_routed.append(f)
        unmatched = extras_routed

    return OrganizePlan(
        moves=moves,
        splits=splits,
        unmatched=unmatched,
        missing=final_missing,
    )


def _compute_destination(
    candidate: MatchCandidate,
    plan: PlannedMovie | PlannedShow,
    base: Path,
) -> Path | None:
    """Compute the Plex-canonical destination path for a matched file.

    Returns ``None`` if a valid Plex path cannot be determined (e.g. a
    TV episode title that doesn't match any TMDb episode).
    """
    label = candidate.matched_label
    log.debug("_compute_destination: label='%s'", label)

    # Movie main file
    if "(movie)" in label:
        safe_title = sanitize_filename(plan.canonical_title)
        dest = base / f"{safe_title} ({plan.year}).mkv"
        log.debug("  -> movie main file: %s", dest)
        return dest

    # Episode: label like "Disc 1: Coasts" or "s01e01 - Title"
    # Check for episode label from match_files (s##e## format)
    if label.startswith("s") and "e" in label[:5]:
        safe = sanitize_filename(label.split(" - ", 1)[-1]) if " - " in label else label
        dest = base / f"{safe}.mkv"
        log.debug("  -> episode format label: %s", dest)
        return dest

    # Disc episode: "Disc N: Title"
    if label.startswith("Disc ") and ": " in label:
        title_part = label.split(": ", 1)[1]
        feature_type = _extract_feature_type(title_part)
        if feature_type:
            # This is an extra; check if it matches a Season 00 episode first
            clean_title = title_part[: title_part.rfind("(")].strip()
            if isinstance(plan, PlannedShow):
                ep = _find_episode_by_title(plan, clean_title)
                if ep and ep.season_number == 0:
                    fname = episode_file_name(
                        plan.canonical_title, plan.year,
                        ep.season_number, ep.episode_number, ep.title,
                    )
                    dest = base / season_folder_name(0) / fname
                    log.debug("  -> S00 episode via feature_type: %s", dest)
                    return dest
            folder = _extras_folder(feature_type)
            safe = sanitize_filename(clean_title)
            dest = base / folder / f"{safe}.mkv"
            log.debug("  -> extras folder '%s': %s", folder, dest)
            return dest
        else:
            # This is an episode/content item without type annotation
            if isinstance(plan, PlannedShow):
                ep = _find_episode_by_title(plan, title_part)
                if ep:
                    fname = episode_file_name(
                        plan.canonical_title, plan.year,
                        ep.season_number, ep.episode_number, ep.title,
                    )
                    dest = base / season_folder_name(ep.season_number) / fname
                    log.debug("  -> episode by title lookup '%s': %s", title_part, dest)
                    return dest
                # No TMDb match; can't produce a valid Plex filename.
                log.debug("  -> no TMDb match for title '%s', returning None", title_part)
                return None
            folder = _infer_extras_folder(title_part)
            safe = sanitize_filename(title_part)
            dest = base / folder / f"{safe}.mkv"
            log.debug("  -> movie extras '%s': %s", folder, dest)
            return dest

    # Fallback: put in Other
    safe = sanitize_filename(label)
    dest = base / "Other" / f"{safe}.mkv"
    log.debug("  -> fallback Other: %s", dest)
    return dest


def execute_plan(
    organize_plan: OrganizePlan,
    dry_run: bool = True,
    unmatched_policy: str = "ignore",
    unmatched_dir: Path | None = None,
) -> list[str]:
    """Execute file moves. Returns a list of action descriptions.

    If *dry_run* is True (the default), no files are actually moved.

    *unmatched_policy* controls what happens to unmatched files:
    - ``"ignore"``: leave in place (default)
    - ``"move"``: move to *unmatched_dir*
    - ``"delete"``: remove the file
    """
    actions: list[str] = []

    for move in organize_plan.moves:
        desc = f"[{move.confidence}] {move.label}"
        if dry_run:
            actions.append(f"  WOULD MOVE: {move.source}")
            actions.append(f"          TO: {move.destination}")
            actions.append(f"       MATCH: {desc}")
            actions.append("")
        else:
            dest = Path(move.destination)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(move.source, dest)
            actions.append(f"  MOVED: {move.source} -> {move.destination} ({desc})")

    for split in organize_plan.splits:
        if dry_run:
            actions.append(f"  WOULD SPLIT: {split.source}")
            actions.append(f"     ORIGINAL: {split.original_label}")
            for dest, label in zip(split.chapter_destinations, split.chapter_labels):
                actions.append(f"   CHAPTER -> {dest}")
                actions.append(f"      MATCH: [{split.confidence}] {label}")
            actions.append("")
        else:
            import tempfile

            output_names = [Path(d).name for d in split.chapter_destinations]
            with tempfile.TemporaryDirectory() as tmp:
                split_files = split_by_chapters(split.source, tmp, output_names)
                for sf, dest in zip(split_files, split.chapter_destinations):
                    dest_path = Path(dest)
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(sf, dest_path)
            actions.append(f"  SPLIT: {split.source} -> {len(split.chapter_destinations)} files")
            for dest, label in zip(split.chapter_destinations, split.chapter_labels):
                actions.append(f"    -> {dest} ([{split.confidence}] {label})")

    if organize_plan.unmatched:
        actions.append("UNMATCHED FILES (no confident match found):")
        for f in organize_plan.unmatched:
            if unmatched_policy == "ignore":
                actions.append(f"  {f.name} ({f.duration_seconds}s) [ignored]")
            elif unmatched_policy == "move":
                if unmatched_dir is None:
                    actions.append(f"  {f.name} ({f.duration_seconds}s) [ignored, no move dir]")
                    continue
                dest = unmatched_dir / f.name
                if dry_run:
                    actions.append(f"  WOULD MOVE: {f.path}")
                    actions.append(f"          TO: {dest}")
                    actions.append("")
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(f.path, dest)
                    actions.append(f"  MOVED TO UNMATCHED: {f.path} -> {dest}")
            elif unmatched_policy == "delete":
                if dry_run:
                    actions.append(f"  WOULD DELETE: {f.path}")
                else:
                    Path(f.path).unlink()
                    actions.append(f"  DELETED: {f.path}")

    if organize_plan.missing:
        actions.append("MISSING CONTENT (expected but no file found):")
        for label in organize_plan.missing:
            actions.append(f"  {label}")

    return actions
