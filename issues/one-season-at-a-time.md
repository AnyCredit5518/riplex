# One Season at a Time (TV Rip Invariant)

## Problem

TV rip sessions today can span multiple seasons when a dvdcompare release
happens to cover a boxset (e.g. "Psych: The Complete Series" S1–S8). This
creates several messy edge cases:

1. **Resume ambiguity.** If the user rips two discs of Season 1 from a
   complete-series release, then later inserts a Season 3 disc from the
   same physical boxset, we can't tell whether they want to resume the
   original multi-season session or start fresh — and they may have
   picked a *different* single-season release the second time around.
2. **Session marker fan-out complexity.** `_riplex_session.json` is
   fanned out into every work-folder of a session, so a boxset session
   writes markers into 8 season folders up front, even for seasons the
   user may never rip.
3. **`find_existing_session` disambiguation.** We added
   `season_number=` filtering to distinguish which season's session to
   resume, but the underlying model still assumes a session can span
   seasons, which forces every caller to remember to pass the filter.
4. **Cross-season disc lookups.** dvdcompare-scraper returns the whole
   release; downstream code has to figure out which discs belong to
   the picked season, and mis-classification leads to the wrong disc
   list on the overview.

## Proposed invariant

**A single rip session covers exactly one season of one TV show.**

- Movies unaffected (single work, no season concept).
- The user picks the season *before* the dvdcompare release, and the
  release-picker filters its disc list down to that season. If a boxset
  release contains S1–S4 and the user picked Season 2, the overview
  shows only the Season 2 discs.
- `SessionWork.season_number` becomes non-optional for TV.
  `_riplex_session.json` always contains exactly one work for TV.
- Resume matching for TV is always keyed on `(title, season_number)`.
  No cross-season fallback.

## What we gain

- **Simpler resume.** `find_existing_session(title, season)` becomes
  the *only* resume path for TV. No cross-season aggregation, no
  order-dependent iterdir behavior.
- **No cross-season disc confusion.** Overview always shows exactly
  the discs the user needs to insert right now.
- **Cleaner session markers.** One work, one folder. No fan-out.
- **Predictable UX.** "One disc set → one rip session" matches the
  physical workflow (users swap discs of one season, then move on).

## What we give up

- **Complete-series boxset users** have to rerun orchestrate once per
  season instead of one long multi-season session. In practice they
  already swap discs between rip runs (a single rip takes an hour), so
  this maps naturally to "finish Season 1, start Season 2 tomorrow".
- **Multi-work releases** (e.g. TV series + bonus-features disc for a
  film) — the bonus disc is no longer part of the TV session. The
  release-picker can surface a one-line hint ("this release also has
  bonus movie discs — rip separately"), but they'd be a separate rip.

## Migration

No data migration needed. Existing multi-work sessions on disk keep
resuming through today's exact-`(title, season)` match. New sessions
written after the change are single-work.

## Open questions

1. How reliable is dvdcompare's per-disc season metadata? For most
   boxsets each disc's contents are clearly labelled ("Season 2 Disc 1"),
   but if a release is ambiguous we fall back to using the picked
   season's dvdcompare page instead of the boxset page (the scraper
   already supports both).
2. Do any release-picker scenarios *need* cross-season discs visible?
   The release list is per-title, not per-season, so all cross-season
   releases stay visible during selection — only the *disc list* inside
   the chosen release is filtered.

## Implementation sketch

1. Season picker runs before release picker (already true).
2. In the release picker's post-selection step, filter
   `dvdcompare_discs` down to the picked season. Use per-disc title
   matching first, fall back to the per-season dvdcompare page if the
   boxset page can't be split.
3. `build_session_work` for TV always sets `season_number` (raise if
   the caller passes `None` for a TV work).
4. `write_session_marker` writes one work-folder for TV; drop the fan-out
   loop for TV sessions.
5. `find_existing_session` keeps its current signature (backward
   compatible), but for TV all internal callers pass `season_number`.
6. Organize flow unchanged — it already iterates each season folder
   under the show root independently.
