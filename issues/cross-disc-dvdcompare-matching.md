# Cross-disc dvdcompare matching produces false positives

## Problem

When classifying makemkvcon titles, `build_dvd_entries()` flattens **all** dvdcompare discs into a single list. The duration matcher then matches titles on the physical disc against entries from *any* disc in the release.

### Example: King Kong (2005) Ultimate Edition

The physical disc is Disc 1 (Blu-ray 4K) with 3 titles:
- Title 0: 3:07:16 — Theatrical Cut
- Title 1: 5:30 — unknown short content
- Title 2: 3:20:08 — Extended Cut

dvdcompare Disc 3 (extras) contains "Production Day 66: Journey of a Roll of Film" with a runtime of 331s. Title 1 (330s) gets matched to it, even though Title 1 is on Disc 1 and the Production Diary is on Disc 3.

## Proposed fix

After the user selects a dvdcompare release, filter `build_dvd_entries()` to only the disc matching the physical disc being ripped.

### Disc matching heuristic

Match by format: the physical disc's detected format (e.g. "Blu-ray 4K" from resolution) should match the dvdcompare disc's `format` field. If multiple discs share the same format, fall back to all-disc matching.

### Changes needed

1. Add a `disc_number: int | None` parameter to `build_dvd_entries()` to filter by disc
2. Detect which dvdcompare disc corresponds to the physical disc (format matching)
3. Thread the disc number through `classify_title` and `select_rippable_titles` call sites
4. Fall back to all-disc matching when format matching is ambiguous

### Impact

- Eliminates false positive matches from extras discs
- Reduces noise in title classification for multi-disc releases
- Particularly important for releases with many short extras (production diaries, deleted scenes)
