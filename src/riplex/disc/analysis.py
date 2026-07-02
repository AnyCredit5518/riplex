"""Disc title classification and analysis for makemkvcon output.

Cross-references live disc titles against dvdcompare metadata to produce
rip/skip recommendations.  Used by both ``rip-guide`` and ``rip``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from riplex.models import PlannedDisc, PlannedExtra
    from riplex.models import DiscGroup


# Edition patterns in dvdcompare feature titles
_EDITION_RE = re.compile(
    r"(?:The Film\s*-\s*)?"
    r"((?:Extended|Director'?s|Unrated|Ultimate|Special|Theatrical)\s+(?:Cut|Edition|Version))",
    re.IGNORECASE,
)
_FORMAT_EDITION_RE = re.compile(r"\b(3D|2D|IMAX|Open Matte)\b", re.IGNORECASE)

# Feature types that indicate featurette/bonus content (not episodes)
_FEATURETTE_PLAY_ALL_TYPES = frozenset({
    "featurette", "featurettes",
    "behind the scenes", "behind-the-scenes",
    "documentary", "interview", "interviews",
    "deleted scene", "deleted scenes",
})


def _is_featurette_play_all(entry_type: str) -> bool:
    """Return True if the entry type indicates a featurette collection."""
    return entry_type.lower().strip() in _FEATURETTE_PLAY_ALL_TYPES


# Feature types that clearly denote bonus content (not standalone films).
# Used by ``detect_bonus_films`` to reject long featurettes and documentaries.
_BONUS_CONTENT_FEATURE_TYPES = frozenset({
    "featurette", "featurettes",
    "documentary", "documentaries",
    "interview", "interviews",
    "behind the scenes", "behind-the-scenes",
    "deleted scene", "deleted scenes",
    "short film", "short",
    "trailer", "trailers", "teaser", "teasers",
    "music video", "music videos",
    "commentary", "audio commentary",
    "gag reel", "outtakes", "bloopers",
})

# Minimum runtime for a feature to be considered a standalone film.
BONUS_FILM_MIN_RUNTIME_SECONDS = 60 * 60  # 60 minutes


def detect_bonus_films(
    disc: "PlannedDisc",
    *,
    min_runtime_seconds: int = BONUS_FILM_MIN_RUNTIME_SECONDS,
) -> list["PlannedExtra"]:
    """Return film-length top-level features on a film disc.

    Recognises the case where one physical disc holds multiple full-length
    films (e.g. box sets like *Psych* disc 31 with three TV-movie sequels,
    or a Criterion double-feature). Only considers discs flagged
    ``is_film=True`` by dvdcompare — episode discs are ignored to avoid
    false positives on TV compilations.

    A ``PlannedExtra`` qualifies when:

    * The parent disc's ``is_film`` is True.
    * ``runtime_seconds`` is at least ``min_runtime_seconds`` (default 60m).
    * ``feature_type`` is not a bonus-content category (featurette,
      documentary, interview, deleted scene, etc.). An empty
      ``feature_type`` — the common shape for a standalone top-level
      film — passes.
    * The title is not a Play-All parent (suffix ``": Play All"``).

    Returns an empty list when no additional films are present. On a
    typical single-film disc dvdcompare does not list the main film as
    a feature at all, so this correctly returns ``[]``.
    """
    if not disc.is_film:
        return []
    results: list[PlannedExtra] = []
    for extra in disc.extras:
        if extra.runtime_seconds < min_runtime_seconds:
            continue
        if extra.title.endswith(": Play All"):
            continue
        ft = (extra.feature_type or "").strip().lower()
        if ft in _BONUS_CONTENT_FEATURE_TYPES:
            continue
        results.append(extra)
    return results


def group_release_discs(
    discs: list["PlannedDisc"],
    current_tmdb_match: object | None = None,
) -> list["DiscGroup"]:
    """Split a release's discs into groups that map to distinct organize targets.

    Some multi-disc releases bundle multiple distinct works. The classic
    example is *Psych: The Complete Series*, whose Blu-ray box holds the
    eight-season TV series on discs 1-30 plus three standalone TV-movie
    sequels on disc 31. Ripped as one release everything would land under a
    single TMDb match — this function partitions the release so the caller
    can attach a separate target to each group.

    v1 rule: contiguous runs of discs sharing the same ``is_film`` value form
    one group. Non-film discs become a "main content" group (typically the
    TV series or a movie split across format discs); film discs become a
    "feature films" group.

    ``current_tmdb_match`` is the TMDb match the user selected earlier at
    the metadata screen. It is auto-assigned to the group whose ``kind``
    matches its ``media_type`` (movie → film group; tv → main group). Other
    groups are returned with ``tmdb_match=None`` so the UI can prompt the
    user to pick a target for them. When only one group exists the match is
    always assigned to it regardless of media type.
    """
    from riplex.models import DiscGroup, FilmSlot

    if not discs:
        return []

    sorted_discs = sorted(discs, key=lambda d: d.number)
    groups: list[DiscGroup] = []
    current_run: list = []

    def emit_run() -> None:
        if not current_run:
            return
        is_film = current_run[0].is_film
        numbers = [d.number for d in current_run]
        first_n, last_n = numbers[0], numbers[-1]
        range_str = f"disc {first_n}" if first_n == last_n else f"discs {first_n}-{last_n}"

        films: list[FilmSlot] = []
        if is_film:
            if len(numbers) == 1:
                bonus = detect_bonus_films(current_run[0])
                n_films = max(1, len(bonus))
                if n_films > 1:
                    label = f"{n_films} feature films ({range_str})"
                else:
                    label = f"Feature film ({range_str})"
                default_title = bonus[0].title if len(bonus) == 1 else ""
                # Each detected bonus film becomes its own FilmSlot so the UI
                # can assign a distinct TMDb match per film.
                for f in bonus:
                    films.append(FilmSlot(
                        title=f.title,
                        runtime_seconds=int(getattr(f, "runtime_seconds", 0) or 0),
                    ))
            else:
                label = f"Feature film discs ({range_str})"
                default_title = ""
            gid = f"film_{first_n}"
            kind = "film"
        else:
            label = f"Main content ({range_str})"
            default_title = ""
            gid = f"main_{first_n}"
            kind = "main"

        groups.append(DiscGroup(
            id=gid,
            label=label,
            disc_numbers=numbers,
            kind=kind,
            default_search_title=default_title,
            films=films,
        ))

    prev_is_film: bool | None = None
    for d in sorted_discs:
        if prev_is_film is None or d.is_film == prev_is_film:
            current_run.append(d)
        else:
            emit_run()
            current_run = [d]
        prev_is_film = d.is_film
    emit_run()

    if current_tmdb_match is not None and groups:
        want_kind = "film" if getattr(current_tmdb_match, "media_type", None) == "movie" else "main"
        target = next((g for g in groups if g.kind == want_kind), groups[0])
        # For a film group we park the pre-picked match on the first film
        # slot (or the whole group if there are no per-film slots yet). For
        # a main group the match goes on the group itself.
        if target.kind == "film" and target.films:
            target.films[0].tmdb_match = current_tmdb_match
            target.films[0].source = "user"
        else:
            target.tmdb_match = current_tmdb_match
            target.source = "user"

    return groups


def group_for_disc(
    disc_groups: list["DiscGroup"],
    disc_number: int | None,
) -> "DiscGroup | None":
    """Return the DiscGroup that owns ``disc_number``, or None if the
    disc isn't in any group (or ``disc_number`` is None)."""
    if disc_number is None:
        return None
    for g in disc_groups:
        if disc_number in g.disc_numbers:
            return g
    return None


