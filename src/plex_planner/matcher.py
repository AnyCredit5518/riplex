"""Runtime-based matching helper for ripped MKV files.

Stretch goal: given a list of ripped file durations and a planned result,
produce a non-destructive "possible matches" report.
"""

from __future__ import annotations

import logging
import re

from plex_planner.models import (
    MatchCandidate,
    OrganizeResult,
    PlannedDisc,
    PlannedEpisode,
    PlannedExtra,
    PlannedMovie,
    PlannedShow,
    ScannedDisc,
    ScannedFile,
)

log = logging.getLogger(__name__)

# Tolerance thresholds in seconds
_HIGH_THRESHOLD = 30
_MEDIUM_THRESHOLD = 120


def parse_duration(text: str) -> int:
    """Parse a human-entered duration string into total seconds.

    Supported formats:
      - "48m 12s" or "48m12s"
      - "1h 2m 30s"
      - "3024" (raw seconds)
      - "48:12" (mm:ss)
      - "1:02:30" (h:mm:ss)
    """
    text = text.strip()

    # Try h/m/s pattern: 1h 2m 30s, 48m 12s, etc.
    hms = re.match(
        r"(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+)s)?$", text, re.IGNORECASE
    )
    if hms and any(hms.groups()):
        h = int(hms.group(1) or 0)
        m = int(hms.group(2) or 0)
        s = int(hms.group(3) or 0)
        return h * 3600 + m * 60 + s

    # Try colon-separated: 1:02:30 or 48:12
    colon = re.match(r"(\d+):(\d{1,2}):(\d{1,2})$", text)
    if colon:
        return (
            int(colon.group(1)) * 3600
            + int(colon.group(2)) * 60
            + int(colon.group(3))
        )
    colon2 = re.match(r"(\d+):(\d{1,2})$", text)
    if colon2:
        return int(colon2.group(1)) * 60 + int(colon2.group(2))

    # Try raw seconds
    if text.isdigit():
        return int(text)

    return 0


def _confidence(delta: int) -> str:
    if delta <= _HIGH_THRESHOLD:
        return "high"
    if delta <= _MEDIUM_THRESHOLD:
        return "medium"
    return "low"


def match_files(
    ripped_files: list[tuple[str, int]],
    planned: PlannedMovie | PlannedShow,
) -> list[MatchCandidate]:
    """Match ripped files (name, duration_seconds) against a planned result.

    Returns a list of MatchCandidate objects sorted by file order, each
    containing the best-matching episode/movie entry.
    """
    targets = _collect_targets(planned)
    candidates: list[MatchCandidate] = []

    for file_name, file_dur in ripped_files:
        best_label = "no match"
        best_runtime = 0
        best_delta = 999999

        for label, runtime_s in targets:
            if runtime_s <= 0:
                continue
            delta = abs(file_dur - runtime_s)
            if delta < best_delta:
                best_delta = delta
                best_label = label
                best_runtime = runtime_s

        candidates.append(
            MatchCandidate(
                file_name=file_name,
                file_duration_seconds=file_dur,
                matched_label=best_label,
                matched_runtime_seconds=best_runtime,
                delta_seconds=best_delta,
                confidence=_confidence(best_delta),
            )
        )

    return candidates


def _collect_targets(
    planned: PlannedMovie | PlannedShow,
) -> list[tuple[str, int]]:
    """Extract (label, runtime_seconds) pairs from a planned result."""
    if isinstance(planned, PlannedMovie):
        return [(f"{planned.canonical_title} (movie)", planned.runtime_seconds)]

    targets: list[tuple[str, int]] = []
    for season in planned.seasons:
        for ep in season.episodes:
            label = (
                f"s{ep.season_number:02d}e{ep.episode_number:02d}"
                f" - {ep.title}"
            )
            targets.append((label, ep.runtime_seconds))
    return targets


