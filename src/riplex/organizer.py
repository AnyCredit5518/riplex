"""Organizer: compute destination paths and move/rename files."""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from riplex.models import (
    MatchCandidate,
    OrganizeResult,
    PlannedEpisode,
    PlannedMovie,
    PlannedShow,
    ScannedFile,
)
from riplex.normalize import (
    episode_file_name,
    movie_file_name,
    movie_folder_name,
    sanitize_filename,
    season_folder_name,
    show_folder_name,
)
from riplex.splitter import split_by_chapters

log = logging.getLogger(__name__)

# Regex to extract edition name from rip-time classification strings
# e.g. "Theatrical Cut (4K)" -> "Theatrical Cut"
_EDITION_RE = re.compile(
    r"((?:Extended|Director'?s|Unrated|Ultimate|Special|Theatrical)\s+(?:Cut|Edition|Version))",
    re.IGNORECASE,
)
_FORMAT_EDITION_RE = re.compile(r"\b(3D|IMAX|Open Matte)\b", re.IGNORECASE)
_VERSION_4K_RE = re.compile(r"\b(?:4K|2160p)\b", re.IGNORECASE)
_VERSION_1080P_RE = re.compile(r"\b1080p\b", re.IGNORECASE)

# Leading "S01E03 - " on a rip-time classification, produced by the
# analysis step's TMDb enrichment. When present, the season and
# episode were resolved at rip time and can flow straight through to
# the destination path without a second title lookup.
_CLASSIFICATION_SE_PREFIX_RE = re.compile(
    r"^S(\d{2,3})E(\d{2,4})\s*-\s*", re.IGNORECASE,
)


def _find_episode_by_se(
    plan: PlannedShow, season_number: int, episode_number: int,
) -> PlannedEpisode | None:
    """Find an episode in a PlannedShow by (season, episode) number."""
    for season in plan.seasons:
        if season.season_number != season_number:
            continue
        for ep in season.episodes:
            if ep.episode_number == episode_number:
                return ep
    return None


def _episode_from_classification_se(
    plan: PlannedShow, classification: str,
) -> PlannedEpisode | None:
    """Resolve an episode from a classification's leading ``SxxEyy -`` tag.

    Returns ``None`` when no tag is present, when the season/episode
    numbers don't exist in the plan, or when the input is empty. Legacy
    manifests (rips from before TMDb enrichment landed) hit the first
    branch and fall through to the fuzzy title-based lookup.
    """
    if not classification:
        return None
    m = _CLASSIFICATION_SE_PREFIX_RE.match(classification)
    if not m:
        return None
    return _find_episode_by_se(plan, int(m.group(1)), int(m.group(2)))


def _extract_movie_edition(text: str) -> str:
    """Extract a Plex movie edition label from classifier/match text."""
    m = _EDITION_RE.search(text)
    if m:
        return m.group(1)
    m = _FORMAT_EDITION_RE.search(text)
    if not m:
        return ""
    value = m.group(1)
    if value.lower() == "open matte":
        return "Open Matte"
    return value.upper()


def _extract_movie_version_suffix(text: str) -> str:
    """Extract a Plex multi-version suffix from classifier/match text."""
    if _VERSION_4K_RE.search(text):
        return "4k"
    if _VERSION_1080P_RE.search(text):
        return "1080p"
    return ""


def _infer_movie_version_suffix(scanned_file: ScannedFile | None, edition: str | None) -> str:
    """Infer a Plex multi-version suffix from scanned video dimensions."""
    if not scanned_file:
        return ""
    if scanned_file.max_width >= 3840 or scanned_file.max_height >= 2160:
        return "4k"
    if scanned_file.max_width >= 1920 or scanned_file.max_height >= 1080:
        return "1080p"
    return ""

# Map dvdcompare feature_type strings to Plex extras folder names
_EXTRAS_FOLDER_MAP: dict[str, str] = {
    "documentary": "Featurettes",
    "documentaries": "Featurettes",
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
    "short": "Shorts",
}