def build_season_labels(discs: list["PlannedDisc"]) -> dict[int, str]:
    """Assign an intra-season disc index for each disc carrying a season title.

    dvdcompare's placeholder syntax (``DISCS ONE - FOUR: Season 1``)
    resolves into ``PlannedDisc.title == "Season 1"`` on every disc in
    that range. Callers want to display ``Season 1, Disc 2`` in the UI
    so users can cross-reference the physical case, so we walk the
    input in order and number each run of consecutive same-title discs
    from 1. Discs without a title map to an empty string.

    The returned dict is keyed by ``PlannedDisc.number``; missing entries
    (or empty values) mean "no season info known, render as usual".
    """
    labels: dict[int, str] = {}
    current_title: str = ""
    index_in_run = 0
    for d in discs:
        title = (d.title or "").strip()
        if not title:
            labels[d.number] = ""
            current_title = ""
            index_in_run = 0
            continue
        if title != current_title:
            current_title = title
            index_in_run = 1
        else:
            index_in_run += 1
        labels[d.number] = f"{title}, Disc {index_in_run}"
    return labels


def _detect_edition_name(
    duration: int,
    dvd_entries: list[tuple[str, int, str]],
    *,
    edition_hint: str | None = None,
) -> str | None:
    """Try to identify an edition name from dvdcompare entries.

    Looks for entries whose title contains an edition keyword (Extended Cut,
    Director's Cut, etc.) and whose runtime is either zero (unknown) or
    close to the given duration.

    *edition_hint* can be ``"theatrical"`` or ``"extended"`` to prefer
    a specific type when multiple editions exist.
    """
    candidates: list[str] = []
    for name, runtime, _ in dvd_entries:
        m = _EDITION_RE.search(name)
        if not m:
            continue
        # If the entry has a runtime, it must be close
        if runtime > 0 and abs(duration - runtime) > 120:
            continue
        candidates.append(m.group(1))

    if not candidates:
        return None

    if edition_hint == "theatrical":
        for c in candidates:
            if "theatrical" in c.lower():
                return c
    elif edition_hint == "extended":
        for c in candidates:
            cl = c.lower()
            if "extended" in cl or "director" in cl or "unrated" in cl:
                return c

    return candidates[0]


