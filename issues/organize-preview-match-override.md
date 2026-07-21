# GUI: override a wrong match on the organize preview

## Problem

The organize preview is the last checkpoint before files are moved into Plex
layout, but it is read-only. When the user spots a wrong match there — a title
routed to the wrong episode, an episode dropped into `Other/`, an extra
mislabeled — they have **no recourse**. Their only options are to execute a
plan they know is wrong, or go back and re-rip / re-pick metadata, neither of
which fixes a single bad row.

We hit this with Psych S5: three episodes with parenthetical titles or filed
by dvdcompare under a disc's extras (`Shawn and Gus in Drag (Racing)`,
`Romeo and Juliet and Juliet`, `Dual Spires`) landed in `Other/`. The
underlying misclassification is now fixed (organize honors the rip-time
`SxxEyy` classification from the manifest), and the new duration columns on
the preview make a bad match visible — but "visible" still isn't "fixable."

## Goal

Let the user correct an individual row on the organize preview before
executing, without leaving the screen or re-running the whole flow.

## Proposed UX

Each matched / unmatched / (optionally) split row gets an **Edit** affordance
(pencil icon or click-to-expand). Activating it opens an inline picker for
that one file:

- **Target dropdown** populated from the current plan:
  - Each episode in the resolved `PlannedShow` (`S05E05 - Shawn and Gus in
    Drag (Racket)`), grouped by season.
  - The movie main feature / editions for a `PlannedMovie`.
  - Extras folders: `Featurettes`, `Behind The Scenes`, `Deleted Scenes`,
    `Interviews`, `Trailers`, `Shorts`, `Other`.
  - `Skip (leave unmatched)`.
- The dropdown defaults to the current assignment and shows each option's
  expected runtime next to the file's runtime (reuse the duration formatting
  just added), so the correct episode is easy to pick.
- Confirming rebuilds just that row's destination and re-renders the preview
  (updating the summary counts). No other rows are recomputed.

## Where the logic lives (CLI/GUI parity)

Per `.github/copilot-instructions.md`, the override resolution must be a plain
function in `src/riplex/`, not GUI code. Sketch:

```python
# src/riplex/organizer.py (or a new override.py)
def apply_move_override(
    plan: OrganizePlan,
    source_path: str,
    target: MoveOverride,   # episode (s,e) | movie edition | extras folder | skip
    planned: PlannedMovie | PlannedShow,
    output_root: Path,
) -> OrganizePlan:
    """Return a new OrganizePlan with the one file re-routed per `target`."""
```

The GUI preview becomes a thin caller (`state[...] = apply_move_override(...)`
then re-render); a future CLI `--fix FILE=TARGET` flag could call the same
function. Destination computation should reuse `_compute_destination` / the
episode + extras-folder helpers rather than duplicating path logic.

## Scope / decisions to settle

- **Persistence:** session-only (re-route affects just this execute), or write
  the corrected `SxxEyy` back into the file's `_rip_manifest.json` so a later
  re-organize keeps the fix? Recommend session-only first; manifest write-back
  is a follow-up.
- **Split rows:** overriding a chapter-split move is more complex (N
  destinations). Start with matched + unmatched single-file rows; leave split
  overrides out of v1.
- **Validation:** picking an episode that another row already claims should
  warn (duplicate destination) but not hard-block — the user may be fixing a
  swap and will correct the other row next.
- **Testing:** unit-test `apply_move_override` in `tests/test_organizer.py`
  (episode re-route, extras re-route, skip). Drive the picker end to end in the
  GUI integration harness (`tests/support/`), asserting the summary counts and
  the corrected destination.

## Related

- Fixed: organize honors rip-time `SxxEyy` classification over the dvdcompare
  label (Psych S5 E01/E05/E12 → `Other/`).
- Added: source + target durations on the organize preview (highlights
  mismatches), which pairs naturally with this override picker.
