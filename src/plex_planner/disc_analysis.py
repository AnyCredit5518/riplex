"""Disc title classification and analysis for makemkvcon output.

Cross-references live disc titles against dvdcompare metadata to produce
rip/skip recommendations.  Used by both ``rip-guide`` and ``rip``.
"""

from __future__ import annotations


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

    # Check if this is the main movie
    if is_movie and movie_runtime:
        if abs(dur - movie_runtime) < 60:
            return f"MAIN FILM ({res_label}) - rip this"

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
            return (
                f"Play-all ({res_label}, {title.chapters} chapters) - "
                f"rip this OR the {len(same_res_individuals)} individual titles"
            )
        return f"Play-all ({res_label}, {title.chapters} chapters) - rip this"

    # Disc-internal play-all detection: check if duration matches sum of other
    # titles at the same resolution (when no dvdcompare data available)
    play_all_match = detect_play_all(title, all_titles)
    if play_all_match:
        parts = play_all_match
        part_indices = ", ".join(f"#{t.index}" for t in parts)
        return (
            f"Play-all ({res_label}, {title.chapters} ch, {title.segment_count} segments) - "
            f"skip (rip {part_indices} individually)"
        )

    # Check if this is a lower-resolution play-all (e.g. 1080p play-all of 4K episodes)
    cross_res_match = detect_cross_res_play_all(title, all_titles)
    if cross_res_match:
        other_res = "4K" if "3840" in cross_res_match[0].resolution else "1080p"
        return f"Play-all ({res_label}) - skip (individual {other_res} titles available)"

    # Check if this matches a single dvdcompare episode
    best_match = find_duration_match(dur, dvd_entries)
    if best_match:
        name, _, entry_type = best_match
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
                return f"{name} ({res_label}) - rip this (skip #{dups[0].index} {dup_res} duplicate)"
            else:
                return f"{name} ({res_label}) - skip (rip #{dups[0].index} {dup_res} instead)"
        return f"{name} ({res_label}) - rip this"

    # Short title, likely menu/intro
    if dur < 120:
        return "Very short - skip"

    # Fall back: individual episode on a multi-title disc
    other_substantial = [
        t for t in all_titles
        if t is not title
        and t.duration_seconds > 120
        and t.resolution == title.resolution
    ]
    if other_substantial:
        return f"Episode ({res_label}) - rip this"

    return f"Unknown content ({res_label}, {format_seconds(dur)}) - rip to be safe"


def is_skip_title(
    title,
    all_titles: list,
    is_movie: bool,
    movie_runtime: int | None,
    total_episode_runtime: int,
    episode_count: int,
) -> bool:
    """Return True if this title should be skipped."""
    dur = title.duration_seconds
    is_4k = "3840" in (title.resolution or "")

    # Always skip very short titles
    if dur < 120:
        return True

    # Skip lower-resolution duplicates when a 4K version exists
    if not is_4k:
        for t in all_titles:
            if t is not title and "3840" in (t.resolution or "") and abs(t.duration_seconds - dur) < 30:
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

    return False


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
                             total_episode_runtime, episode_count)
    ]
    skip_titles = [t for t in titles if t not in rip_titles]

    if rip_titles:
        rip_indices = ", ".join(str(t.index) for t in rip_titles)
        total_size = sum(t.size_bytes for t in rip_titles) / (1024 ** 3)
        print(f"\n  Rip titles: {rip_indices} ({total_size:.1f} GB total)")
    if skip_titles:
        skip_indices = ", ".join(str(t.index) for t in skip_titles)
        print(f"  Skip titles: {skip_indices}")