def _extract_movie_edition(text: str) -> str | None:
    """Extract a movie edition label from dvdcompare film-entry text."""
    m = _EDITION_RE.search(text)
    if m:
        return m.group(1)
    m = _FORMAT_EDITION_RE.search(text)
    if not m:
        return None
    value = m.group(1)
    if value.lower() == "open matte":
        return "Open Matte"
    return value.upper()


def _apply_movie_variant_classifications(
    classifications: dict[int, str],
    titles: list,
    current_disc_entries: list,
    movie_runtime: int | None,
) -> None:
    """Label same-runtime movie variants such as 3D/2D using dvdcompare hints."""
    if not movie_runtime:
        return

    film_entries = []
    for disc in current_disc_entries:
        if not getattr(disc, "is_film", False):
            continue
        for extra in getattr(disc, "extras", []):
            title = getattr(extra, "title", "")
            if not title.lower().startswith("the film"):
                continue
            edition = _extract_movie_edition(title)
            if edition:
                film_entries.append((edition, getattr(extra, "runtime_seconds", 0) or 0))

    if len(film_entries) < 2:
        return

    candidate_titles = [
        title for title in titles
        if abs(title.duration_seconds - movie_runtime) < 60
        and classifications.get(title.index, "").startswith("MAIN FILM")
    ]
    if len(candidate_titles) < 2:
        return

    edition_names = [edition for edition, _ in film_entries]
    has_3d_2d = "3D" in edition_names and "2D" in edition_names
    if has_3d_2d:
        sorted_entries = sorted(film_entries, key=lambda entry: 0 if entry[0] == "3D" else 1)
        sorted_titles = sorted(candidate_titles, key=lambda title: title.size_bytes, reverse=True)
    else:
        sorted_entries = sorted(
            film_entries,
            key=lambda entry: 0 if "theatrical" in entry[0].lower() else 1,
        )
        sorted_titles = sorted(candidate_titles, key=lambda title: title.duration_seconds)

    for title, (edition, _) in zip(sorted_titles, sorted_entries):
        res_label = "4K" if "3840" in (title.resolution or "") else "1080p"
        classifications[title.index] = f"{edition} Edition ({res_label})"


def format_seconds(seconds: int) -> str:
    """Format seconds as MM:SS or H:MM:SS."""
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ---- dvdcompare entry helpers ----

def build_dvd_entries(
    dvdcompare_discs: list,
) -> tuple[list[tuple[str, int, str]], int, int]:
    """Build a flat list of dvdcompare entries and compute episode totals.

    Returns (dvd_entries, total_episode_runtime, episode_count) where each
    entry in dvd_entries is (name, runtime_seconds, type_label).
    """
    dvd_entries: list[tuple[str, int, str]] = []
    total_episode_runtime = 0
    episode_count = 0
    for disc in dvdcompare_discs:
        for ep in disc.episodes:
            dvd_entries.append((ep.title, ep.runtime_seconds, "episode"))
            total_episode_runtime += ep.runtime_seconds
            episode_count += 1
        for ex in disc.extras:
            dvd_entries.append((
                ex.title, ex.runtime_seconds, ex.feature_type or "extra",
            ))
    return dvd_entries, total_episode_runtime, episode_count


