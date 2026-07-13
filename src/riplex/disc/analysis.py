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


def _looks_like_main_feature_edition(
    duration_seconds: int,
    is_movie: bool,
    movie_runtime: int | None,
) -> bool:
    """Return True if a title's runtime matches the main feature or a
    plausible extended cut of it.

    The windows here must stay in lockstep with ``classify_title``'s
    MAIN FILM / Theatrical / Extended Cut branches so the two functions
    never disagree about which titles are main-feature variants. Callers
    use this to short-circuit heuristics (like play-all detection) that
    must never fire on the feature itself.
    """
    if not (is_movie and movie_runtime):
        return False
    if abs(duration_seconds - movie_runtime) < 60:
        return True
    extra = duration_seconds - movie_runtime
    return 300 <= extra <= 3600


def detect_bonus_films(disc: "PlannedDisc") -> list["PlannedExtra"]:
    """Return the disc's pointer-linked bonus items in source order.

    dvdcompare hyperlinks a bonus title to another film page when that
    item is actually the main feature of a distinct work — e.g. disc 31
    of a *Complete Series* boxset links each standalone TV-movie sequel
    to its own dvdcompare entry. Those hyperlinks are the only reliable
    signal that a bonus item is a separate work; runtime and
    feature_type heuristics misfire on things like long featurettes and
    Making-Of docs that happen to run 60+ minutes.

    Duplicate pointer_fids are collapsed (a Making-Of platter that
    hyperlinks every featurette to the same movie page produces one
    entry, not N). Play-All parents are excluded.
    """
    results: list[PlannedExtra] = []
    seen: set[int] = set()
    for extra in disc.extras:
        fid = getattr(extra, "pointer_fid", None)
        if fid is None:
            continue
        if extra.title.endswith(": Play All"):
            continue
        if fid in seen:
            continue
        seen.add(fid)
        results.append(extra)
    return results


def reconcile_bonus_films(
    bonus_films: list,
    rippable_titles: list,
    *,
    min_feature_seconds: int = 2400,
) -> list:
    """Trim dvdcompare's linked-film list to what the disc actually holds.

    ``detect_bonus_films`` returns the films dvdcompare *links* to a
    disc, which can over-report: a boxset's movies disc frequently
    hyperlinks sibling works (sequels, spin-offs) whose real home is a
    different disc, so a disc that physically presses a single feature
    can appear to hold three. Reconcile against the live scan by
    counting feature-length rippable titles (``>= min_feature_seconds``)
    and keeping only as many bonus films as there are titles beyond the
    main feature. A single-feature disc therefore returns ``[]`` and the
    caller shows no multi-film alert.

    Pure function — no I/O — so both the GUI selection screen and the
    CLI ``rip`` command share one reconciliation rule.
    """
    feature_count = sum(
        1 for t in rippable_titles
        if getattr(t, "duration_seconds", 0) >= min_feature_seconds
    )
    max_extra_films = max(0, feature_count - 1)
    return bonus_films[:max_extra_films]


