# Orchestrate: dvdcompare fallback for missing discs

## Problem

When `riplex orchestrate` can't find a disc on dvdcompare, it exits with a
fatal error instead of falling back to duration-based title selection. The
`rip` command handles this correctly (warns and continues), but `orchestrate`
does `return 1`.

## Affected users

Anyone using `orchestrate` with a disc that isn't listed on dvdcompare (niche
releases, old DVDs, foreign titles, etc).

## Workaround

Use `riplex rip` instead of `orchestrate` for single-disc titles not on
dvdcompare. It warns about the missing dvdcompare data and falls back to
selecting the main feature by TMDb runtime matching.

## Proposed fix

Change `orchestrate.py` to warn instead of error when dvdcompare fails, then:

1. Skip the multi-disc loop entirely (no disc data to iterate)
2. Fall through to a single-disc rip using the same heuristics as `rip.py`:
   - `build_dvd_entries([])` returns empty entries
   - `select_rippable_titles()` uses TMDb runtime to pick the main feature
3. After ripping, proceed to the organize step normally

### Complications

The downstream code in orchestrate's disc loop (`disc_order`, disc swap
prompts, `detect_disc_number`, `_print_disc_overview`) all assume `discs` is
populated. A full fix needs to either:

- Create a synthetic single-disc `PlannedDisc` entry when dvdcompare fails
- Or branch early into a simplified single-disc rip path (essentially
  delegating to `rip`-like behavior) before hitting the disc loop

### Files involved

- `src/riplex_cli/commands/orchestrate.py` (lines ~249-258): the error/return
- Downstream: disc loop starting at ~line 285, `_print_disc_overview`,
  `detect_disc_number`, disc swap prompts
