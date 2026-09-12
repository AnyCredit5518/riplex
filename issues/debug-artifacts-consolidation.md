# Consolidate riplex debug artifacts

## Status

Partially implemented. MakeMKV summary parsing now prevents failed title saves
from being reported as successful, but manifest status records, snapshot
consolidation, and removal of the duplicate debug writers remain open.

## Problem

riplex currently writes 11 distinct JSON/log artifacts across multiple
locations with overlapping naming. The word "manifest" is overloaded
(production `_rip_manifest.json` vs. debug `riplex-rip.manifest.json`),
two debug writers (`save_rip_manifest`, `save_scan_snapshot`) have no
production readers, and the organize snapshot lives at the title root
instead of in `_riplex/` like the other debug files. The `_riplex/README.txt`
template lists files that may not actually be present.

A related bug: failed rips silently produce a `_rip_manifest.json` with
`"filename": ""` because `run_rip` checks `proc.returncode == 0` to
determine success, but `makemkvcon` returns 0 even on HashCheck failures.
Surfaced by a real failure on Matrix Reloaded Disc 1 (corrupt
`/BDMV/STREAM/00002.m2ts`).

## Affected users

Anyone filing bug reports (confused about which JSON to attach), anyone
inspecting their rip output (unclear what each file is for), anyone
re-running organize on a failed rip (manifest claims success).

## Workaround

None — symptom is cosmetic confusion plus the failed-rip status bug,
which can be diagnosed by reading `_makemkvcon_tNN.log` directly.

## Proposed fix

### Target artifact layout

**Per-disc folder** (production + per-title logs):

- `Disc N/<canonical>_tNN.mkv` — actual rip
- `Disc N/_rip_manifest.json` — production; gains a per-title `status`
  field (`"success"` | `"failed"` | `"cancelled"`) plus `error_message`
  for failures, and top-level `success_count` / `failed_count`
- `Disc N/_makemkvcon_tNN.log` — stays here (per-title, too noisy for
  the title-level debug folder)

**Title-root `_riplex/`** (single home for all debug):

- `riplex-rip.snapshot.json` — rip pipeline state (TMDb match,
  dvdcompare, selected/ripped titles, phase)
- `riplex-organize.snapshot.json` — **renamed and moved** from
  `<Title>.snapshot.json` at title root
- `organized.json` — already lives here, unchanged
- `riplex.log` — CLI session log, unchanged
- `README.txt` — rewritten to match what's actually written

**User-data folder** (`~/.../riplex/`) — unchanged:

- `riplex_app.log` — GUI runtime log
- `crashes/crash-*.txt` — GUI crash dumps

**Removed entirely**:

- `_riplex/riplex-rip.manifest.json` — duplicate of production manifest,
  no readers
- `_riplex/riplex-scan.snapshot.json` — aborted parallel mechanism, no
  production readers (only tests)

### Implementation phases

1. **Manifest status field.** Real success detection in `run_rip` (parse
   `MSG:5004,...,"N titles saved, M failed"` summary line). Update
   `build_rip_manifest` to include all attempted titles with `status` +
   `error_message`. `build_scanned_from_manifests` skips non-success
   entries. `load_manifest` defaults `status` to `"success"` when
   missing for back-compat. Independent of other phases. (Partially
   implemented: `_parse_rip_summary` already added in
   `src/riplex/disc/makemkv.py`.)

2. **Consolidate organize snapshot.** New path
   `_riplex/riplex-organize.snapshot.json`. `snapshot.py::load()` falls
   back to legacy `<Title>.snapshot.json` for old folders (no
   migration). Updates callers in `organize.py` and
   `organize_preview.py`. Independent of phase 1.

3. **Remove dead writers.** Delete `snapshot.py::save_rip_manifest()`
   and `snapshot.py::save_scan_snapshot()` plus their callers. Drop
   corresponding tests. Depends on phase 2.

4. **Docs + README template.** Rewrite `_README_TEXT` in `snapshot.py`
   to match reality. New "Output Artifacts" section in
   `docs/architecture.md` with the full table (production vs debug,
   location, writer, reader, safe-to-delete). Dated entry in
   `docs/changelog.md`. Same commit as phases 2-3 so docs match code.

5. **Patch version bump** per repo convention.

### Decisions locked

- Heavy scope: consolidate file locations + rename + remove dead code +
  docs (not just docs)
- "manifest" reserved for production data; debug duplicate is deleted,
  not renamed
- Both `save_rip_manifest` and `save_scan_snapshot` removed
- `_makemkvcon_tNN.log` stays in per-disc folder (too noisy/per-title to
  belong alongside the higher-level pipeline snapshots)
- Failed rips DO get a `_rip_manifest.json` entry with `status: "failed"`
- No migration tool for old organize snapshots — `load()` just tries new
  path first, falls back to legacy

### Verification

1. `pytest` — existing tests pass; new tests for status field +
   legacy snapshot fallback
2. Fresh GUI rip → output dirs contain only files in the north-star
   list above
3. Cancel a rip mid-way → manifest has `status: "cancelled"` entry
4. Re-rip Matrix Reloaded Disc 1 (the damaged disc that prompted this)
   → manifest has `status: "failed"` with `error_message` populated
5. Run organize against a folder containing legacy
   `<Title>.snapshot.json` → loads via fallback
6. Open `_riplex/README.txt` in a finished session → matches files
   actually present
7. Visual: title folder structure matches `docs/architecture.md` table
   exactly

### Out of scope

- User-data log locations (`riplex_app.log`, crash dumps)
- Migration tool for old `<Title>.snapshot.json` (just fallback-read)
- v1/v2 snapshot envelope format (already supported by `load`)
- `_makemkvcon_tNN.log` location/format
- GUI changes beyond the manifest status fix already started

## Relevant files

- `src/riplex/manifest.py` — `build_rip_manifest`,
  `build_scanned_from_manifests`, `load_manifest`
- `src/riplex/snapshot.py` — `save_rip_snapshot`, `save_rip_manifest`
  (DELETE), `save_scan_snapshot` (DELETE), `save_from_scanned`, `load`,
  `_README_TEXT`, `get_debug_dir`
- `src/riplex/disc/makemkv.py` — `run_rip`, `_parse_rip_summary`
- `src/riplex_cli/commands/rip.py` — remove `save_rip_manifest` call
- `src/riplex_cli/commands/organize.py` — organize snapshot path
- `src/riplex_app/screens/organize_preview.py` — organize snapshot path
- `src/riplex_app/screens/progress.py` — `_write_manifest`
- `tests/test_snapshot.py`, `tests/test_manifest.py` — fixtures, drop
  deleted-fn tests, add status-field tests
- `docs/architecture.md` — new Output Artifacts section
- `docs/changelog.md` — dated entry
