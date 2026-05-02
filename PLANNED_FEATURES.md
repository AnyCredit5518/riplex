# Planned Features


## Multi-Resolution Support (4K + Standard Blu-ray)

Many 4K boxsets include standard Blu-ray discs with the same content at 1080p.
Some users may want to rip both so Plex can serve the lower-resolution version
to mobile devices without transcoding.

### Plex support status

**Movies**: Fully supported via "Multi-Version Movies." Multiple files in the
same folder with different suffixes are collapsed into one library item. Plex
auto-selects the best version per device, and many apps let the user choose
manually. Naming convention:

```
/Movies/MovieName (Year)/
   MovieName (Year) - 4K.mkv
   MovieName (Year) - 1080p.mkv
```

**TV Shows**: NOT officially supported. Plex's TV naming documentation does not
mention multi-version episodes. There is no documented way to have 4K and 1080p
versions of the same episode collapse into a single item. Community workarounds
exist (separate libraries, or relying on Plex's automatic version detection
which sometimes works for TV but is undocumented and unreliable).

### Plan

- **Movies**: Support ripping both 4K and standard Blu-ray discs. During
  organize, name them with resolution suffixes so Plex collapses them.
- **TV Shows**: Since Plex does not officially support multi-version TV
  episodes, we should:
  1. Warn the user during rip if they attempt to rip a standard Blu-ray disc
     for a TV show that already has 4K rips.
  2. Offer to skip it with an explanation of why.
  3. If Plex adds official TV multi-version support in the future, revisit.
  4. Optionally allow it anyway for users who use separate libraries or
     other workarounds, but make the limitation clear.


## GUI Workflow Expansion (Orchestrate + Organize)

### Problem

The GUI currently only exposes the `rip` workflow (single-disc rip with title
selection). The two most-used CLI workflows — `orchestrate` (full pipeline
with multi-disc support) and `organize` (organize existing MKV rips into Plex
structure) — have no GUI equivalent.

### Goals

1. **Organize mode**: Let users point at a folder of existing MKV rips and
   organize them into Plex-compatible structure, matching the CLI `organize`
   command.
2. **Orchestrate mode**: Full pipeline in the GUI — detect disc, lookup
   metadata, rip, prompt for disc swap, repeat, then organize everything at
   the end. Matches the CLI `orchestrate` command.
3. **Workflow picker**: Replace the current single-flow GUI with a welcome
   screen that lets users choose their workflow.

### Plan

#### Welcome screen redesign

Replace the current welcome screen (which goes straight into rip) with a
workflow picker:

```
What would you like to do?

  [Rip & Organize]     Full pipeline: detect disc, look up metadata,
                        rip, swap discs, organize into Plex.
                        (equivalent to: riplex orchestrate)

  [Organize Rips]      Organize existing MKV rips into Plex-compatible
                        folder structure.
                        (equivalent to: riplex organize)
```

Both flows reuse existing screens where possible (metadata, release,
selection, progress, done).

#### Organize flow

Relatively straightforward — no disc hardware interaction:

1. **Folder picker**: User selects a folder containing MKV rips (Flet
   `FilePicker`).
2. **Scan**: Scan the folder with `scanner.scan_folder()`, show file list
   with durations and sizes.
3. **TMDb lookup**: Reuse the existing metadata screen. Auto-detect title
   from folder name or file metadata via `infer_title_from_scanned()`.
4. **dvdcompare lookup**: Reuse the release screen. Use
   `detect_disc_format()` from scan results.
5. **Preview**: Show the planned Plex folder structure (dry-run output from
   `organizer`). Let user review before executing.
6. **Execute**: Move/rename files. Show progress and results.

Screens to reuse: metadata.py, release.py, done.py
New screens: folder_picker.py, organize_preview.py

#### Orchestrate flow

The complex one — multi-disc loop with disc-swap prompts:

1. **Disc detection**: Reuse disc_detection.py screen.
2. **Metadata**: Reuse metadata.py (TMDb lookup, only on first disc).
3. **Release**: Reuse release.py (dvdcompare lookup, only on first disc).
4. **Title selection**: Reuse selection.py (per-disc title classification).
5. **Rip**: Reuse progress.py (per-disc rip with progress tracking).
6. **Disc swap prompt**: NEW screen — "Insert disc N of M, then click
   Continue" or "All discs ripped, click Organize".
7. **Loop**: Return to step 1 (disc detection) for the next disc.
8. **Organize**: After all discs are ripped, run the organize step
   automatically (reuse organize preview/execute from the organize flow).
9. **Done**: Show final results across all discs.

Key challenges:
- **State management**: Need to track across the loop — which discs have
  been ripped, accumulated rip results, metadata that persists across swaps.
  Consider a session state object passed through screens.
- **Disc number detection**: After each disc swap, auto-detect which disc
  number was inserted using `detect_disc_number()`.
- **Error recovery**: If a disc rip fails partway, allow retry or skip.
- **Cancel mid-flow**: User should be able to stop after any disc and still
  organize what's been ripped so far.