# ---- title classification ----

def classify_title(
    title,
    all_titles: list,
    dvd_entries: list[tuple[str, int, str]],
    is_movie: bool,
    movie_runtime: int | None,
    total_episode_runtime: int,
    episode_count: int,
) -> str:
    """Return a human-readable recommendation for a makemkvcon title."""
    dur = title.duration_seconds
    is_4k = "3840" in (title.resolution or "")
    res_label = "4K" if is_4k else "1080p"

    # Check for same-resolution duplicate (earlier title with identical duration/size)
    for t in all_titles:
        if t is title:
            break  # only look at titles before this one
        if (
            t.resolution == title.resolution
            and abs(t.duration_seconds - dur) < 5
            and t.size_bytes == title.size_bytes
        ):
            return f"Duplicate of #{t.index} ({res_label})"

    # Check if this is the main movie
    if is_movie and movie_runtime:
        if abs(dur - movie_runtime) < 60:
            # Check if dvdcompare has a specific edition name (e.g. "Theatrical Cut")
            edition = _detect_edition_name(dur, dvd_entries, edition_hint="theatrical")
            if edition:
                return f"{edition} ({res_label})"
            return f"MAIN FILM ({res_label})"

    # Check if this matches a dvdcompare "Play All" entry (before extended cut check)
    if dvd_entries:
        play_all_match = find_duration_match(dur, dvd_entries)
        if play_all_match and "play all" in play_all_match[0].lower():
            pa_name, _, pa_type = play_all_match
            colon_idx = pa_name.lower().find(": play all")
            section = pa_name[:colon_idx] if colon_idx > 0 else pa_name
            return f"{section}: Play All ({res_label})"

    # Check for extended/director's cut: significantly longer than theatrical
    # but within a plausible range (5-60 min longer)
    if is_movie and movie_runtime:
        extra_duration = dur - movie_runtime
        if 300 <= extra_duration <= 3600:
            # Try to get a specific name from dvdcompare entries
            edition_name = _detect_edition_name(dur, dvd_entries, edition_hint="extended")
            if edition_name:
                return f"{edition_name} ({res_label})"
            return f"Extended Cut ({res_label})"

    # Check if this is a play-all (dvdcompare total)
    if total_episode_runtime > 0 and abs(dur - total_episode_runtime) < 120:
        same_res_individuals = [
            t for t in all_titles
            if t is not title
            and t.resolution == title.resolution
            and t.duration_seconds < dur * 0.8
            and t.duration_seconds > 120
        ]
        if same_res_individuals:
            return f"Play-all of {len(same_res_individuals)} titles ({res_label})"
        return f"Play-all ({res_label})"

    # Disc-internal play-all detection: check if duration matches sum of other
    # titles at the same resolution (when no dvdcompare data available)
    play_all_match = detect_play_all(title, all_titles)
    if play_all_match:
        parts = play_all_match
        part_indices = ", ".join(f"#{t.index}" for t in parts)
        return f"Play-all of {part_indices} ({res_label})"

    # Check if this is a lower-resolution play-all (e.g. 1080p play-all of 4K episodes)
    cross_res_match = detect_cross_res_play_all(title, all_titles)
    if cross_res_match:
        other_res = "4K" if "3840" in cross_res_match[0].resolution else "1080p"
        return f"Play-all ({res_label}, individual {other_res} titles available)"

    # Check if this matches a single dvdcompare entry
    best_match = find_duration_match(dur, dvd_entries)
    if best_match:
        name, _, entry_type = best_match
        # Skip if it matches a "Play All" entry from dvdcompare
        if "play all" in name.lower():
            colon_idx = name.lower().find(": play all")
            section = name[:colon_idx] if colon_idx > 0 else name
            return f"{section}: Play All ({res_label})"

        # Determine display label: include feature type for non-episode matches
        is_extra = entry_type not in ("episode", "")
        type_prefix = f"[{entry_type}] " if is_extra else ""

        # Check for a duplicate at different resolution
        dups = [
            t for t in all_titles
            if t is not title
            and abs(t.duration_seconds - dur) < 30
            and t.resolution != title.resolution
        ]
        if dups:
            dup_res = "4K" if "3840" in dups[0].resolution else "1080p"
            if is_4k:
                return f"{type_prefix}{name} ({res_label}, skip #{dups[0].index} {dup_res} duplicate)"
            else:
                return f"{type_prefix}{name} ({res_label}, #{dups[0].index} is {dup_res})"
        return f"{type_prefix}{name} ({res_label})"

    # Short title, likely menu/intro
    if dur < 120:
        return f"Very short ({res_label})"

    # When dvdcompare data exists and no match was found, this is unmatched content
    # Don't call it "Episode" if it's much shorter than known episodes
    if dvd_entries and episode_count > 0:
        avg_episode = total_episode_runtime / episode_count
        if dur < avg_episode * 0.3:
            return f"Unmatched content ({res_label}, {format_seconds(dur)})"

    # Movie disc: any title that isn't the main film or extended cut
    # and doesn't match a dvdcompare entry is unmatched content
    if is_movie and movie_runtime and dur < movie_runtime * 0.5:
        return f"Unmatched content ({res_label}, {format_seconds(dur)})"

    # Fall back: individual episode on a multi-title disc
    other_substantial = [
        t for t in all_titles
        if t is not title
        and t.duration_seconds > 120
        and t.resolution == title.resolution
    ]
    if other_substantial:
        return f"Episode ({res_label})"

    return f"Unknown content ({res_label}, {format_seconds(dur)})"