# Keyword fallback: if the feature_type *contains* one of these words, use
# the mapped folder.  Checked in order; first match wins.
_EXTRAS_KEYWORD_MAP: list[tuple[str, str]] = [
    ("trailer", "Trailers"),
    ("behind-the-scenes", "Behind The Scenes"),
    ("behind the scenes", "Behind The Scenes"),
    ("deleted scene", "Deleted Scenes"),
    ("interview", "Interviews"),
    ("documentary", "Featurettes"),
    ("featurette", "Featurettes"),
    ("short", "Shorts"),
]


@dataclass
class FileMove:
    """A planned file move from source to destination."""

    source: str
    destination: str
    label: str  # what this file was matched to
    confidence: str
    delta_seconds: int = 0  # |file_runtime - target_runtime|, for diagnostics


@dataclass
class SplitMove:
    """A file that needs chapter-based splitting before moving."""

    source: str
    chapter_destinations: list[str]  # one destination per chapter
    chapter_labels: list[str]  # one label per chapter
    confidence: str
    original_label: str = ""  # the dvdcompare match label
    delta_seconds: int = 0


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
    normalized = feature_type.lower().strip().rstrip(":")
    # Exact match first
    result = _EXTRAS_FOLDER_MAP.get(normalized)
    if result:
        return result
    # Keyword fallback for compound types like "4K remastered trailer"
    for keyword, folder in _EXTRAS_KEYWORD_MAP:
        if keyword in normalized:
            return folder
    return "Other"


def _extract_feature_type(label: str) -> str:
    """Extract the feature type from a match label like 'Disc 3: Title (documentary)'."""
    if "(" in label and label.endswith(")"):
        return label[label.rfind("(") + 1 : -1]
    return ""


_CLASSIFICATION_TYPE_PREFIX_RE = re.compile(r"^\[([^\]]+)\]\s*")


def _extract_classification_type(classification: str | None) -> str:
    """Return the ``[type]`` prefix from a rip-time classification.

    ``"[extra] Start-up Trailers (1080p)"`` -> ``"extra"``. Empty
    when the classification carries no bracketed prefix (episodes,
    play-alls, main films).
    """
    if not classification:
        return ""
    m = _CLASSIFICATION_TYPE_PREFIX_RE.match(classification)
    return m.group(1).strip() if m else ""


_TRAILER_PATTERN = re.compile(
    r"^(trailer|teaser|tv\s*spot|promo)\b", re.IGNORECASE,
)


def _infer_extras_folder(title: str) -> str:
    """Infer a Plex extras folder from the title when no type annotation exists."""
    if _TRAILER_PATTERN.search(title.lstrip("-").strip().strip('"')):
        return "Trailers"
    return "Featurettes"


