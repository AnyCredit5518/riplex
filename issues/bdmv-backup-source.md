# BDMV Backup as a Disc Source

## Status

Proposed.

## Problem

Riplex can currently read title information only from an optical drive. Users
who already have a full MakeMKV Blu-ray or UHD backup must put the original
disc back in the drive and rip it again before Riplex can classify, select,
name, and organize its contents.

MakeMKV already supports opening a filesystem backup:

```text
makemkvcon info file:<BDMV folder>
makemkvcon mkv file:<BDMV folder> <title id> <destination folder>
```

Riplex's wrapper does not expose that capability. Its source resolver treats
every string that is not already `disc:` or `dev:` as an optical device.

## Goal

Let the `rip` and `orchestrate` workflows use either:

- a physical optical disc; or
- an existing BDMV backup that MakeMKV can open.

Once MakeMKV has returned `DiscInfo`, both source types must use the same
metadata lookup, disc analysis, title classification, title selection, remux,
manifest, matching, and organize logic.

The BDMV tree is always read-only input. Riplex writes selected titles as MKVs
to its normal rip output and never renames, moves, or deletes files in the
backup.

## Core invariant

```text
Physical drive -----> DiscSource -----> makemkvcon info -----> DiscInfo
BDMV backup --------> DiscSource -----------^

DiscInfo
  -> metadata lookup
  -> title analysis and selection
  -> makemkvcon mkv using the same DiscSource
  -> RipResult
  -> manifest
  -> existing organize pipeline
```

Source-specific behavior ends at source preparation and reappears only for
physical operations such as drive polling and ejection.

## Why this is not direct M2TS organization

A Blu-ray title is defined by playlists, not necessarily by one file under
`BDMV/STREAM`. A playlist may join several M2TS segments, reuse segments,
provide chapters, or represent a seamless-branching cut. Processing individual
M2TS files would discard this structure and could produce incorrect features.

MakeMKV remains responsible for interpreting the BDMV structure and remuxing
selected playlists into MKVs. This does not re-encode the video, but it still
requires reading and writing each selected title. It will usually be faster
than reading the optical disc, but it is not an in-place rename operation.

## Verified feasibility

- The installed MakeMKV CLI advertises `file:<FolderName>` for both `info` and
  `mkv` commands.
- `DiscInfo` and `DiscTitle` contain no physical-drive dependency.
- `analyze_disc`, manifest creation, matching, and organization consume
  `DiscInfo`, `RipResult`, or generated MKVs rather than `DriveInfo`.
- The current blocker is localized in `MakeMKV._resolve_source`, which turns a
  BDMV path into `dev:<path>`.
- The CLI resolves drives before entering the shared downstream flow.
- The GUI carries `DriveInfo` through detection, progress, swap, and ejection;
  those screens need to carry a source instead.

No real BDMV fixture is committed, so exact behavior with decrypted,
encrypted, incomplete, and network-hosted backups still needs a compatibility
spike.

## Proposed source model

Add a shared source abstraction under `src/riplex/`, owned by the library rather
than either frontend. The exact names can change during implementation, but the
responsibilities should remain explicit:

```python
@dataclass(frozen=True)
class DiscSource:
    kind: Literal["drive", "bdmv"]
    locator: int | str | Path = field(repr=False)
    label_hint: str = ""
    eject_device: str | None = field(default=None, repr=False)

    def makemkv_spec(self) -> str: ...

    @property
    def can_eject(self) -> bool: ...


@dataclass(frozen=True)
class OpenedDisc:
    source: DiscSource
    disc_info: DiscInfo
    volume_label: str
```

Shared functions should perform the multi-step work used by both frontends:

- normalize and validate a user-selected BDMV path;
- resolve an optical-drive request into a concrete source;
- open either source with MakeMKV;
- derive a volume-label fallback;
- validate a source against an expected release disc number; and
- format source-aware errors and display labels.

The CLI should prompt and print around these functions. The GUI should render
controls and store their returned dataclasses. Neither frontend should build
`file:` arguments or duplicate BDMV validation.

### BDMV path normalization

Accept all of these user inputs:

- a backup root containing an immediate `BDMV` child;
- the `BDMV` directory itself; or
- `BDMV/index.bdmv`.