def is_skip_title(
    title,
    all_titles: list,
    is_movie: bool,
    movie_runtime: int | None,
    total_episode_runtime: int,
    episode_count: int,
    dvd_entries: list[tuple[str, int, str]] | None = None,
) -> bool:
    """Return True if this title should be skipped."""
    dur = title.duration_seconds
    is_4k = "3840" in (title.resolution or "")

    # Always skip very short titles
    if dur < 120:
        return True

    # Skip same-resolution duplicates (earlier title with identical duration/size)
    for t in all_titles:
        if t is title:
            break
        if (
            t.resolution == title.resolution
            and abs(t.duration_seconds - dur) < 5
            and t.size_bytes == title.size_bytes
        ):
            return True

    # Skip lower-resolution duplicates when a 4K version exists
    if not is_4k:
        for t in all_titles:
            if t is not title and "3840" in (t.resolution or "") and abs(t.duration_seconds - dur) < 30:
                return True

    # Skip titles matching a dvdcompare "Play All" entry (but keep featurette play-alls)
    if dvd_entries:
        match = find_duration_match(dur, dvd_entries)
        if match and "play all" in match[0].lower():
            if not _is_featurette_play_all(match[2]):
                return True

    # On 4K discs, skip 1080p titles that match non-episode dvdcompare entries
    # ONLY when a 4K physical title at the same duration also exists on the
    # disc (i.e. the 1080p title is a true duplicate). Some studios (e.g.
    # Universal) ship the 4K main film on a 4K disc but include most extras
    # at 1080p only — in that case the 1080p extras are the *only* copy and
    # must be ripped, not skipped.
    if not is_4k and dvd_entries:
        has_4k = any("3840" in (t.resolution or "") for t in all_titles if t.duration_seconds > 600)
        if has_4k:
            match = find_duration_match(dur, dvd_entries)
            if match and match[2] != "episode":
                has_4k_version = any(
                    "3840" in (t.resolution or "")
                    and abs(t.duration_seconds - dur) < 30
                    for t in all_titles if t is not title
                )
                if has_4k_version:
                    return True

    # Skip dvdcompare-based play-all if individual episodes exist at same resolution
    if total_episode_runtime > 0 and abs(dur - total_episode_runtime) < 120:
        same_res_individuals = [
            t for t in all_titles
            if t is not title
            and t.resolution == title.resolution
            and t.duration_seconds < dur * 0.8
            and t.duration_seconds > 120
        ]
        if len(same_res_individuals) >= episode_count:
            return True

    # Skip disc-internal play-all (same resolution)
    if detect_play_all(title, all_titles):
        return True

    # Skip cross-resolution play-all (e.g. 1080p play-all of 4K episodes)
    if detect_cross_res_play_all(title, all_titles):
        return True

    # Skip unmatched short titles when dvdcompare data is available
    # If we have episode metadata and this title is much shorter than episodes
    # with no dvdcompare match, it's likely junk or an unlisted bonus
    if dvd_entries and episode_count > 0:
        match = find_duration_match(dur, dvd_entries)
        if not match:
            avg_episode = total_episode_runtime / episode_count
            if dur < avg_episode * 0.3:
                return True

    # Movie disc: skip titles that aren't the main film or extended cut
    # and don't match any dvdcompare entry
    if is_movie and movie_runtime and dur < movie_runtime * 0.5:
        match = find_duration_match(dur, dvd_entries) if dvd_entries else None
        if not match:
            return True

    return False