def group_release_discs(
    discs: list["PlannedDisc"],
    current_tmdb_match: object | None = None,
    *,
    add_primary_work_slot: bool = False,
    primary_runtime_seconds: int = 0,
) -> list["DiscGroup"]:
    """Split a release's discs into groups that map to distinct organize targets.

    Some multi-disc releases bundle multiple distinct works. The classic
    example is *Psych: The Complete Series*, whose Blu-ray box holds the
    eight-season TV series on discs 1-30 plus three standalone TV-movie
    sequels on disc 31. Ripped as one release everything would land under a
    single TMDb match — this function partitions the release so the caller
    can attach a separate target to each group.

    Split rule: each disc's set of ``PlannedExtra.pointer_fid`` values
    (excluding ``None``) forms a *split key*. Contiguous runs of discs
    sharing the same key form one group. A disc with no pointered extras
    (empty key) is treated as belonging to the primary work; a disc
    whose extras hyperlink to distinct film pages is treated as a
    bonus-films disc and produces one ``FilmSlot`` per distinct fid.
    ``is_film`` is intentionally ignored here — dvdcompare's ``* The
    Film`` marker is inconsistent (a bonus-content platter can be
    ``is_film=True`` on one release and ``False`` on another), whereas
    hyperlinks are curated and mean the item genuinely lives on a
    different film page.

    ``current_tmdb_match`` is the TMDb match the user selected earlier at
    the metadata screen. It's auto-assigned to the first group without
    per-film slots (the group whose title matches whatever the user
    searched for). Groups with per-film slots always autofill from each
    slot's ``dvdcompare_fid`` instead — the user's search can't be
    pre-routed to N distinct linked works.

    ``add_primary_work_slot`` (keyword-only) tells the seating logic
    that ``current_tmdb_match`` is the release's primary work living
    on a pointer disc alongside pointered linked works. Set this when
    the caller has filtered the release down to pointer discs only
    (via :func:`filter_discs_to_picked_movie`) and the user's pick is
    a movie: the seating fallback then prepends a new ``FilmSlot`` for
    the primary work instead of overwriting the first pointered slot.

    ``primary_runtime_seconds`` (keyword-only) supplies the runtime for
    that prepended primary-work slot. ``MetadataSearchResult`` (the
    usual ``current_tmdb_match`` type) carries no runtime, so callers
    pass the movie runtime they already have (``movie_runtime`` in
    app state / ``LookupResult``) to avoid an "unknown runtime" label.
    """
    from riplex.models import DiscGroup, FilmSlot

    if not discs:
        return []

    def _split_key(d: "PlannedDisc") -> frozenset[int]:
        return frozenset(
            fid for fid in (getattr(e, "pointer_fid", None) for e in d.extras)
            if fid is not None
        )

    sorted_discs = sorted(discs, key=lambda d: d.number)
    groups: list[DiscGroup] = []
    current_run: list = []

    def emit_run() -> None:
        if not current_run:
            return
        key = _split_key(current_run[0])
        numbers = [d.number for d in current_run]
        first_n, last_n = numbers[0], numbers[-1]
        range_str = f"Disc {first_n}" if first_n == last_n else f"Discs {first_n}-{last_n}"
        gid = f"disc_{first_n}" if first_n == last_n else f"discs_{first_n}_{last_n}"

        films: list[FilmSlot] = []
        default_title = ""
        label = range_str
        if key:
            # A bonus-films disc: one FilmSlot per distinct linked work.
            # detect_bonus_films dedupes pointer_fids per-disc, but a
            # multi-disc run sharing the same key means the same works
            # appear on every disc — dedupe across the run too.
            bonus_by_fid: dict[int, "PlannedExtra"] = {}
            for d in current_run:
                for extra in detect_bonus_films(d):
                    fid = getattr(extra, "pointer_fid", None)
                    if fid is not None and fid not in bonus_by_fid:
                        bonus_by_fid[fid] = extra
            bonus = list(bonus_by_fid.values())
            n_films = len(bonus)
            if n_films == 1:
                default_title = bonus[0].title
                label = f"{range_str}: {bonus[0].title}"
            elif n_films > 1:
                label = f"{range_str}: {n_films} linked works"
            for extra in bonus:
                films.append(FilmSlot(
                    title=extra.title,
                    runtime_seconds=int(getattr(extra, "runtime_seconds", 0) or 0),
                    dvdcompare_fid=getattr(extra, "pointer_fid", None),
                ))

        groups.append(DiscGroup(
            id=gid,
            label=label,
            disc_numbers=numbers,
            default_search_title=default_title,
            films=films,
        ))

    prev_key: frozenset[int] | None = None
    for d in sorted_discs:
        k = _split_key(d)
        if prev_key is None or k == prev_key:
            current_run.append(d)
        else:
            emit_run()
            current_run = [d]
        prev_key = k
    emit_run()

    if current_tmdb_match is not None and groups:
        # The user's search always refers to the primary work; seat it
        # on the first group without per-film slots. If every group has
        # pointered slots (exotic — a release consisting entirely of
        # sibling linked works), fall back to the first slot of the
        # first group so the match isn't dropped.
        target = next((g for g in groups if not g.films), None)
        if target is not None:
            target.tmdb_match = current_tmdb_match
            target.source = "user"
        elif add_primary_work_slot and groups[0].films:
            # Multi-work release where the picked movie IS the primary
            # work and co-lives on the pointer disc as a non-pointer
            # main feature (Psych: The Complete Series disc 31 shape:
            # "The Film" plus 2 linked TV-movie sequels). Prepend a
            # dedicated slot for the primary work so all N works stay
            # visible and correctly attributed, instead of clobbering
            # the first pointered slot.
            primary = FilmSlot(
                title=getattr(current_tmdb_match, "title", "") or "",
                runtime_seconds=int(
                    primary_runtime_seconds
                    or getattr(current_tmdb_match, "runtime_seconds", 0)
                    or 0
                ),
            )
            primary.tmdb_match = current_tmdb_match
            primary.source = "user"
            groups[0].films.insert(0, primary)
            numbers = groups[0].disc_numbers
            first_n, last_n = numbers[0], numbers[-1]
            range_str = (
                f"Disc {first_n}"
                if first_n == last_n
                else f"Discs {first_n}-{last_n}"
            )
            n_films = len(groups[0].films)
            if n_films == 1:
                groups[0].label = f"{range_str}: {primary.title}"
            else:
                groups[0].label = f"{range_str}: {n_films} works"
        elif groups[0].films:
            groups[0].films[0].tmdb_match = current_tmdb_match
            groups[0].films[0].source = "user"

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