Normalize all three to the absolute BDMV directory and pass it to MakeMKV as
one subprocess argument: `file:<absolute BDMV directory>`.

Validation should:

- expand user-relative paths and resolve relative paths;
- handle spaces, Windows drive paths, and UNC paths without shell quoting;
- locate `BDMV` and `index.bdmv` case-insensitively;
- require the `PLAYLIST` and `STREAM` directories;
- reject a collection folder containing several backups instead of guessing;
- reject an output directory inside the selected BDMV tree; and
- let MakeMKV make the final determination about encryption and readability.

Do not recursively search arbitrary descendants. Choosing a directory that
contains `Disc 1/BDMV` and `Disc 2/BDMV` is not the same as choosing one disc.

### Labels

Prefer labels in this order:

1. `DiscInfo.disc_name` reported by MakeMKV;
2. the backup root's directory name; and
3. an explicit title supplied by the user.

Never present `BDMV` or `index.bdmv` as the inferred movie/show title.

### Persistence

Keep source locators in memory only. Do not add an absolute BDMV path to the
rip manifest, session marker, snapshot, cache, or configuration file.

Existing manifests remain valid because they describe the generated MKVs and
their media identity, not the device from which they came. Resume should ask
the user to select the pending backup again rather than retaining a stale or
private filesystem path.

## MakeMKV wrapper changes

Update `MakeMKV.disc_info` and `MakeMKV.rip` to accept `DiscSource`, while
retaining compatibility wrappers for existing integer and device-name callers
during migration.

Commands should differ only by source argument:

```text
# Physical
makemkvcon -r info disc:0
makemkvcon -r --progress=-same mkv disc:0 3 <output>

# Backup
makemkvcon -r info file:<BDMV folder>
makemkvcon -r --progress=-same mkv file:<BDMV folder> 3 <output>
```

While this boundary is being changed:

- consolidate the duplicate `MakeMKV.resolve_drive` definitions and preserve
  advertised device-name support;
- turn nonzero exits, fatal MakeMKV messages, timeouts, and zero-title results
  into consistent source-opening errors; and
- detect the MKV created by the current title operation instead of selecting
  the newest pre-existing MKV in the destination.

The last item is important for resume and multi-backup runs, where the output
folder may already contain successful titles.

## CLI UX

Use an explicit option rather than overloading `--drive`:

```text
riplex rip --backup /path/to/movie/BDMV
riplex orchestrate --backup /path/to/disc-1/BDMV
```

`--backup` and `--drive` are mutually exclusive. Supplying neither preserves
today's `--drive auto` behavior.

### `rip`

`rip` accepts exactly one backup. It opens that source, then follows the
existing single-disc flow without enumerating, polling, or ejecting drives.
Dry-run behavior remains unchanged: scanning and planning are allowed, but no
MKV is written without `--execute`.

### `orchestrate`

Orchestration retains the existing disc queue. The source mode chosen at the
start applies to the whole session:

- drive mode asks the user to insert each queued disc;
- backup mode asks the user to select the BDMV for each queued disc.

For interactive use, one initial `--backup` is enough. When the queue advances,
the CLI prompts for the BDMV path for the expected disc.

For scripted use, allow `--backup` to be repeated:

```text
riplex orchestrate \
  --discs 1,2 \
  --backup /path/to/disc-1/BDMV \
  --backup /path/to/disc-2/BDMV
```

Repeated backups map to the explicit `--discs` order. In `--auto` mode,
multiple backups require `--discs` and the counts must match; Riplex must not
guess disc identity from similar episode runtimes. Interactive mode may warn
when runtime matching suggests a different disc but should let the user
confirm the intended assignment, matching current physical-disc behavior.

No backup-mode path may call drive listing, wait-for-disc, or eject functions.

## GUI UX

Add a source choice before the current detection step, using a segmented
control:

- **Optical disc**: enter the existing drive detection screen.
- **BDMV backup**: show a path field, folder button, and Open command.

The session retains that mode. This keeps the multi-disc interaction
predictable and avoids a mixture of inserted discs and folder assignments in
one queue.

In backup mode:

