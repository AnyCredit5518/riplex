# Refactor: Split orchestrate.py into domain-specific modules

## Problem

`orchestrate.py` is a "junk drawer" of shared business logic named after one specific CLI command. It contains 13 functions spanning 4 unrelated domains: title parsing, disc format detection, dvdcompare release scoring/selection, and file manifest I/O.

The name implies it's specific to the `orchestrate` command, but `rip`, `organize`, `lookup`, and the GUI all import from it. `score_releases` lives in "orchestrate" but is fundamental release-matching logic that belongs with dvdcompare/disc handling.

## Proposed Structure

| New Module | Functions Moved | Domain |
|---|---|---|
| `riplex/title.py` (new) | `strip_year_from_title`, `infer_title_from_scanned`, `parse_volume_label` | Title/label string parsing |
| `riplex/disc_provider.py` (existing) | + `score_releases`, `select_dvdcompare_release`, `fetch_and_select_release`, `detect_disc_format`, `detect_disc_number`, `disc_content_summary` | All dvdcompare interaction + disc intelligence |
| `riplex/manifest.py` (new) | `find_ripped_discs`, `create_rip_folders`, `build_scanned_from_manifests` | Rip output folder/manifest I/O |
| `riplex/detect.py` (existing) | + `infer_media_type` | Auto-detection helpers |

After this, `orchestrate.py` becomes an empty re-export shim (for backward compat), then is deleted.

## Steps

### Phase 1: Move functions into correct homes

1. Create `riplex/title.py` with `strip_year_from_title`, `infer_title_from_scanned`, `parse_volume_label` (+ their regexes)
2. Move `score_releases`, `select_dvdcompare_release`, `fetch_and_select_release`, `detect_disc_format`, `detect_disc_number`, `disc_content_summary` into `riplex/disc_provider.py`
3. Create `riplex/manifest.py` with `find_ripped_discs`, `create_rip_folders`, `build_scanned_from_manifests`
4. Move `infer_media_type` into `riplex/detect.py`
5. Convert `orchestrate.py` into a re-export shim (all functions re-exported from new locations)

### Phase 2: Update callers

6. Update `riplex_cli/main.py` imports to use new module paths
7. Update `riplex_app/screens/release.py` and `disc_detection.py` imports
8. Update `riplex/cli.py` backward-compat shim
9. Update any tests that import from orchestrate

### Phase 3: Remove shim

10. Delete `orchestrate.py` (or keep as deprecated re-export)

## Verification

1. `py -m pytest` passes after each phase — all 452+ tests must pass
2. `riplex rip` dry-run works
3. `riplex-ui` launches and shows correct release recommendation

## Decisions

- `disc_provider.py` is the natural home for scoring — it already owns the dvdcompare interface, fetching, and release conversion
- `detect_disc_format` goes with disc_provider (not detect.py) because it produces dvdcompare-format strings, not general file detection
- `infer_media_type` goes with detect.py since it's general media type inference from disc structure, not dvdcompare-specific
- `select_dvdcompare_release` (which calls `prompt_choice`) stays in disc_provider — gated behind `is_interactive()`, splitting it out would be over-engineering
- The `_TRAILING_YEAR_RE` and `_TRAILING_DISC_RE` regexes move with `title.py` (they only serve those functions)

## Files Affected

- `src/riplex/orchestrate.py` — split up / deleted
- `src/riplex/disc_provider.py` — gains scoring + selection + format detection
- `src/riplex/detect.py` — gains `infer_media_type`
- `src/riplex/title.py` — new, title/label parsing
- `src/riplex/manifest.py` — new, rip folder/manifest I/O
- `src/riplex_cli/main.py` — update imports (11 functions)
- `src/riplex_app/screens/release.py` — update imports
- `src/riplex_app/screens/disc_detection.py` — update imports
- `src/riplex/cli.py` — update re-export shim