New screens: disc_swap.py, orchestrate_summary.py (multi-disc results)
State: OrchestrateSession dataclass tracking metadata, rip results per disc

#### Rip as a sub-flow

The current standalone rip flow (detect → metadata → release → select →
rip → done) becomes a special case of orchestrate with a single disc.
Consider whether to keep it as a separate option or just make orchestrate
handle single-disc cases gracefully (detect only one disc's worth of content
→ skip swap prompt → go straight to organize/done).

### Implementation order

1. Organize flow first (simpler, no disc hardware, exercises screen reuse)
2. Welcome screen workflow picker
3. Orchestrate session state model
4. Disc swap screen
5. Orchestrate loop (wire existing screens with state passing)
6. Organize-after-rip integration
7. Error recovery and cancel handling


## Bug Report Submission (GUI + Shared Snapshots)

### Problem

The CLI automatically writes two types of snapshot files for debugging:

1. **Rip snapshot** (`_rip_snapshot.json`): Written after `rip`/`orchestrate`.
   Contains disc info, metadata, title classifications, and rip results.
2. **Organize snapshot** (`<folder>.snapshot.json`): Written after `organize`.
   Contains scanned file metadata from ffprobe (durations, streams, etc.).

These are essential for reproducing user-reported issues, but they have
several problems:

- **Inconsistent naming**: `_rip_snapshot.json` vs `Disc 1.snapshot.json`
- **Inconsistent structure**: Rip snapshot is a raw dict with no version;
  organize snapshot has `snapshot_version` and `created` fields.
- **Mixed in with media files**: Users have to dig through MKV files to find
  debug artifacts.
- **No single folder to zip**: When filing a bug, users need to hunt for
  files across multiple locations.
- **GUI doesn't write snapshots at all**.

### Goals

1. **Snapshot consistency**: Both snapshot types use the same naming scheme,
   envelope format, and output location.
2. **Dedicated debug folder**: All debug artifacts go in one place that's
   easy to find and zip up.
3. **Snapshot parity**: GUI writes the same snapshot files as the CLI.
4. **One-click bug reports**: A button in the GUI opens a pre-filled GitHub
   issue in the user's browser and tells them to attach the debug folder.

### Plan

#### Phase 1: Dedicated debug folder (`_riplex/`)

All debug artifacts move into a `_riplex/` subfolder inside the output
directory. The underscore prefix means Plex ignores it.

**Current layout** (files mixed with MKVs):
```
E:\Media\_MakeMKV\Starship Troopers (1997)\
  Disc 1\
    title_t00.mkv
    title_t01.mkv
    _rip_manifest.json
    _rip_snapshot.json
```

**New layout** (clean separation):
```
E:\Media\_MakeMKV\Starship Troopers (1997)\
  Disc 1\
    title_t00.mkv
    title_t01.mkv
  _riplex\
    riplex-rip.snapshot.json
    riplex-scan.snapshot.json      (after organize)
    riplex-rip.manifest.json
    riplex.log                     (copy of the debug log)
    README.txt
```