def build_season_labels(
    discs: list["PlannedDisc"],
    *,
    film_title: str | None = None,
) -> dict[int, str]:
    """Assign an intra-season disc index for each disc carrying a season title.

    dvdcompare's placeholder syntax (``DISCS ONE - FOUR: Season 1``)
    resolves into ``PlannedDisc.title == "Season 1"`` on every disc in
    that range. Callers want to display ``Season 1, Disc 2`` in the UI
    so users can cross-reference the physical case, so we walk the
    input in order and number each run of consecutive same-title discs
    from 1.

    Some releases (typically single-season pages that happen to include
    later seasons as pointers, e.g. ``Psych: Season 1`` at fid=66231)
    leave the "own" discs untitled and only label the pointer runs.
    When ``film_title`` is passed and contains a ``Season N`` fragment,
    any leading run of untitled discs is treated as belonging to that
    season. Trailing untitled discs (extras/bonus platter) still map
    to an empty string.

    The returned dict is keyed by ``PlannedDisc.number``; missing
    entries (or empty values) mean "no season info known, render as
    usual".
    """
    labels: dict[int, str] = {d.number: "" for d in discs}

    # Group into consecutive same-title runs.
    runs: list[tuple[str, list[int]]] = []
    for d in discs:
        title = (d.title or "").strip()
        if not runs or runs[-1][0] != title:
            runs.append((title, [d.number]))
        else:
            runs[-1][1].append(d.number)

    # Backfill an untitled *leading* run from the film title when
    # possible. Only the leading run is inferred — trailing untitled
    # discs are usually a bonus disc and shouldn't be labeled.
    if runs and runs[0][0] == "" and film_title:
        implied = _implied_season_label(film_title)
        if implied is not None:
            runs[0] = (implied, runs[0][1])

    for title, disc_numbers in runs:
        if not title:
            continue
        for idx, num in enumerate(disc_numbers, start=1):
            labels[num] = f"{title}, Disc {idx}"

    return labels


_SEASON_IN_TITLE_RE = re.compile(r"\bSeason\s+(\d+)\b", re.IGNORECASE)


def parse_season_number(label: str) -> int | None:
    """Extract the numeric season from a label like ``Season 1, Disc 2``.

    Callers use this to pick the right season's episode list out of a
    TMDb ``ShowDetail`` when passing ``tmdb_episodes`` to
    ``analyze_disc``.
    """
    if not label:
        return None
    m = _SEASON_IN_TITLE_RE.search(label)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def filter_discs_to_season(
    discs: list["PlannedDisc"],
    season_number: int,
    *,
    film_title: str | None = None,
) -> list["PlannedDisc"]:
    """Drop discs that don't belong to *season_number* from *discs*.

    Enforces the "one season at a time" invariant for TV rips: even if
    the user picked a Complete-Series-style boxset release, the rest of
    the rip pipeline only ever sees discs for the picked season. Uses
    the same season-label resolution as
    :func:`collect_tmdb_episodes_for_disc` so a disc's season here
    matches the season used when enriching its episodes.

    If ``build_season_labels`` can't identify *any* disc's season (the
    common single-season release case where the outer film page IS the
    season and no disc has a season title), the input is returned
    unchanged — filtering would incorrectly drop the entire release.

    ``film_title`` mirrors ``build_season_labels``: pass the outer
    dvdcompare film title so a leading run of untitled discs can be
    inferred as belonging to the film-implied season.
    """
    if not discs or season_number is None:
        return list(discs)
    labels = build_season_labels(discs, film_title=film_title)
    seasons_seen = {parse_season_number(labels.get(d.number, "")) for d in discs}
    known_seasons = seasons_seen - {None}
    if not known_seasons:
        # No per-disc season info; nothing to filter against. Assume the
        # entire release IS the picked season (typical single-season page).
        return list(discs)
    return [
        d for d in discs
        if parse_season_number(labels.get(d.number, "")) == season_number
    ]