def _find_episode_by_title(
    plan: PlannedShow, title: str,
) -> PlannedEpisode | None:
    """Find an episode in a PlannedShow by title.

    Tries case-insensitive exact match first. If that misses, falls
    back to fuzzy matching via :func:`_episode_name_similarity`
    (normalized-substring at 0.95, else difflib) so dvdcompare titles
    like ``Domestic Pilot`` still route to TMDb's ``Pilot``,
    ``Spellingg Bee`` to ``Spelling Bee``, and punctuation-only diffs
    (``Game, Set... Muuurder?`` vs ``Game, Set, ... Muuurder?``) don't
    end up "unmatched" at the organize step.
    """
    from riplex.disc.analysis import _episode_name_similarity

    title_lower = title.lower().strip()
    for season in plan.seasons:
        for ep in season.episodes:
            if ep.title.lower().strip() == title_lower:
                return ep

    best_ep: PlannedEpisode | None = None
    best_score = 0.0
    for season in plan.seasons:
        for ep in season.episodes:
            score = _episode_name_similarity(title, ep.title)
            if score > best_score:
                best_score = score
                best_ep = ep
    if best_score >= 0.75:
        return best_ep
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
            # Only consider splitting files whose current match is a
            # play-all / compilation entry.  Standalone featurettes that
            # happen to have chapters matching missing entries should be
            # left alone.
            if (sf and len(sf.chapter_durations) > 1
                    and move.label and "play all" in move.label.lower()):
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

    # Also index ScannedFile objects by their absolute path so callers
    # that pass basename-keyed maps still resolve correctly when two
    # discs produce files with colliding basenames. When the caller
    # passes a path-keyed map here, this becomes a no-op remap.
    scanned_by_path: dict[str, ScannedFile] = {}
    for sf in scanned_files.values():
        if sf.path:
            scanned_by_path[sf.path] = sf

    def _resolve_scanned(candidate: MatchCandidate) -> ScannedFile | None:
        if candidate.file_path and candidate.file_path in scanned_by_path:
            return scanned_by_path[candidate.file_path]
        return scanned_files.get(candidate.file_name)

    def _resolve_source(candidate: MatchCandidate) -> str:
        if candidate.file_path:
            return candidate.file_path
        return path_map.get(candidate.file_name, "")

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
        source = _resolve_source(candidate)

        # Detect split candidate: TV extra with chapter count matching Season 00
        if isinstance(plan, PlannedShow) and season0_episodes:
            feature_type = _extract_feature_type(candidate.matched_label)
            sf = _resolve_scanned(candidate)
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

        dest = _compute_destination(candidate, plan, base, _resolve_scanned(candidate))
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
                delta_seconds=candidate.delta_seconds,
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
    scanned_file: ScannedFile | None = None,
) -> Path | None:
    """Compute the Plex-canonical destination path for a matched file.

    Returns ``None`` if a valid Plex path cannot be determined (e.g. a
    TV episode title that doesn't match any TMDb episode).
    """
    label = candidate.matched_label
    log.debug("_compute_destination: label='%s'", label)

    # SE-first: the rip-time classification is authoritative. When the
    # classifier tagged this file with a TMDb-enriched "SxxEyy - Title"
    # prefix (recorded in the manifest at rip time), route directly by
    # (season, episode) — before consulting the dvdcompare match label.
    # The label loses episode identity when the episode title carries a
    # parenthetical (e.g. "Shawn and Gus in Drag (Racing)", which the
    # feature-type branch below mistakes for an extra) or when dvdcompare
    # files the episode under a disc's extras (e.g. an "(Extended
    # Version)" listing). Honoring the manifest avoids re-deriving — and
    # mis-deriving — a match that was already correct at rip time.
    if isinstance(plan, PlannedShow):
        se_ep = _episode_from_classification_se(plan, candidate.classification)
        if se_ep is not None:
            fname = episode_file_name(
                plan.canonical_title, plan.year,
                se_ep.season_number, se_ep.episode_number, se_ep.title,
            )
            dest = base / season_folder_name(se_ep.season_number) / fname
            log.debug(
                "  -> episode by SE-in-classification '%s' (pre-label): %s",
                candidate.classification, dest,
            )
            return dest

    # Movie main file
    if "(movie)" in label:
        edition = None
        version_suffix = ""
        # Check for edition in label (from multi-edition disc targets)
        # e.g. "Disc 1: Theatrical Cut (movie)"
        if label.startswith("Disc ") and ": " in label:
            edition_part = label.split(": ", 1)[1].replace(" (movie)", "")
            edition = _extract_movie_edition(edition_part) or None
            version_suffix = _extract_movie_version_suffix(edition_part)
        # Fallback: check rip-time classification
        if not edition and candidate.classification:
            edition = _extract_movie_edition(candidate.classification) or None
        if not version_suffix and candidate.classification:
            version_suffix = _extract_movie_version_suffix(candidate.classification)
        if not version_suffix:
            version_suffix = _infer_movie_version_suffix(scanned_file, edition)
        movie_base = base.parent / movie_folder_name(plan.canonical_title, plan.year, edition=edition) if edition else base
        file_name = movie_file_name(
            plan.canonical_title,
            plan.year,
            edition=edition,
            version_suffix=version_suffix,
        )
        dest = movie_base / file_name
        log.debug("  -> movie main file (edition=%s, version=%s): %s", edition, version_suffix, dest)
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
                # SE-first: when the rip-time classification carries a
                # TMDb-enriched "S01E03 - Title" prefix, route directly
                # by (season, episode) — deterministic and immune to
                # later TMDb title drift or dvdcompare↔TMDb spelling
                # fuzziness.
                se_ep = _episode_from_classification_se(plan, candidate.classification)
                if se_ep is not None:
                    fname = episode_file_name(
                        plan.canonical_title, plan.year,
                        se_ep.season_number, se_ep.episode_number, se_ep.title,
                    )
                    dest = base / season_folder_name(se_ep.season_number) / fname
                    log.debug(
                        "  -> episode by SE-in-classification '%s': %s",
                        candidate.classification, dest,
                    )
                    return dest
                # If the rip-time classifier explicitly tagged this
                # file as an extra (via a "[type]" prefix), don't try
                # to route it as an episode via fuzzy title matching.
                # dvdcompare sometimes lists the same episode name
                # twice (once as the actual episode, once as a bonus
                # re-edit); ``enrich_dvd_entries_with_tmdb`` demotes
                # the shorter entry to ``extra`` and the classifier
                # stamps it with ``[extra]``, but the *label* alone
                # still looks like the episode's — so a fuzzy title
                # lookup would clobber the real episode's destination
                # with the duplicate re-edit. Honoring the classifier
                # here keeps the two files on distinct paths.
                class_type = _extract_classification_type(candidate.classification)
                if class_type:
                    folder = _extras_folder(class_type)
                    if folder == "Other":
                        folder = _infer_extras_folder(title_part)
                    safe = sanitize_filename(title_part)
                    dest = base / folder / f"{safe}.mkv"
                    log.debug(
                        "  -> extras via classification [%s] -> '%s': %s",
                        class_type, folder, dest,
                    )
                    return dest
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
    # --- Execute moves/splits first ---
    for move in organize_plan.moves:
        if not dry_run:
            dest = Path(move.destination)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(move.source, dest)
            log.info("Moved: %s -> %s ([%s] %s)", move.source, move.destination, move.confidence, move.label)

    for split in organize_plan.splits:
        if not dry_run:
            import tempfile

            output_names = [Path(d).name for d in split.chapter_destinations]
            with tempfile.TemporaryDirectory() as tmp:
                split_files = split_by_chapters(split.source, tmp, output_names)
                for sf, dest in zip(split_files, split.chapter_destinations):
                    dest_path = Path(dest)
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(sf, dest_path)
            log.info("Split: %s -> %d files", split.source, len(split.chapter_destinations))

    # Handle unmatched files
    for f in organize_plan.unmatched:
        if unmatched_policy == "move" and unmatched_dir is not None:
            dest = unmatched_dir / f.name
            if not dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(f.path, dest)
                log.info("Moved unmatched: %s -> %s", f.path, dest)
        elif unmatched_policy == "delete":
            if not dry_run:
                Path(f.path).unlink()
                log.info("Deleted unmatched: %s", f.path)

    # --- Build grouped output ---
    return format_organize_plan(organize_plan, dry_run, unmatched_policy, unmatched_dir)