def format_match_report(candidates: list[MatchCandidate]) -> str:
    """Format match candidates as a human-readable report."""
    lines: list[str] = ["Match Report", "=" * 60]
    for c in candidates:
        from plex_planner.normalize import format_runtime

        file_rt = format_runtime(c.file_duration_seconds)
        match_rt = format_runtime(c.matched_runtime_seconds)
        delta = format_runtime(c.delta_seconds) if c.delta_seconds > 0 else "0s"
        lines.append(
            f"  {c.file_name} ({file_rt})"
            f"  ->  {c.matched_label} ({match_rt})"
            f"  [delta: {delta}, confidence: {c.confidence}]"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Disc-aware matching (scanned files vs planned discs)
# ---------------------------------------------------------------------------

# Disc number used for the synthetic "movie" target so that it can be
# constrained to the film disc folder.
_FILM_DISC_MARKER = -1

# Absolute maximum delta (seconds) beyond which a pairing is rejected.
# Prevents garbage matches when no good candidate exists.
_MAX_MATCH_DELTA = 300

_PLAY_ALL_RE = re.compile(r"\bplay\s*all\b", re.IGNORECASE)


def collect_disc_targets(
    discs: list[PlannedDisc],
    plan: PlannedMovie | PlannedShow | None = None,
) -> list[tuple[str, int, int | None]]:
    """Build (label, runtime_seconds, disc_number) tuples.

    *disc_number* is the PlannedDisc.number the target belongs to, or
    ``_FILM_DISC_MARKER`` for the synthetic movie target (assigned to
    whichever disc has ``is_film=True``).
    """
    targets: list[tuple[str, int, int | None]] = []

    # Identify the film disc number (if any) so the movie target is
    # constrained to that disc's folder.
    film_disc_num: int | None = None
    for d in discs:
        if d.is_film:
            film_disc_num = d.number
            break

    if isinstance(plan, PlannedMovie) and plan.runtime_seconds > 0:
        targets.append(
            (f"{plan.canonical_title} (movie)", plan.runtime_seconds, film_disc_num)
        )

    for disc in discs:
        prefix = f"Disc {disc.number}"
        for ep in disc.episodes:
            if ep.runtime_seconds <= 0:
                continue
            targets.append((f"{prefix}: {ep.title}", ep.runtime_seconds, disc.number))

        # Collect non-play-all extras as targets; play-all entries are
        # redundant when individual parts are also listed on the disc.
        # Also skip "The Film ..." entries on film discs: they represent
        # the main feature which is already covered by the movie target.
        play_all_extras: list[PlannedExtra] = []
        regular_extras: list[PlannedExtra] = []
        for ex in disc.extras:
            if ex.runtime_seconds <= 0:
                continue
            if disc.is_film and ex.title.lower().startswith("the film"):
                log.debug("Disc %d: skipping film entry '%s' (covered by movie target)",
                          disc.number, ex.title)
                continue
            if _PLAY_ALL_RE.search(ex.title):
                play_all_extras.append(ex)
            else:
                regular_extras.append(ex)

        # Only include play-all entries if there are no other targets on
        # this disc (episodes or regular extras) to match against.
        has_parts = bool(disc.episodes) or bool(regular_extras)
        extras_to_add = regular_extras
        if play_all_extras and not has_parts:
            extras_to_add = play_all_extras
        elif play_all_extras:
            log.debug("Disc %d: filtering %d play-all target(s) (parts exist)",
                      disc.number, len(play_all_extras))

        for ex in extras_to_add:
            label = f"{prefix}: {ex.title}"
            if ex.feature_type:
                label += f" ({ex.feature_type})"
            targets.append((label, ex.runtime_seconds, disc.number))

    return targets


# ---------------------------------------------------------------------------
# Folder-to-disc mapping heuristics
# ---------------------------------------------------------------------------

_DISC_NUMBER_RE = re.compile(r"(?:disc|disk)\s*(\d+)|\bD(\d+)\b", re.IGNORECASE)
_BONUS_FOLDER_NAMES = {"special features", "bonus", "extras", "bonus features"}


def map_folders_to_discs(
    scanned: list[ScannedDisc],
    discs: list[PlannedDisc],
    plan: PlannedMovie | PlannedShow | None = None,
) -> dict[str, int | None]:
    """Map each scanned folder to a PlannedDisc number (or None).

    Heuristics applied in order:

    1. **Explicit disc number** in folder name (e.g. "Disc 1", "Planet
       Earth III - Disc 2").
    2. **Film disc**: the folder whose longest file is within 5 minutes
       of the movie runtime maps to the disc with ``is_film=True``.
    3. **Bonus folder**: names like "Special Features", "Bonus", or
       "Extras" map to the non-film disc that has the most extras.
    4. No match: ``None`` (falls back to global matching).
    """
    disc_numbers = {d.number for d in discs}
    mapping: dict[str, int | None] = {}
    claimed_discs: set[int] = set()

    # Pass 1: explicit disc number in folder name
    for sd in scanned:
        m = _DISC_NUMBER_RE.search(sd.folder_name)
        if m:
            num = int(m.group(1) or m.group(2))
            if num in disc_numbers and num not in claimed_discs:
                log.debug("Disc map pass 1: '%s' -> Disc %d (regex match)",
                          sd.folder_name, num)
                mapping[sd.folder_name] = num
                claimed_discs.add(num)
            elif num not in disc_numbers:
                log.debug("Disc map pass 1: '%s' matched number %d but no such disc exists",
                          sd.folder_name, num)
            else:
                log.debug("Disc map pass 1: '%s' matched number %d but already claimed",
                          sd.folder_name, num)

    # Pass 2: film disc (longest file matches movie runtime)
    film_disc = next((d for d in discs if d.is_film), None)
    if (
        film_disc is not None
        and film_disc.number not in claimed_discs
        and isinstance(plan, PlannedMovie)
        and plan.runtime_seconds > 0
    ):
        best_folder: str | None = None
        best_delta = 999999
        for sd in scanned:
            if sd.folder_name in mapping:
                continue
            if not sd.files:
                continue
            longest = max(sd.files, key=lambda f: f.duration_seconds)
            delta = abs(longest.duration_seconds - plan.runtime_seconds)
            if delta < best_delta and delta <= 300:  # within 5 minutes
                best_delta = delta
                best_folder = sd.folder_name
        if best_folder is not None:
            log.debug("Disc map pass 2: '%s' -> Disc %d (film disc, delta=%ds)",
                      best_folder, film_disc.number, best_delta)
            mapping[best_folder] = film_disc.number
            claimed_discs.add(film_disc.number)

    # Pass 3: bonus/special features folder
    if len(claimed_discs) < len(disc_numbers):
        bonus_discs = sorted(
            [d for d in discs if not d.is_film and d.number not in claimed_discs],
            key=lambda d: len(d.extras),
            reverse=True,
        )
        for sd in scanned:
            if sd.folder_name in mapping:
                continue
            if sd.folder_name.lower() in _BONUS_FOLDER_NAMES and bonus_discs:
                bd = bonus_discs.pop(0)
                log.debug("Disc map pass 3: '%s' -> Disc %d (bonus folder)",
                          sd.folder_name, bd.number)
                mapping[sd.folder_name] = bd.number
                claimed_discs.add(bd.number)

    # Fill unmapped folders with None
    for sd in scanned:
        if sd.folder_name not in mapping:
            log.debug("Disc map: '%s' -> unmapped (global fallback)", sd.folder_name)
            mapping[sd.folder_name] = None

    return mapping


def match_discs(
    scanned: list[ScannedDisc],
    discs: list[PlannedDisc],
    plan: PlannedMovie | PlannedShow | None = None,
) -> OrganizeResult:
    """Match scanned MKV files against planned disc content.

    Uses disc-constrained matching when folder-to-disc mappings can be
    inferred, then falls back to global greedy matching for any
    remaining unmatched files and targets.

    Returns an :class:`OrganizeResult` with matched, unmatched, and missing items.
    """
    targets = collect_disc_targets(discs, plan)
    if not targets:
        log.debug("match_discs: no targets from disc data, falling back to flat matching")
        # No disc data; fall back to flat matching
        all_files = [
            (f.name, f.duration_seconds)
            for d in scanned
            for f in d.files
        ]
        if plan:
            candidates = match_files(all_files, plan)
        else:
            candidates = []
        unmatched = [f for d in scanned for f in d.files]
        return OrganizeResult(matched=candidates, unmatched=unmatched)

    folder_map = map_folders_to_discs(scanned, discs, plan)

    # Build flat file list with disc assignment per file
    all_scanned: list[ScannedFile] = []
    file_disc: list[int | None] = []  # parallel array: disc number per file
    for sd in scanned:
        disc_num = folder_map.get(sd.folder_name)
        for f in sd.files:
            all_scanned.append(f)
            file_disc.append(disc_num)

    log.debug("match_discs: %d targets, %d files", len(targets), len(all_scanned))
    for ti, (label, runtime_s, t_disc) in enumerate(targets):
        log.debug("  Target[%d]: '%s' %ds disc=%s", ti, label, runtime_s, t_disc)

    matched: list[MatchCandidate] = []
    claimed_targets: set[int] = set()
    claimed_files: set[int] = set()

    # Build pairings respecting disc constraints
    pairings: list[tuple[int, int, int]] = []  # (delta, file_idx, target_idx)
    for fi, sf in enumerate(all_scanned):
        if sf.duration_seconds <= 0:
            continue
        f_disc = file_disc[fi]
        for ti, (label, runtime_s, t_disc) in enumerate(targets):
            if runtime_s <= 0:
                continue
            # Constrain: if both file and target have disc assignments,
            # they must match. If either is None, allow the pairing.
            if f_disc is not None and t_disc is not None and f_disc != t_disc:
                continue
            delta = abs(sf.duration_seconds - runtime_s)
            pairings.append((delta, fi, ti))

    pairings.sort()
    log.debug("match_discs: %d candidate pairings", len(pairings))

    for delta, fi, ti in pairings:
        if fi in claimed_files or ti in claimed_targets:
            continue
        if delta > _MAX_MATCH_DELTA:
            log.debug("Stopping greedy claims: delta %ds exceeds max %ds",
                      delta, _MAX_MATCH_DELTA)
            break
        sf = all_scanned[fi]
        label, runtime_s, _t_disc = targets[ti]
        conf = _confidence(delta)
        log.debug("Claim: %s (%ds) -> '%s' (%ds) delta=%ds [%s]",
                  sf.name, sf.duration_seconds, label, runtime_s, delta, conf)
        matched.append(
            MatchCandidate(
                file_name=sf.name,
                file_duration_seconds=sf.duration_seconds,
                matched_label=label,
                matched_runtime_seconds=runtime_s,
                delta_seconds=delta,
                confidence=conf,
            )
        )
        claimed_files.add(fi)
        claimed_targets.add(ti)

    unmatched = [
        all_scanned[i]
        for i in range(len(all_scanned))
        if i not in claimed_files
    ]
    missing = [
        targets[i][0]
        for i in range(len(targets))
        if i not in claimed_targets
    ]

    for sf in unmatched:
        log.debug("Unmatched file: %s (%ds)", sf.name, sf.duration_seconds)
    for m in missing:
        log.debug("Missing target: %s", m)

    return OrganizeResult(matched=matched, unmatched=unmatched, missing=missing)