- the initial picker validates and opens the backup through the shared core;
- Disc Overview shows the same release and content information;
- the disc-swap screen becomes **Select Backup for Disc N**;
- Scan becomes **Open Backup**;
- eject controls and drive polling are absent;
- progress says the selected backup must remain available;
- cancellation returns to the backup picker for the same disc; and
- resume asks for a backup for the next pending disc.

Replace common-flow dependence on `state["drive"]` with
`state["current_source"]`. Keep organize's `state["source_folder"]` separate:
that value refers to generated MKVs that may later be archived, and must never
point at the original BDMV backup.

Auto-eject is conditional on `current_source.can_eject`. Manifest volume labels
come from `OpenedDisc.volume_label`, not directly from `DriveInfo`.

## What remains source-specific

Most downstream behavior is shared, but these differences are intentional:

- drive discovery, polling, and ejection exist only for optical sources;
- folder selection and filesystem validation exist only for backups;
- a backup may not expose the same volume label as the physical disc;
- a backup on removable or network storage may disappear during remux;
- incomplete or encrypted backups may fail before title analysis; and
- multi-disc orchestration must associate each selected folder with a release
  disc instead of waiting for the next inserted disc.

These differences belong around the shared pipeline, not inside title
analysis, matching, or organization.

## Safety requirements

- Never write, rename, move, archive, or delete anything under the BDMV input.
- Always write generated MKVs to Riplex's configured rip output.
- Never pass individual M2TS files into the organize pipeline.
- Never persist an absolute backup path in session artifacts.
- Treat a source disappearing during a rip as a retryable title failure.
- Preserve dry-run as the default for both source modes.
- Preserve all existing physical-disc command behavior.

## Implementation phases

### Phase 0: compatibility spike

1. Run `makemkvcon info file:<BDMV>` against one real MakeMKV backup.
2. Remux one short title into a temporary output folder.
3. Compare the robot output with the same physical disc where available.
4. Repeat with a path containing spaces.
5. Record behavior for an invalid or unavailable backup.

This spike should not modify the source and should not require committing media
or private filesystem paths.

### Phase 1: shared source boundary

1. Add `DiscSource`, `OpenedDisc`, and BDMV normalization in `src/riplex/`.
2. Add shared source preparation and expected-disc assessment functions.
3. Generalize the MakeMKV wrapper to scan and rip either source.
4. Fix output-file association and consolidate drive resolution.
5. Add focused unit tests before changing either frontend.

### Phase 2: CLI single backup

1. Add the mutually exclusive `--backup` option to `rip`.
2. Route drive and backup input through the shared preparation function.
3. Keep all behavior after `DiscInfo` shared.
4. Verify dry-run, execute, cancellation, manifest writing, and organize.

### Phase 3: CLI orchestration

1. Make the source-swap step source-aware.
2. Prompt for each pending BDMV in interactive mode.
3. Support repeated `--backup` with explicit `--discs` for automation.
4. Reuse existing resume and completed-disc detection without storing paths.
5. Prove backup mode never invokes physical-drive operations.

### Phase 4: GUI

1. Add source selection and a reusable native folder chooser.
2. Store `current_source` and `source_mode` in app state.
3. Generalize initial scan, Disc Overview, disc swap, and progress copy.
4. Disable polling and ejection for backups.
5. Add headless movie, TV multi-disc, cancellation, and resume scenarios.

### Phase 5: documentation and release validation

1. Update architecture diagrams to show both source types converging on
   `DiscInfo`.
2. Document `--backup` in the CLI reference and workflow guides.
3. Add GUI walkthrough and troubleshooting guidance.
4. Add the required dated changelog entry for documentation changes.
5. Run the full test suite and manually smoke-test physical and BDMV modes.

## Test plan

### Source and wrapper tests

- backup root, BDMV directory, and `index.bdmv` normalize identically;
- relative paths, spaces, mixed-case names, and Windows UNC paths;
- missing `index.bdmv`, `PLAYLIST`, or `STREAM` gives a useful error;
- collection folders with multiple backups are rejected;
- exact `file:` argument passed as one subprocess argument;
- physical `disc:` and `dev:` behavior remains unchanged;
- source path does not appear in dataclass representations or persisted state;
- current rip result cannot claim a pre-existing MKV; and
- MakeMKV failures produce actionable errors.

### Equivalence tests

Feed identical MakeMKV robot output through drive and BDMV sources and assert
identical:

- `DiscInfo` and `DiscTitle` values;
- analysis classifications and recommended title indices;
- metadata lookup inputs;
- rip-manifest title records; and
- organize plans for the generated MKVs.

Only source display text, volume-label fallback, and physical capabilities may
differ.

### CLI tests

- `--drive` and `--backup` reject each other;
- omitting both retains automatic drive selection;
- single-backup dry-run and execute paths;
- repeated backups map to `--discs` order;
- automated count mismatch fails before ripping;
- interactive mismatch can be confirmed or rejected;
- resume requests only pending backups; and
- no drive listing, wait, or eject call occurs in backup mode.

### GUI tests

- source selection defaults to optical disc;
- selecting a valid backup reaches the existing metadata flow;
- invalid backup remains on the picker with a useful error;
- one-disc movie and multi-disc TV flows reach the same selection results as
  physical fixtures;
- the next-disc screen asks for a folder in backup mode;
- cancel and retry preserve the expected disc number;
- no eject control or call exists in backup mode;
- resume requires re-selection without losing completed-disc state; and
- the original backup tree is unchanged after execute and organize.

### Manual validation

- one decrypted Blu-ray backup;
- one UHD backup;
- one multi-segment or seamless-branching title;
- one backup stored on removable or network storage if available; and
- one physical disc regression run after the source refactor.

## Acceptance criteria

1. CLI and GUI can open a backup root, BDMV directory, or `index.bdmv`.
2. The same MakeMKV title data produces the same analysis and selection for a
   physical disc and a backup.
3. Selected backup titles are remuxed into the normal Riplex output and can
   complete the existing manifest and organize flow.
4. Multi-disc orchestration asks for the expected BDMV at the same point it
   would ask for the next physical disc.
5. Backup mode performs no drive enumeration, polling, or ejection.
6. Riplex never modifies the source backup or treats it as an organize/archive
   folder.
7. Resume works without persisting the backup path.
8. Existing physical-disc CLI, GUI, and integration tests continue to pass.
9. Errors distinguish invalid structure, unavailable source, no titles, and
   MakeMKV refusal clearly enough for the user to act.

## Out of scope

- Creating a BDMV backup from a physical disc.
- Directly organizing or renaming files under `BDMV/STREAM`.
- Parsing MPLS or M2TS without MakeMKV.
- Repairing incomplete or encrypted backups that MakeMKV cannot open.
- Automatically discovering every backup below a collection folder.
- Persisting backup paths for unattended resume.
- ISO input in the first release. The source abstraction should allow a later
  `iso` kind, but ISO validation and picker UX are separate work.
- Mixing optical and BDMV sources inside one orchestration session.

## Likely files

- `src/riplex/disc/source.py` (new): source model, normalization, preparation,
  and assignment checks.
- `src/riplex/disc/makemkv.py`: source arguments, scan/rip errors, output
  association, and drive-resolution cleanup.
- `src/riplex_cli/main.py`: CLI arguments.
- `src/riplex_cli/commands/rip.py`: single-source preparation.
- `src/riplex_cli/commands/orchestrate.py`: source-aware queue interaction.
- `src/riplex_app/main.py`: source state and screen registration.
- `src/riplex_app/screens/welcome.py` or a new source-selection screen.
- `src/riplex_app/screens/disc_detection.py`: physical-source branch.
- `src/riplex_app/screens/disc_swap.py`: source-aware next-disc interaction.
- `src/riplex_app/screens/progress.py`: source-based ripping and ejection.
- GUI copy in overview, metadata, selection, done, and bug-report surfaces.
- Focused unit tests plus CLI and headless GUI integration scenarios.
- Architecture, CLI, GUI, troubleshooting, and changelog documentation.

## Recommended decisions to confirm

1. Use the user-facing option name `--backup`, with help text explicitly
   naming BDMV, instead of exposing MakeMKV's `file:` syntax.
2. Keep one source mode per orchestration session. A mixed physical/backup
   queue can be considered later if real demand appears.
3. Require explicit `--discs` ordering for multiple backups in automated CLI
   runs rather than trusting runtime-based disc detection.
4. Do not persist backup paths for resume; ask the user to select each pending
   source again.
5. Ship BDMV first and leave ISO as a small follow-up built on the same source
   abstraction.