def filter_discs_to_picked_movie(
    discs: list["PlannedDisc"],
) -> list["PlannedDisc"]:
    """Drop discs that aren't relevant to a picked movie.

    Sibling of :func:`filter_discs_to_season` for the movie flow. In a
    multi-work boxset (e.g. *Psych: The Complete Series* — 30 TV discs
    plus 1 disc of standalone TV-movie sequels), the standalone movies
    live on the pointer-linked disc(s) while the primary-work discs
    hold TV episodes irrelevant to a movie pick. When the release
    contains any pointer discs, we drop the empty-pointer discs so
    the rest of the pipeline only sees the movie disc(s).

    Single-work movie releases have no pointer discs at all; those
    pass through unchanged.
    """
    if not discs:
        return list(discs)

    def _has_pointer(d: "PlannedDisc") -> bool:
        return any(
            getattr(e, "pointer_fid", None) is not None for e in d.extras
        )

    pointer_discs = [d for d in discs if _has_pointer(d)]
    if not pointer_discs:
        return list(discs)
    return pointer_discs


def format_disc_ranges(numbers: list[int]) -> str:
    """Collapse a list of disc numbers into a compact range string.

    ``[1, 2, 3, 4, 9, 10]`` -> ``"1-4, 9-10"``; ``[7]`` -> ``"7"``.
    Used to describe the discs a "one pick at a time" filter hid from
    the disc-overview list so the UI banner can name them without
    listing every number. Input is de-duplicated and sorted.
    """
    unique = sorted(set(numbers))
    if not unique:
        return ""
    parts: list[str] = []
    start = prev = unique[0]
    for n in unique[1:]:
        if n == prev + 1:
            prev = n
            continue
        parts.append(f"{start}" if start == prev else f"{start}-{prev}")
        start = prev = n
    parts.append(f"{start}" if start == prev else f"{start}-{prev}")
    return ", ".join(parts)


def collect_tmdb_episodes_for_disc(
    show_detail,
    dvdcompare_discs: list,
    disc_number: int | None,
    *,
    film_title: str | None = None,
) -> list:
    """Return the TMDb episode list to cross-reference against a disc.

    Prefers the season identified by the disc's own season label
    (parsed from ``build_season_labels``). Falls back to concatenating
    every episode from every season on the show when the label doesn't
    resolve — the enricher only consumes each entry once, so a
    superset is safe. Returns an empty list when no ``ShowDetail`` is
    available.
    """
    if show_detail is None:
        return []
    seasons = getattr(show_detail, "seasons", []) or []
    if not seasons:
        return []
    season_num: int | None = None
    if dvdcompare_discs and disc_number is not None:
        labels = build_season_labels(dvdcompare_discs, film_title=film_title)
        season_num = parse_season_number(labels.get(disc_number, ""))
    if season_num is not None:
        for sm in seasons:
            if getattr(sm, "season_number", None) == season_num:
                return list(sm.episodes)
    return [ep for sm in seasons for ep in sm.episodes]


def _implied_season_label(film_title: str) -> str | None:
    """Return ``"Season N"`` if the film title contains that fragment."""
    m = _SEASON_IN_TITLE_RE.search(film_title)
    if not m:
        return None
    try:
        return f"Season {int(m.group(1))}"
    except ValueError:
        return None


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


# ---- TMDb episode cross-reference ----