def select_rippable_titles(
    disc_info,
    dvd_entries: list[tuple[str, int, str]],
    is_movie: bool,
    movie_runtime: int | None,
    total_episode_runtime: int,
    episode_count: int,
) -> list:
    """Return the subset of disc titles recommended for ripping.

    Filters out titles that `is_skip_title` marks as skip-worthy.
    """
    return [
        t for t in disc_info.titles
        if not is_skip_title(
            t, disc_info.titles, is_movie, movie_runtime,
            total_episode_runtime, episode_count,
            dvd_entries,
        )
    ]


# ---- play-all detection ----

def detect_play_all(title, all_titles: list) -> list | None:
    """Detect if this title is a play-all of other same-resolution titles.

    Returns the list of individual titles that sum to this one, or None.
    """
    dur = title.duration_seconds
    if dur < 300:  # Ignore very short titles
        return None

    # Find substantial titles at the same resolution (excluding this one)
    same_res = [
        t for t in all_titles
        if t is not title
        and t.resolution == title.resolution
        and t.duration_seconds > 120
        and t.duration_seconds < dur * 0.8  # Must be shorter than this title
    ]
    if len(same_res) < 2:
        return None

    total = sum(t.duration_seconds for t in same_res)
    # Allow up to 30 seconds tolerance per title for segment gaps
    tolerance = max(60, len(same_res) * 15)
    if abs(dur - total) <= tolerance:
        return same_res
    return None


def detect_cross_res_play_all(title, all_titles: list) -> list | None:
    """Detect if this title is a lower-res play-all of higher-res individual titles.

    For example, a 1080p play-all when individual 4K episodes exist.
    """
    dur = title.duration_seconds
    if dur < 300:
        return None

    # Find substantial titles at a different resolution
    diff_res = [
        t for t in all_titles
        if t is not title
        and t.resolution != title.resolution
        and t.duration_seconds > 120
        and t.duration_seconds < dur * 0.8
    ]
    if len(diff_res) < 2:
        return None

    total = sum(t.duration_seconds for t in diff_res)
    tolerance = max(60, len(diff_res) * 15)
    if abs(dur - total) <= tolerance:
        return diff_res
    return None


def find_duration_match(
    duration_seconds: int,
    entries: list[tuple[str, int, str]],
    tolerance: int = 30,
) -> tuple[str, int, str] | None:
    """Find the best dvdcompare entry matching a duration."""
    best = None
    best_diff = tolerance + 1
    for name, runtime, etype in entries:
        if runtime <= 0:
            continue
        diff = abs(duration_seconds - runtime)
        if diff < best_diff:
            best = (name, runtime, etype)
            best_diff = diff
    return best


# ---- high-level analysis ----

def print_disc_analysis(
    disc_info,
    dvdcompare_discs: list,
    is_movie: bool,
    movie_runtime: int | None,
) -> None:
    """Print live disc analysis cross-referencing makemkvcon vs dvdcompare."""
    print(f"\n{'=' * 60}")
    print(f"Live disc analysis: {disc_info.disc_name}")
    print(f"{'=' * 60}")

    titles = disc_info.titles
    if not titles:
        print("  No titles found on disc.")
        return

    dvd_entries, total_episode_runtime, episode_count = build_dvd_entries(
        dvdcompare_discs,
    )

    # Classify and match each makemkvcon title
    print(f"\n  {'#':>3}  {'Duration':>9}  {'Size':>8}  {'Res':>9}  {'Ch':>3}  {'Recommendation'}")
    print(f"  {'':->3}  {'':->9}  {'':->8}  {'':->9}  {'':->3}  {'':->40}")

    for t in titles:
        dur_str = format_seconds(t.duration_seconds)
        size_gb = t.size_bytes / (1024 ** 3)
        size_str = f"{size_gb:.1f} GB"
        res_str = t.resolution or "?"
        ch_str = str(t.chapters)

        recommendation = classify_title(
            t, titles, dvd_entries,
            is_movie, movie_runtime,
            total_episode_runtime, episode_count,
        )

        print(f"  {t.index:>3}  {dur_str:>9}  {size_str:>8}  {res_str:>9}  {ch_str:>3}  {recommendation}")

    # Summary
    rip_titles = [
        t for t in titles
        if not is_skip_title(t, titles, is_movie, movie_runtime,
                             total_episode_runtime, episode_count, dvd_entries)
    ]
    skip_titles = [t for t in titles if t not in rip_titles]

    if rip_titles:
        rip_indices = ", ".join(str(t.index) for t in rip_titles)
        total_size = sum(t.size_bytes for t in rip_titles) / (1024 ** 3)
        print(f"\n  Rip titles: {rip_indices} ({total_size:.1f} GB total)")
    if skip_titles:
        skip_indices = ", ".join(str(t.index) for t in skip_titles)
        print(f"  Skip titles: {skip_indices}")