def format_organize_plan(
    organize_plan: OrganizePlan,
    dry_run: bool,
    unmatched_policy: str,
    unmatched_dir: Path | None,
) -> list[str]:
    """Build grouped, human-readable output lines for an organize plan."""
    actions: list[str] = []

    # Determine output root from first move destination
    output_base = ""
    all_dests = [Path(m.destination) for m in organize_plan.moves]
    for split in organize_plan.splits:
        all_dests.extend(Path(d) for d in split.chapter_destinations)
    if all_dests:
        # Find common ancestor of all destinations
        parts_list = [d.parts for d in all_dests]
        common = []
        for level in zip(*parts_list):
            if len(set(level)) == 1:
                common.append(level[0])
            else:
                break
        if common:
            output_base = str(Path(*common))

    if output_base:
        verb = "Would organize to" if dry_run else "Output"
        actions.append(f"{verb}: {output_base}")
        actions.append("")

    # Group moves by subfolder relative to output_base
    groups: dict[str, list[tuple[str, str]]] = {}  # folder -> [(dest_name, source_name)]
    for move in organize_plan.moves:
        dest_path = Path(move.destination)
        source_name = Path(move.source).name
        dest_name = dest_path.name
        if output_base:
            try:
                rel = dest_path.relative_to(output_base)
                folder = str(rel.parent) if rel.parent != Path(".") else ""
            except ValueError:
                folder = ""
        else:
            folder = str(dest_path.parent)
        groups.setdefault(folder, []).append((dest_name, source_name))
        log.debug("Plan: %s <- %s ([%s] %s)", move.destination, move.source, move.confidence, move.label)

    for split in organize_plan.splits:
        source_name = Path(split.source).name
        for dest, label in zip(split.chapter_destinations, split.chapter_labels):
            dest_path = Path(dest)
            dest_name = dest_path.name
            if output_base:
                try:
                    rel = dest_path.relative_to(output_base)
                    folder = str(rel.parent) if rel.parent != Path(".") else ""
                except ValueError:
                    folder = ""
            else:
                folder = str(dest_path.parent)
            groups.setdefault(folder, []).append((dest_name, f"{source_name} (split)"))

    # Print groups in a logical order: root first, then alphabetical subfolders
    root_items = groups.pop("", [])
    if root_items:
        header = "Main Feature" if len(root_items) == 1 else f"Main ({len(root_items)} files)"
        actions.append(header)
        for dest_name, source_name in root_items:
            actions.append(f"  {dest_name:<45} <- {source_name}")
        actions.append("")

    for folder in sorted(groups.keys()):
        items = groups[folder]
        actions.append(f"{folder} ({len(items)} {'file' if len(items) == 1 else 'files'})")
        for dest_name, source_name in items:
            actions.append(f"  {dest_name:<45} <- {source_name}")
        actions.append("")

    # Unmatched
    if organize_plan.unmatched:
        if unmatched_policy == "ignore":
            actions.append(f"Unmatched ({len(organize_plan.unmatched)} files, left in place)")
            for f in organize_plan.unmatched:
                actions.append(f"  {f.name}")
        elif unmatched_policy == "move" and unmatched_dir:
            verb = "would move to" if dry_run else "moved to"
            actions.append(f"Unmatched ({len(organize_plan.unmatched)} files, {verb} {unmatched_dir})")
            for f in organize_plan.unmatched:
                actions.append(f"  {f.name}")
        elif unmatched_policy == "delete":
            verb = "would delete" if dry_run else "deleted"
            actions.append(f"Unmatched ({len(organize_plan.unmatched)} files, {verb})")
            for f in organize_plan.unmatched:
                actions.append(f"  {f.name}")
        actions.append("")

    # Missing
    if organize_plan.missing:
        actions.append(f"Not Found ({len(organize_plan.missing)} expected items)")
        for label in organize_plan.missing:
            # Clean up dvdcompare labels: strip outer parens like "((with Play All))"
            clean = label
            if clean.startswith("(") and clean.endswith(")"):
                clean = clean[1:-1]
            actions.append(f"  {clean}")
        actions.append("")

    return actions