def _normalize_episode_title(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace for fuzzy matching."""
    s = re.sub(r"[^\w\s]", " ", s.lower())
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _episode_name_similarity(a: str, b: str) -> float:
    """Return 0..1 similarity between two episode titles.

    dvdcompare titles are sometimes truncated or extended relative to
    TMDb (e.g. "Woman Seeking Dead Husband" vs "Woman Seeking Dead
    Husband: Smokers Okay, No Pets"), so a normalized-substring
    relationship counts as a very strong match. Otherwise falls back to
    ``difflib.SequenceMatcher`` on the normalized form.
    """
    from difflib import SequenceMatcher

    na, nb = _normalize_episode_title(a), _normalize_episode_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        return 0.95
    return SequenceMatcher(None, na, nb).ratio()


def enrich_dvd_entries_with_tmdb(
    dvd_entries: list[tuple[str, int, str]],
    tmdb_episodes: list,
    *,
    similarity_threshold: float = 0.85,
    min_promote_seconds: int = 900,
) -> tuple[list[tuple[str, int, str]], int, int]:
    """Cross-reference dvdcompare features against a TMDb episode list.

    dvdcompare knows *what's on this specific disc* with accurate ripped
    runtimes; TMDb knows *what an episode actually is* with canonical
    S/E numbers and titles. Combining the two lets us:

    * **Promote** a dvdcompare feature that dvdcompare didn't flag as
      "episode" (missing or empty ``feature_type``) into an episode when
      its title fuzzy-matches a TMDb episode. Guarded by
      ``min_promote_seconds`` so short deleted scenes / featurettes with
      the same title as an episode (e.g. Psych S1 D3 has "Shawn vs. the
      Red Phantom" as both a 43-min episode and a 52-second deleted
      scene) don't get mis-promoted.
    * **Enrich** matched episode names with an ``SxxEyy - `` prefix so
      the Select Titles screen shows canonical Plex-style labels and
      downstream organizer can pick up the S/E numbers.
    * **Preserve** all non-matching entries verbatim (extras,
      featurettes, deleted scenes, unlisted bonus content) so nothing
      gets silently dropped.

    Each TMDb episode is used at most once (first-come, best-similarity
    within a single pass), preventing the same episode name from
    landing on two features when their titles happen to be identical.

    Returns ``(enriched_entries, total_episode_runtime, episode_count)``
    with counts reflecting any promotions.
    """
    if not tmdb_episodes or not dvd_entries:
        total = sum(rt for _, rt, et in dvd_entries if et == "episode")
        count = sum(1 for _, _, et in dvd_entries if et == "episode")
        return dvd_entries, total, count

    # Pass 1 — score every promotable dvd_entry against every TMDb
    # episode. Track both the winning entry per TMDb episode (highest
    # similarity, break ties by longest runtime) and whether each entry
    # had a strong match somewhere. The two-pass structure is what
    # lets us detect dvdcompare duplicates independently of listing
    # order: when the same episode is listed twice (once as the real
    # 43-min broadcast and once as a shorter re-edit), both entries
    # score 1.0 against the same TMDb episode; the longer entry wins
    # the SE prefix and the shorter one gets downgraded.
    # tmdb_i -> list of (entry_idx, score, runtime)
    match_candidates: dict[int, list[tuple[int, float, int]]] = {}
    entry_strong_match: set[int] = set()
    for entry_idx, (name, runtime, etype) in enumerate(dvd_entries):
        can_promote = etype == "episode" or runtime >= min_promote_seconds
        if not can_promote:
            continue
        for tmdb_i, ep in enumerate(tmdb_episodes):
            score = _episode_name_similarity(name, getattr(ep, "title", ""))
            if score >= similarity_threshold:
                match_candidates.setdefault(tmdb_i, []).append(
                    (entry_idx, score, runtime),
                )
                entry_strong_match.add(entry_idx)

    # Award each TMDb episode to a single dvd_entry.
    entry_to_tmdb: dict[int, int] = {}
    for tmdb_i, cands in match_candidates.items():
        cands.sort(key=lambda c: (-c[1], -c[2]))
        winner_entry_idx = cands[0][0]
        # First-write wins if an earlier TMDb ep already claimed this
        # entry (extremely rare — would need two TMDb episodes with
        # near-identical titles).
        if winner_entry_idx not in entry_to_tmdb:
            entry_to_tmdb[winner_entry_idx] = tmdb_i

    # Pass 2 — emit enriched entries.
    enriched: list[tuple[str, int, str]] = []
    for entry_idx, (name, runtime, etype) in enumerate(dvd_entries):
        if entry_idx in entry_to_tmdb:
            ep = tmdb_episodes[entry_to_tmdb[entry_idx]]
            se = f"S{ep.season_number:02d}E{ep.episode_number:02d}"
            if re.match(r"^S\d{2}E\d{2}\b", name):
                enriched_name = name
            else:
                enriched_name = f"{se} - {name}"
            enriched.append((enriched_name, runtime, "episode"))
        elif etype == "episode" and entry_idx in entry_strong_match:
            # dvdcompare said "episode" and the name matches a TMDb
            # episode, but a longer entry already claimed that episode.
            # Almost always a bonus re-edit / shortened version — mark
            # it "extra" so the sequential walker won't hand it a
            # spurious SE assignment and the rip guide labels it
            # ``[extra] Title`` instead of an ambiguous bare title.
            enriched.append((name, runtime, "extra"))
        else:
            enriched.append((name, runtime, etype))

    total_episode_runtime = sum(rt for _, rt, et in enriched if et == "episode")
    episode_count = sum(1 for _, _, et in enriched if et == "episode")
    return enriched, total_episode_runtime, episode_count


# ---- title classification ----


def _positional_episode_alignment(
    all_titles: list,
    episodes: list[tuple[int, str, int]],
    tolerance_seconds: int,
) -> dict[int, tuple[str, int, str]] | None:
    """Align episode-length disc titles to dvdcompare episodes *by position*.

    dvdcompare lists a disc's episodes in disc order, and makemkv reports titles
    in disc order too. When the count of episode-length titles equals the count
    of dvdcompare episode entries, position is a far stronger signal than
    runtime: a single wrong dvdcompare runtime (a listing typo) would otherwise
    orphan the title it belongs to and let a same-runtime neighbour steal its
    episode. Aligning 1:1 in order fixes both at once.

    Returns the ``title.index -> (name, runtime, "episode")`` mapping, or
    ``None`` to defer to runtime matching when this can't be applied safely:

    * the count of episode-length titles doesn't equal the episode count
      (ragged disc — a listing has an episode not present, or the disc has an
      extra title), or
    * more than one positional pair is out of tolerance. A *lone* outlier is
      the signature of a single bad runtime (trust position); two or more means
      the identity/order is genuinely uncertain, so runtime matching is safer.

    "Episode-length" is a duration band derived from the known episode runtimes.
    Because the alignment only fires on an exact count match, a mis-included or
    mis-excluded title simply changes the count and defers to the fallback —
    positional assignment never fires on an ambiguous disc.
    """
    ep_runtimes = [rt for _, _, rt in episodes]
    if not ep_runtimes:
        return None
    lo = min(ep_runtimes) * 0.6
    hi = max(ep_runtimes) * 1.5

    candidates = [
        t for t in sorted(all_titles, key=lambda t: t.index)
        if lo <= t.duration_seconds <= hi
    ]
    if len(candidates) != len(episodes):
        return None

    outliers = sum(
        1 for t, (_, _, runtime) in zip(candidates, episodes)
        if abs(t.duration_seconds - runtime) > tolerance_seconds
    )
    if outliers > 1:
        return None

    return {
        t.index: (name, runtime, "episode")
        for t, (_, name, runtime) in zip(candidates, episodes)
    }


def _assign_episodes_sequentially(
    all_titles: list,
    dvd_entries: list[tuple[str, int, str]],
    *,
    tolerance_seconds: int = 60,
) -> dict[int, tuple[str, int, str]]:
    """Match disc titles to dvdcompare episode entries.

    First tries a *positional* 1:1 alignment (see
    :func:`_positional_episode_alignment`) which trusts disc order over
    runtime when the episode-length titles line up exactly with the episode
    list — this survives a single wrong dvdcompare runtime.

    Otherwise falls back to a first-fit walk: disc titles in index order, each
    taking the earliest unconsumed dvdcompare episode within tolerance.

    TV episode runtimes on the same disc are often within a few seconds of
    each other, so pure duration matching can grab the wrong entry and
    even hand the same entry to two disc titles. Walking both lists in
    parallel and preferring the earliest unconsumed dvdcompare entry that
    fits within tolerance yields one-to-one assignments that duration
    alone cannot. This handles two independent problems:

    * near-identical episode runtimes: on discs where every episode is
      within a few seconds of every other, sequential preference picks
      the correct entry instead of whichever happened to be the tightest
      duration match.
    * dvdcompare listing an episode in a different physical order than
      the disc, or listing an episode that isn't on this disc at all:
      first-fit skips past entries whose runtimes are out of tolerance
      and lets a later disc title claim them.

    Returns a mapping of ``title.index`` → ``(name, runtime, "episode")``
    for every title that was assigned an episode. Titles with no
    assignment (play-alls, featurettes, unmatched content, duplicates)
    are left out and handled by the duration-only path in
    ``classify_title`` / ``is_skip_title``.
    """
    episodes = [
        (i, name, runtime)
        for i, (name, runtime, etype) in enumerate(dvd_entries)
        if etype == "episode" and runtime > 0
    ]
    if not episodes or not all_titles:
        return {}

    # Plan A: trust disc order when the episode-length titles line up 1:1.
    positional = _positional_episode_alignment(all_titles, episodes, tolerance_seconds)
    if positional is not None:
        return positional

    consumed: set[int] = set()
    assignments: dict[int, tuple[str, int, str]] = {}
    ordered = sorted(all_titles, key=lambda t: t.index)

    for t in ordered:
        dur = t.duration_seconds
        # Ignore obviously-short titles (menus, intros) so they don't
        # burn a slot they can't possibly fill.
        if dur < 120:
            continue
        for ep_i, name, runtime in episodes:
            if ep_i in consumed:
                continue
            if abs(dur - runtime) <= tolerance_seconds:
                assignments[t.index] = (name, runtime, "episode")
                consumed.add(ep_i)
                break
        # No unconsumed episode within tolerance — leave this title for
        # the downstream matcher (which will typically label it
        # Unmatched content, a play-all, or a duplicate).

    return assignments


def _is_claimed_episode(
    title,
    all_titles: list,
    dvd_entries: list[tuple[str, int, str]],
) -> bool:
    """True when the sequential walk assigns this title to a
    dvdcompare episode entry. Used to suppress disc-internal play-all
    detection for real episodes whose runtime coincidentally matches
    the sum of unrelated extras on the same disc (Psych S3 D3: seven
    disc extras summing to ~2552s vs 2579s episodes)."""
    if not dvd_entries:
        return False
    if not any(etype == "episode" for _, _, etype in dvd_entries):
        return False
    assignments = _assign_episodes_sequentially(all_titles, dvd_entries)
    return title.index in assignments


def _get_effective_match(
    title,
    all_titles: list,
    dvd_entries: list[tuple[str, int, str]],
) -> tuple[str, int, str] | None:
    """Resolve the best dvdcompare match for a disc title, honoring the
    sequential episode walk so no episode is assigned to more than one
    title.

    On TV discs with episode entries, this defers to
    ``_assign_episodes_sequentially`` for episode matches; if this title
    wasn't assigned an episode by the walk, only non-episode entries
    (featurettes, play-alls, extras) are considered so an already-used
    episode entry can't be double-claimed via duration alone.

    On movie discs or when dvd_entries has no episode entries, this
    behaves identically to ``find_duration_match``.
    """
    if not dvd_entries:
        return None
    has_episodes = any(etype == "episode" for _, _, etype in dvd_entries)
    if not has_episodes:
        return find_duration_match(title.duration_seconds, dvd_entries)
    assignments = _assign_episodes_sequentially(all_titles, dvd_entries)
    if title.index in assignments:
        return assignments[title.index]
    non_ep = [
        (n, rt, et) for n, rt, et in dvd_entries if et != "episode"
    ]
    if not non_ep:
        return None
    return find_duration_match(title.duration_seconds, non_ep)


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
    # titles at the same resolution (when no dvdcompare data available).
    # Suppressed for titles the sequential walk already claims as a
    # dvdcompare episode, since a real episode's runtime can
    # coincidentally equal the sum of unrelated extras on the same disc.
    claimed_episode = _is_claimed_episode(title, all_titles, dvd_entries)
    if not claimed_episode:
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

    # Check if this matches a single dvdcompare entry.
    # _get_effective_match routes episode matching through the sequential
    # walk so each dvdcompare episode is assigned to at most one disc
    # title, in dvdcompare order — pure duration matching mis-assigns
    # episodes on TV discs whose runtimes cluster within seconds.
    best_match = _get_effective_match(title, all_titles, dvd_entries)
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
        # Also unmatched when the title is meaningfully longer than the
        # longest known episode: no single-episode entry can explain it,
        # and it slipped past every play-all detector, so labeling it
        # "Episode" would be misleading. Common cause: a partial-season
        # play-all (e.g. episodes 1+2 concatenated, ~85 min) that
        # dvdcompare only lists as "Episodes (with Play All option)"
        # with no per-play-all duration.
        episode_runtimes = [
            rt for _, rt, etype in dvd_entries
            if etype == "episode" and rt > 0
        ]
        if episode_runtimes:
            max_episode = max(episode_runtimes)
            # 1.5x the longest known episode. Loose enough that a
            # slightly-longer episode variant (e.g. an extended finale
            # dvdcompare hasn't listed accurately) still counts as an
            # episode; tight enough that any 2+ episode concatenation
            # gets flagged as unmatched.
            if dur > max_episode * 1.5:
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
        # On a TV disc where every dvdcompare episode entry has already
        # been assigned to another disc title, calling this leftover
        # title "Episode" is misleading — it's almost always a
        # play-all fragment, bonus content, or a menu chapter. Only
        # emit "Episode" when there's an unclaimed episode slot this
        # title could plausibly represent.
        if episode_count > 0 and dvd_entries:
            assignments = _assign_episodes_sequentially(all_titles, dvd_entries)
            if len(assignments) >= episode_count and title.index not in assignments:
                return f"Unmatched content ({res_label}, {format_seconds(dur)})"
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

    # Guard the play-all detectors from matching the movie itself.
    # On movie discs packed with many small extras, the extras' durations
    # can accidentally sum to within tolerance of the main feature and
    # trigger a false-positive skip. Independence Day 4K disc 1: 14 extras
    # summed to 8610s of the 8688s theatrical. Sharing the check with
    # classify_title (via _looks_like_main_feature_edition) ensures the
    # two functions can never disagree about which titles are main-feature
    # variants.
    if not _looks_like_main_feature_edition(dur, is_movie, movie_runtime):
        # Suppress disc-internal play-all detection for real episodes
        # (see ``classify_title``): otherwise a real episode whose
        # runtime happens to equal the sum of unrelated extras gets
        # skipped, hiding actual episode content from the user.
        if not _is_claimed_episode(title, all_titles, dvd_entries or []):
            # Skip disc-internal play-all (same resolution)
            if detect_play_all(title, all_titles):
                return True

            # Skip cross-resolution play-all (e.g. 1080p play-all of 4K episodes)
            if detect_cross_res_play_all(title, all_titles):
                return True

    # Skip unmatched short titles when dvdcompare data is available
    # If we have episode metadata and this title is much shorter than episodes
    # with no dvdcompare match, it's likely junk or an unlisted bonus.
    # Uses _get_effective_match so a title that missed its sequential
    # episode slot doesn't get spuriously matched to an already-consumed
    # episode via duration alone.
    if dvd_entries and episode_count > 0:
        match = _get_effective_match(title, all_titles, dvd_entries)
        if not match:
            avg_episode = total_episode_runtime / episode_count
            if dur < avg_episode * 0.3:
                return True
            # Symmetric: also skip unmatched titles that are longer than
            # any known episode. On TV discs these are almost always
            # partial play-alls (e.g. episodes 1+2 concatenated,
            # ~85 min) — the individual-episode titles cover the same
            # content, and dvdcompare doesn't list this variant, so
            # keeping it selected would rip a duplicate. Falls back to
            # unchecked; the user can re-tick from the Select Titles
            # screen if they actually want the play-all.
            episode_runtimes = [
                rt for _, rt, etype in dvd_entries
                if etype == "episode" and rt > 0
            ]
            if episode_runtimes and dur > max(episode_runtimes) * 1.5:
                return True
            # Mirror ``classify_title``'s all-slots-claimed guard: if
            # every dvdcompare episode slot is already assigned to an
            # earlier disc title, an unmatched title in the middle of
            # the episode-runtime range is a bonus/play-all fragment,
            # not a missing episode. Without this, the two functions
            # disagree — classify_title labels the title "Unmatched
            # content" while is_skip_title leaves it selected.
            assignments = _assign_episodes_sequentially(all_titles, dvd_entries)
            if len(assignments) >= episode_count and title.index not in assignments:
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
    tmdb_episodes: list | None = None,
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
    tmdb_episodes:
        Optional list of ``EpisodeMetadata`` (or duck-typed equivalents
        with ``.title``, ``.season_number``, ``.episode_number``) for
        the season(s) covered by this disc. When provided on a TV
        release, dvdcompare features are cross-referenced against these
        entries so canonical S/E numbers land in the classification
        labels and mis-flagged features (dvdcompare's ``feature_type``
        empty or incorrect) can be promoted to episodes. Movie discs
        ignore this parameter.
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

    # Cross-reference with TMDb episode list for TV releases so
    # canonical S/E numbers appear in labels and features dvdcompare
    # didn't flag as episodes can be promoted based on name matches.
    if tmdb_episodes and not is_movie:
        dvd_entries, total_episode_runtime, episode_count = (
            enrich_dvd_entries_with_tmdb(dvd_entries, tmdb_episodes)
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
