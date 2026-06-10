# GUI: manual rip and manual organize escape hatches

## Problem

When riplex can't classify a disc — no dvdcompare match, ambiguous TMDb
result, multi-feature compilation, region-coded oddity, etc. — the GUI flow
dead-ends at the title-selection screen. The user has to leave riplex-ui,
launch the MakeMKV GUI to rip the disc directly, and then either keep those
files unorganized or manually rename and move them into Plex layout.

We hit this in practice with a BBC Earth Blu-ray containing two unrelated
features (*Wild Africa* + *Tiny Giants*). The disc isn't on dvdcompare, TMDb
has only a combined "double feature" entry, and riplex's planner assumes one
disc → one TMDb item, so the rip flow couldn't proceed at all.

## Why we don't want to model compilations directly

Compilation discs that contain multiple unrelated films are rare enough that
building first-class support (per-title TMDb matching, per-title disc
metadata, multi-target organize) isn't justified. A generic escape hatch is
cheaper and covers other niche scenarios as a side benefit (foreign releases
without metadata, damaged-disc recovery, special workshop discs, etc.).

## Proposed UX

Two new entry points in the GUI, both intentionally generic:

### 1. "Manual rip" button on the title-selection screen

When riplex can't classify titles confidently (no dvdcompare match **and**
TMDb selection is ambiguous, or user just wants raw control), surface a
"Manual rip" button alongside the existing "Rip selected" button.

Clicking it drops the user into a flat MakeMKV-style title list:

- All titles, sorted by index, with duration / size / chapter count
- Checkbox per title (default: all titles longer than 2 minutes)
- Output folder picker (defaults to `<output_root>/_MakeMKV/<disc_label>/`)
- "Rip" button → calls `makemkvcon mkv all` (or per-title) and shows the
  existing progress UI

No metadata lookup, no organize, no Plex naming. The user lands in the "Done"
screen with a folder of raw MKVs, with a follow-up button: "Organize this
folder now → opens the manual organize screen pre-pointed at that path."

### 2. "Organize existing folder" entry on the welcome screen

A second card on welcome (next to "Rip a disc") titled "Organize existing
files." Picks up an arbitrary folder of MKVs and walks the user through:

1. **Folder picker** → list MKVs with sizes and ffprobe runtimes.
2. **TMDb search** (reuses existing `metadata` screen) → select the canonical
   entry.
3. **File assignment** → for each MKV, drop-down: `Main feature`, `Part 1
   (-pt1)`, `Part 2 (-pt2)`, `Extra → behindthescenes`, `Extra → featurette`,
   `Extra → trailer`, `Skip`. Auto-suggest based on duration.
4. **Plan preview** → show source → destination paths.
5. **Apply** → move + rename into Plex layout, with the existing dry-run
   default and `Execute` toggle.

This is essentially the existing `riplex organize` CLI behavior with a GUI in
front of it. No new business logic — just a thin wrapper that also handles
the "two parts of one TMDb movie" case via the assignment step.

## Why this works for the BBC Earth case

End-to-end flow stays inside riplex-ui:

1. Insert disc → riplex tries to classify, fails to find dvdcompare match.
2. User clicks **Manual rip**, picks the two main titles, hits Rip.
3. Done screen → click **Organize this folder**.
4. TMDb search → "Wild Africa Tiny Giants" → pick `tmdb-1657586`.
5. Assign t00 → pt1, t01 → pt2.
6. Apply → files land in `Movies\Wild Africa - Tiny Giants (2016)\`.

No external tool, no manual `Move-Item`.

## Tradeoffs

- **Pro**: covers any disc riplex can't classify, not just compilations.
- **Pro**: reuses existing rip + organize plumbing; mostly UI work.
- **Con**: more GUI surface (two screens, file-assignment widget).
- **Con**: risk of users defaulting to manual mode and bypassing the smart
  classification we built. Mitigation: gate the manual-rip button behind a
  "we couldn't classify this disc" trigger or an "Advanced" reveal, so it's
  not a peer to the normal "Rip selected" button on every disc.

## Out of scope

- Per-title TMDb matching (full compilation support).
- Multi-target organize where one folder of MKVs maps to N different TMDb
  entries. Manual mode handles this by running the organize wizard once per
  target with file selection.
- Saving manual-mode decisions for repeat use (cache).

## Files likely involved

- `src/riplex_app/screens/selection.py` — add "Manual rip" button + branch.
- `src/riplex_app/screens/manual_rip.py` (new) — flat title list + ripper.
- `src/riplex_app/screens/welcome.py` — add "Organize existing files" card.
- `src/riplex_app/screens/manual_organize.py` (new) — folder picker → TMDb →
  assignment → plan preview → apply.
- `src/riplex/organizer.py` — already has the path-building logic; may need
  a small helper for the assignment data structure.
- `src/riplex_cli/commands/organize.py` — sanity-check the CLI still works
  after any planner refactor.