# ---- shared analysis entry point ----


@dataclass
class DiscAnalysis:
    """Result of analyzing a disc's titles against metadata."""

    disc_number: int | None
    dvd_entries: list[tuple[str, int, str]]
    total_episode_runtime: int
    episode_count: int
    rippable_titles: list
    classifications: dict[int, str] = field(default_factory=dict)


def analyze_disc(
    disc_info,
    dvdcompare_discs: list,
    *,
    disc_number: int | None = None,
    is_movie: bool,
    movie_runtime: int | None = None,
) -> DiscAnalysis:
    """Analyze disc titles and determine rip recommendations.

    This is the single entry point for the "filter entries → build entries →
    classify → select" chain, shared by CLI rip, CLI orchestrate, and the GUI.

    Parameters
    ----------
    disc_info:
        Live disc info from makemkvcon (has .titles, .disc_name).
    dvdcompare_discs:
        All PlannedDisc objects from the dvdcompare release.
    disc_number:
        Which disc this is (1-based).  If provided, entries are filtered to
        that disc only.  If ``None``, auto-detection is attempted via
        ``detect_disc_number()``.  When auto-detection fails and there are
        multiple discs, an **empty** entry list is used (no dvdcompare data),
        falling back to duration heuristics only.
    is_movie:
        Whether this is a movie (vs TV show).
    movie_runtime:
        Movie runtime in seconds (used for main-feature classification).
    """
    from riplex.disc.provider import detect_disc_number

    # Resolve disc number
    if disc_number is None and dvdcompare_discs:
        disc_number = detect_disc_number(disc_info, dvdcompare_discs)

    # Filter to the current disc's entries
    if disc_number is not None:
        current_disc_entries = [d for d in dvdcompare_discs if d.number == disc_number]
    elif len(dvdcompare_discs) <= 1:
        # Single disc release: safe to use all entries
        current_disc_entries = dvdcompare_discs
    else:
        # Multiple discs, detection failed: use NO entries rather than all
        # (using all discs pollutes classification with entries from other discs)
        current_disc_entries = []

    dvd_entries, total_episode_runtime, episode_count = build_dvd_entries(
        current_disc_entries
    )

    # If this disc has no film/episode entries, it's a bonus disc —
    # disable movie_runtime heuristics (main film / extended cut detection)
    effective_movie_runtime = movie_runtime
    if is_movie and episode_count == 0 and dvd_entries:
        # Only disable movie_runtime if no disc in the set is a film disc.
        # Film discs always have episode_count==0 because their features
        # go into extras, but they still need main-film detection.
        has_film_disc = any(d.is_film for d in current_disc_entries)
        if not has_film_disc:
            effective_movie_runtime = None

    # Select rippable titles
    titles = disc_info.titles if disc_info else []
    rippable = select_rippable_titles(
        disc_info, dvd_entries, is_movie, effective_movie_runtime,
        total_episode_runtime, episode_count,
    )

    # Classify each title
    classifications = {}
    for t in titles:
        classifications[t.index] = classify_title(
            t, titles, dvd_entries, is_movie, effective_movie_runtime,
            total_episode_runtime, episode_count,
        )
    if is_movie:
        _apply_movie_variant_classifications(
            classifications, titles, current_disc_entries, effective_movie_runtime,
        )

    return DiscAnalysis(
        disc_number=disc_number,
        dvd_entries=dvd_entries,
        total_episode_runtime=total_episode_runtime,
        episode_count=episode_count,
        rippable_titles=rippable,
        classifications=classifications,
    )