def archive_source_folder(
    source_folder: Path,
    archive_root: str,
    *,
    prune_stop: Path | None = None,
) -> Path | None:
    """Move *source_folder* into *archive_root*, preserving the folder name.

    Returns the destination path on success, or ``None`` if archiving is
    skipped (empty *archive_root*) or fails.

    After a successful move, walks up ``source_folder.parent`` and
    ``rmdir``s empty ancestors so a season-nested rip like
    ``<rip_root>/Psych (2006)/Season 02`` doesn't leave the empty
    ``Psych (2006)/`` shell behind. Stops at *prune_stop* (typically
    the rip output root) or at the first non-empty ancestor. Never
    removes *prune_stop* itself.
    """
    if not archive_root:
        return None
    dest = Path(archive_root) / source_folder.name
    parent = source_folder.parent
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source_folder), dest)
        log.info("Archived: %s -> %s", source_folder, dest)
    except OSError as exc:
        log.warning("Failed to archive %s: %s", source_folder, exc)
        return None

    stop = prune_stop.resolve() if prune_stop else None
    current = parent
    for _ in range(4):  # bounded walk; TV is at most 2 hops
        try:
            resolved = current.resolve()
        except OSError:
            break
        if stop is not None and resolved == stop:
            break
        try:
            current.rmdir()  # only succeeds if empty
            log.info("Pruned empty parent: %s", current)
        except OSError:
            break
        current = current.parent
    return dest
