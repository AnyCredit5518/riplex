"""Group-aware organize planner.

Bridges the pass-3 DiscGroup model with the per-plan organizer. A single
release can now split into multiple works (a TV series plus standalone
films on a bonus disc, for instance). Each ``DiscGroup`` — and each
``FilmSlot`` within a film group — carries its own TMDb match and needs
its own :class:`~riplex.organizer.OrganizePlan`. This module resolves
each group's assignment (with UI overrides applied), fans out to
:func:`~riplex.metadata.planner._plan_movie` /
:func:`~riplex.metadata.planner._plan_show` and
:func:`~riplex.organizer.build_organize_plan` per group, then merges the
per-group plans into a single :class:`~riplex.organizer.OrganizePlan`
suitable for preview and execution.

The CLI still uses the single-plan path directly. This module is
consumed by the GUI's organize preview when ``disc_groups`` is present
in state.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from riplex.matcher import collect_disc_targets, match_discs
from riplex.metadata.planner import _plan_movie, _plan_show
from riplex.metadata.provider import MetadataProvider
from riplex.models import (
    DiscGroup,
    FilmSlot,
    PlannedDisc,
    PlannedMovie,
    PlannedShow,
    ScannedDisc,
    ScannedFile,
    SearchRequest,
)
from riplex.normalize import movie_file_name, movie_folder_name
from riplex.organizer import FileMove, OrganizePlan, build_organize_plan

log = logging.getLogger(__name__)

_DISC_NUM_RE = re.compile(r"Disc\s+(\d+)", re.IGNORECASE)

# Runtime tolerance (seconds) when routing a scanned file to a FilmSlot.
# 5 minutes accommodates the usual dvdcompare vs. actual disc runtime
# rounding without letting a wrong film match by accident.
_FILM_MATCH_TOLERANCE_S = 300


@dataclass
class GroupPlan:
    """One group's contribution to the merged organize plan.

    Kept for diagnostics and the organize-done summary. ``planned`` is
    ``None`` for film-slot routing that bypasses the planner entirely
    (the standalone-movie destinations are computed directly from the
    TMDb match). ``skipped_reason`` explains why a group produced no
    plan; empty string when the group ran successfully.
    """

    group_id: str
    label: str
    planned: PlannedMovie | PlannedShow | None = None
    plan: OrganizePlan = field(default_factory=OrganizePlan)
    skipped_reason: str = ""


def apply_group_overrides(
    disc_groups: list[DiscGroup],
    overrides: dict,
) -> None:
    """Layer UI overrides (from ``state['group_tmdb_overrides']``) onto
    the groups. Mirrors the read-side logic in the disc overview screen
    so callers who only have ``state['disc_groups']`` still get the
    latest user picks.

    Override schema::

        {group_id: {"match": Match, "source": "user"|"auto",
                    "films": {film_idx: {"match": Match, "source": ...}}}}
    """
    for g in disc_groups:
        entry = overrides.get(g.id)
        if not entry:
            continue
        if entry.get("match") is not None:
            g.tmdb_match = entry["match"]
            g.source = entry.get("source")
        for idx, film_entry in (entry.get("films") or {}).items():
            if 0 <= idx < len(g.films) and film_entry.get("match") is not None:
                g.films[idx].tmdb_match = film_entry["match"]
                g.films[idx].source = film_entry.get("source")


def _disc_num_from_folder(folder_name: str) -> int | None:
    """Extract ``N`` from ``"Disc N"`` folder names; None if absent."""
    m = _DISC_NUM_RE.search(folder_name)
    return int(m.group(1)) if m else None


def _partition_scanned_by_group(
    scanned: list[ScannedDisc],
    disc_groups: list[DiscGroup],
) -> tuple[dict[str, list[ScannedDisc]], list[ScannedDisc]]:
    """Split scanned discs into per-group buckets by folder disc number.

    Returns ``(by_group_id, orphans)``. Orphans are folders whose disc
    number couldn't be mapped to any group; the caller decides whether
    to route them to a fallback plan or list them as unmatched.
    """
    group_by_disc: dict[int, str] = {}
    for g in disc_groups:
        for n in g.disc_numbers:
            group_by_disc[n] = g.id

    by_group: dict[str, list[ScannedDisc]] = {g.id: [] for g in disc_groups}
    orphans: list[ScannedDisc] = []
    for sd in scanned:
        disc_num = _disc_num_from_folder(sd.folder_name)
        if disc_num is not None and disc_num in group_by_disc:
            by_group[group_by_disc[disc_num]].append(sd)
        else:
            orphans.append(sd)
    return by_group, orphans


def _match_files_to_film_slots(
    scanned: list[ScannedDisc],
    films: list[FilmSlot],
) -> tuple[list[tuple[FilmSlot, ScannedFile, int]], list[ScannedFile]]:
    """Greedily pair each ``FilmSlot`` with the closest-runtime file.

    Returns ``(matches, leftover_files)`` where ``matches`` is a list of
    ``(film_slot, matched_file, delta_seconds)`` for every slot that
    found a file within :data:`_FILM_MATCH_TOLERANCE_S`. Slots without a
    match, and files not claimed by any slot, are excluded from the
    return but the leftovers list captures the unclaimed files so the
    caller can mark them as unmatched.
    """
    all_files: list[ScannedFile] = [f for sd in scanned for f in sd.files]

    # Build all viable (delta, file_idx, slot_idx) pairings, then greedy
    # assign smallest-delta first so exact hits win over near-misses.
    pairings: list[tuple[int, int, int]] = []
    for si, slot in enumerate(films):
        if slot.tmdb_match is None or slot.runtime_seconds <= 0:
            continue
        for fi, f in enumerate(all_files):
            if f.duration_seconds <= 0:
                continue
            delta = abs(f.duration_seconds - slot.runtime_seconds)
            if delta <= _FILM_MATCH_TOLERANCE_S:
                pairings.append((delta, fi, si))
    pairings.sort()

    claimed_files: set[int] = set()
    claimed_slots: set[int] = set()
    matches: list[tuple[FilmSlot, ScannedFile, int]] = []
    for delta, fi, si in pairings:
        if fi in claimed_files or si in claimed_slots:
            continue
        claimed_files.add(fi)
        claimed_slots.add(si)
        matches.append((films[si], all_files[fi], delta))

    leftover = [f for i, f in enumerate(all_files) if i not in claimed_files]
    return matches, leftover


def _build_film_slot_moves(
    matches: list[tuple[FilmSlot, ScannedFile, int]],
    output_root: Path,
) -> list[FileMove]:
    """Turn film-slot matches into Plex-shaped ``FileMove`` entries.

    Each standalone film lands in
    ``<output_root>/Movies/<Title> (<Year>)/<Title> (<Year>).mkv``.
    ``matched_label`` names the slot's title so the preview shows which
    slot claimed which file. Confidence is derived from the runtime
    delta so a near-miss reads as medium.
    """
    moves: list[FileMove] = []
    for slot, sf, delta in matches:
        match = slot.tmdb_match
        title = getattr(match, "title", slot.title)
        year = getattr(match, "year", 0) or 0
        folder = movie_folder_name(title, year)
        fname = movie_file_name(title, year)
        dest = output_root / "Movies" / folder / fname
        if delta <= 30:
            confidence = "high"
        elif delta <= 120:
            confidence = "medium"
        else:
            confidence = "low"
        moves.append(FileMove(
            source=sf.path,
            destination=str(dest),
            label=slot.title,
            confidence=confidence,
            delta_seconds=delta,
        ))
    return moves


def merge_plans(plans: list[OrganizePlan]) -> OrganizePlan:
    """Concatenate per-group plans into a single :class:`OrganizePlan`."""
    merged = OrganizePlan()
    for p in plans:
        merged.moves.extend(p.moves)
        merged.splits.extend(p.splits)
        merged.unmatched.extend(p.unmatched)
        merged.missing.extend(p.missing)
    return merged


async def build_multi_group_plan(
    scanned: list[ScannedDisc],
    dvdcompare_discs: list[PlannedDisc],
    disc_groups: list[DiscGroup],
    provider: MetadataProvider,
    output_root: Path,
    *,
    request_defaults: SearchRequest | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[OrganizePlan, list[GroupPlan]]:
    """Fan out organize planning across every DiscGroup, then merge.

    ``disc_groups`` is expected to already have UI overrides applied
    (call :func:`apply_group_overrides` first if you only have the raw
    output of :func:`~riplex.disc.analysis.group_release_discs`).

    Behavior per group kind:

    * **film with per-film slots** — each slot's assigned MKV is routed
      as a standalone movie into ``Movies/Title (Year)/``. Leftover
      files (short menus, unmatched extras) are listed as unmatched.
      The planner is bypassed here because a single-file movie needs no
      extras skeleton or episode map.
    * **film without slots** — treated like the classic single-movie
      case: run :func:`_plan_movie` on the group's TMDb match and hand
      the group's scanned discs to :func:`build_organize_plan`.
    * **main** — run :func:`_plan_show` or :func:`_plan_movie` depending
      on the match's media type, restricted to the group's discs.

    Groups without an assigned match are skipped with a diagnostic
    ``GroupPlan.skipped_reason``. The caller decides how to surface
    those to the user.
    """
    def _log(msg: str) -> None:
        log.info(msg)
        if progress is not None:
            progress(msg)

    by_group, orphans = _partition_scanned_by_group(scanned, disc_groups)
    dvd_by_disc = {d.number: d for d in dvdcompare_discs}
    group_plans: list[GroupPlan] = []

    for group in disc_groups:
        group_scanned = by_group.get(group.id, [])
        if not group_scanned:
            group_plans.append(GroupPlan(
                group_id=group.id,
                label=group.label,
                skipped_reason="no ripped files for this group",
            ))
            continue

        group_dvd = [dvd_by_disc[n] for n in group.disc_numbers if n in dvd_by_disc]

        # Film group with per-film slots: route each MKV to its slot,
        # build direct Plex movie destinations.
        if group.kind == "film" and group.films and any(
            f.tmdb_match is not None for f in group.films
        ):
            _log(f"Organize: routing '{group.label}' by per-film slots")
            matches, leftover = _match_files_to_film_slots(
                group_scanned, group.films,
            )
            moves = _build_film_slot_moves(matches, output_root)
            missing = [
                f"{slot.title} (slot unmatched)"
                for slot in group.films
                if slot.tmdb_match is not None
                and not any(m[0] is slot for m in matches)
            ]
            plan = OrganizePlan(
                moves=moves,
                unmatched=leftover,
                missing=missing,
            )
            group_plans.append(GroupPlan(
                group_id=group.id,
                label=group.label,
                planned=None,
                plan=plan,
            ))
            continue

        # Any other group needs an assigned tmdb_match to plan against.
        if group.tmdb_match is None:
            group_plans.append(GroupPlan(
                group_id=group.id,
                label=group.label,
                skipped_reason="no TMDb match assigned",
            ))
            continue

        match = group.tmdb_match
        media_type = getattr(match, "media_type", None)
        _log(f"Organize: planning '{group.label}' as {media_type or 'movie'}")

        request = SearchRequest(
            title=getattr(match, "title", ""),
            year=getattr(match, "year", None),
            season_number=(
                request_defaults.season_number if request_defaults else None
            ),
            media_type=media_type or "movie",
        )
        if media_type == "tv":
            planned = await _plan_show(match, provider, request)
        else:
            planned = await _plan_movie(match, provider, request)

        result = match_discs(group_scanned, group_dvd, planned)
        file_map = {f.name: f.path for sd in group_scanned for f in sd.files}
        scanned_map = {f.name: f for sd in group_scanned for f in sd.files}
        targets = collect_disc_targets(group_dvd, planned) if group_dvd else None

        plan = build_organize_plan(
            result, planned, output_root,
            scanned_files_by_name=file_map,
            scanned_files=scanned_map,
            disc_targets=targets,
        )
        group_plans.append(GroupPlan(
            group_id=group.id,
            label=group.label,
            planned=planned,
            plan=plan,
        ))

    # Orphan folders (couldn't be tied to any group by disc number) are
    # listed as unmatched so the user knows something didn't route.
    if orphans:
        orphan_files = [f for sd in orphans for f in sd.files]
        group_plans.append(GroupPlan(
            group_id="_orphans",
            label=f"Unassigned folders ({len(orphans)})",
            plan=OrganizePlan(unmatched=orphan_files),
            skipped_reason="folder disc number didn't match any group",
        ))

    merged = merge_plans([gp.plan for gp in group_plans])
    return merged, group_plans