The `_riplex/` folder sits at the title level (e.g.
`Starship Troopers (1997)\_riplex\`), not per-disc, so multi-disc rips share
one debug folder.

**`README.txt`** contents:
```
This folder contains debug information generated by riplex.
If you're filing a bug report, zip this folder and attach it to your issue:
https://github.com/AnyCredit5518/riplex/issues/new?template=bug_report.yml
```

#### Phase 2: Consistent snapshot format

Both snapshot types use the same envelope with a `type` discriminator:

```json
{
  "snapshot_version": 2,
  "type": "rip",
  "created": "2026-05-01T18:30:00Z",
  "riplex_version": "0.1.1.dev18",
  "platform": "Windows-11-10.0.26100-SP0",
  "data": { ... }
}
```

**Naming convention**: `riplex-<phase>.snapshot.json`
- `riplex-rip.snapshot.json` — disc info, TMDb/dvdcompare metadata, title
  classifications, rip results
- `riplex-scan.snapshot.json` — scanned file metadata from ffprobe (durations,
  streams, chapters, fingerprints)

Both are written via shared functions in `riplex/snapshot.py`:

```python
def save_rip_snapshot(
    debug_dir: Path,
    disc_info: DiscInfo,
    metadata: dict,
    selected_titles: list[int],
    rip_results: list[RipResult],
) -> Path | None:
    """Write riplex-rip.snapshot.json. Returns path or None on failure."""

def save_scan_snapshot(
    debug_dir: Path,
    folder: Path,
    scanned: list[ScannedDisc],
) -> Path | None:
    """Write riplex-scan.snapshot.json. Returns path or None on failure."""

def get_debug_dir(output_dir: Path) -> Path:
    """Return (and create) the _riplex/ debug folder for the given output dir."""

def copy_debug_log(debug_dir: Path) -> Path | None:
    """Copy the current session's riplex.log into the debug folder."""
```

The rip manifest also moves to `_riplex/riplex-rip.manifest.json`.

**Backward compatibility**: The `load()` function in `snapshot.py` already
checks `snapshot_version`. It will continue to load v1 snapshots. The new
v2 format unwraps the `data` key. Loading code checks for the `type` field
to distinguish rip vs scan snapshots.

#### Phase 3: GUI snapshot parity

Call the shared functions from the GUI:
- `save_rip_snapshot()` from `progress.py` or `done.py` after rip completes
- `save_scan_snapshot()` if an organize step is reached
- `copy_debug_log()` at the end of the session

#### Phase 4: Bug report button in GUI

Add a "Report a Bug" button to the `done.py` screen (results summary). When
clicked:

1. **Collect context**:
   - App version (`riplex.__version__` or setuptools-scm version)
   - Platform (`platform.platform()`)
   - Disc name and title count from the session
   - Error message (if the rip failed)

2. **Locate the `_riplex/` debug folder** from the session's output directory.

3. **Build a GitHub issue URL** with pre-filled fields:
   ```
   https://github.com/AnyCredit5518/riplex/issues/new
     ?template=bug_report.yml
     &title=[Bug] <disc name> - <brief description>
     &labels=bug
     &body=<url-encoded template>
   ```

4. **Body template** (short — points to the debug folder):
   ```markdown
   **Environment**
   - riplex version: 0.1.1.dev18
   - Platform: Windows-11-10.0.26100-SP0
   - Frontend: GUI

   **Disc**
   - Name: STARSHIP_TROOPERS_ANNIV_ED
   - Titles: 5

   **What happened?**
   <!-- Describe the issue -->

   **Debug files**
   Please zip and attach the debug folder:
   `E:\Media\_MakeMKV\Starship Troopers (1997)\_riplex\`
   ```

5. **Open in browser**: `webbrowser.open(url)`

6. **Copy debug folder path to clipboard** (via Flet's
   `page.set_clipboard()`) so the user can navigate to it easily.

#### Phase 5: GitHub issue template

Create `.github/ISSUE_TEMPLATE/bug_report.yml` with structured fields:

- Environment (version, platform, frontend)
- Disc info (name, volume label)
- What happened (free text)
- Expected behavior (free text)
- Debug folder zip (file upload area)

#### Optional: CLI equivalent

Add a `riplex report` subcommand that finds the most recent `_riplex/` folder,
builds the URL, copies the path to clipboard, and opens the browser. Lower
priority since CLI users are more likely to file issues manually.

### Cross-platform notes

- `webbrowser.open()` is Python stdlib — works on Windows, macOS, Linux
- `page.set_clipboard()` is Flet's clipboard API — works on all desktop targets
- URL length limit is ~8,000 chars in most browsers; the body template above is
  well under that (~300-500 chars). Full snapshots must be attached as files.
- GitHub issue template YAML (`bug_report.yml`) works with `?template=` param
- `shutil.copy2()` for the log file copy is cross-platform

### Implementation order

1. Add `get_debug_dir()` to `snapshot.py` — creates `_riplex/` and writes
   `README.txt`
2. Add `save_rip_snapshot()` with v2 envelope format
3. Add `save_scan_snapshot()` with v2 envelope format (replaces current
   `save_from_scanned()` for new snapshots)
4. Add `copy_debug_log()` — copies the session log into `_riplex/`
5. Update `load()` to handle both v1 and v2 snapshot formats
6. Replace inline snapshot code in CLI's `_run_rip` with
   `save_rip_snapshot()`, move manifest to `_riplex/`
7. Replace inline snapshot code in CLI's `_organize_*` with
   `save_scan_snapshot()`
8. Call snapshot functions from GUI screens
9. Add bug report button to `done.py`
10. Create `.github/ISSUE_TEMPLATE/bug_report.yml`
11. Tests: verify v2 snapshots write valid JSON, verify v1 snapshots still
    load, verify `get_debug_dir()` creates folder with README, verify URL
    builder output


## Interactive Lookup Command

### Problem

`riplex lookup` currently runs non-interactively: it takes the first TMDb
match and the default dvdcompare release without user confirmation. If the
auto-pick is wrong (e.g., a remake vs the original, or a regional release
with different disc contents), the user gets incorrect rip guidance with no
way to correct it short of re-running with `--year` or `--release` flags.

The `rip` and `orchestrate` commands already have interactive TMDb selection
(via `_pick_best` in planner.py), but `lookup` skips it because it was
designed as a quick preview tool.

### Goals

1. Let users confirm or change the TMDb match during `lookup`.
2. Let users pick a dvdcompare release when multiple exist.
3. Keep the current non-interactive behavior available via `--auto`.

### Plan

- Add interactive TMDb selection to `lookup` (reuse `_pick_best` prompt
  from planner — it already handles the numbered list and default selection).
- Add interactive dvdcompare release selection (reuse
  `fetch_and_select_release` which already prompts when multiple releases
  exist, but `lookup` currently bypasses it by calling `lookup_discs`
  directly with a fixed release index).
- Switch `lookup` from `lookup_discs()` to `fetch_and_select_release()` so
  the user sees scored releases and can pick one.
- `--auto` flag (already exists) skips all prompts and uses best-guess
  defaults, preserving current behavior for scripting.


## Other Ideas

(Add future feature ideas here as they come up.)
