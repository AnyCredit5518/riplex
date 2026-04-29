# Organizing Files

The `organize` command is the main pipeline. It scans MakeMKV rip folders, deduplicates, looks up metadata from TMDb and dvdcompare.net, matches files to their correct identities by runtime, and moves everything into the Plex folder layout.

**Dry-run is the default.** Nothing is moved until you add `--execute`.

## Basic usage

```bash
plex-planner organize path/to/rips/Oppenheimer --year 2023 --format "Blu-ray 4K"
```

This will:

1. Scan the folder for MKV files and extract metadata via ffprobe
2. Detect and remove duplicate rips
3. Look up TMDb metadata for Plex-canonical naming
4. Look up disc extras from dvdcompare.net
5. Map scanned subfolders to disc numbers
6. Match files to extras by runtime
7. Print a dry-run preview of where each file would be moved

Add `--execute` to actually move the files:

```bash
plex-planner organize path/to/rips/Oppenheimer --year 2023 --format "Blu-ray 4K" --execute
```

## TV shows (multi-disc)

```bash
plex-planner organize "path/to/rips/PLANET EARTH II" --type tv --format "Blu-ray 4K"
```

Multi-disc rips in separate folders (e.g. "Planet Earth III - Disc 1", "Planet Earth III - Disc 2") are automatically grouped into a single title.

## Chapter splitting

When the scanner detects that a file has chapter markers matching the number of TMDb Season 00 episodes, the tool automatically plans a chapter split instead of a single move. With `--execute`, this uses mkvmerge to split the file by chapters and moves each piece to the correct Season 00 location.

## Regional release selection

dvdcompare lists multiple regional releases. In interactive mode (the default when running in a terminal), you will be presented with all available releases to choose from:

```
Select a dvdcompare release:
  1. North America (4K Ultra HD) [4 discs] *
  2. United Kingdom (4K Ultra HD) [4 discs]
  3. Germany (4K Ultra HD) [3 discs]
Choice [1-3, default=1]:
```

Press Enter to accept the default (marked with `*`) or type a number.

You can also specify a release directly:

```bash
plex-planner organize path/to/rips/Oppenheimer --format "Blu-ray 4K" --release uk
plex-planner organize path/to/rips/Oppenheimer --format "Blu-ray 4K" --release 2
```

Use `--auto` to skip the prompt and use the best-guess default (American release).

## Unmatched file policy

Files that cannot be confidently matched are handled by the `--unmatched` flag:

| Value | Behavior |
|---|---|
| `ignore` (default) | Leave files in place, just report them |
| `move` | Move unmatched files to `_Unmatched/<title>/` under the output root |
| `delete` | Remove unmatched files |
| `extras` | Route files >= 60s to the Plex `Other/` extras folder, named `Extra 1.mkv`, `Extra 2.mkv`, etc. |

```bash
plex-planner organize path/to/rips/Oppenheimer --unmatched extras
```

## Batch mode

Point `organize` at a parent folder containing multiple rip subfolders. The tool auto-detects title groups, infers format from resolution, and processes each title in sequence:

```bash
plex-planner organize path/to/rips
```

Multi-disc rips in separate folders are automatically grouped into a single title.

## Re-organize (--force)

After a successful `--execute`, each organized file is tagged with a `PLEX_PLANNER` marker in the MKV container (via mkvpropedit). Subsequent runs automatically skip these files.

```bash
# First run organizes everything
plex-planner organize path/to/rips/Oppenheimer --execute

# Second run skips already-organized files
plex-planner organize path/to/rips/Oppenheimer
# "Skipping 17 already-organized file(s)."

# Force re-organize
plex-planner organize path/to/rips/Oppenheimer --force
```

## Duplicate detection

Duplicate MKV files (same content ripped from different playlists) are automatically detected and removed before matching:

- **Tier 1**: Fast metadata fingerprint (duration, file size, stream layout, chapter durations)
- **Tier 2**: Perceptual hashing via ffmpeg for visual confirmation

## Play-all detection

"Play all" compilation files (a single MKV that concatenates multiple episodes) are detected and handled:

- Matches individual chapter durations to other files with the same stream layout
- Supports both one-chapter-per-file and grouped chapters (consecutive chapters summing to a file's duration)
- Automatically removed from the file set so individual episodes are organized instead

## Debug logging

Every `organize` run writes detailed debug logs to the OS temp directory. Add `--verbose` to also print debug output to stderr:

```bash
plex-planner organize path/to/rips/Oppenheimer --year 2023 --verbose
```

## Options

| Option | Description |
|---|---|
| `folder` | Path to a MakeMKV rip folder (required) |
| `--title` | Override title (default: folder name) |
| `--year` | Release year |
| `--type` | Force `movie`, `tv`, or `auto` (default: `auto`) |
| `--format` | Disc format filter for dvdcompare (e.g. `Blu-ray 4K`). Auto-detected from resolution if omitted. |
| `--release` | Regional release: 1-based index or name keyword (default: `america`) |
| `--output` | Output root directory (or set `PLEX_ROOT` env var, or `output_root` in config) |
| `--execute` | Actually move files (default: dry-run preview only) |
| `--unmatched` | Policy for unmatched files: `ignore` (default), `move`, `delete`, or `extras` |
| `--verbose`, `-v` | Print debug logging to stderr (log file is always written) |
| `--no-cache` | Bypass cached dvdcompare and TMDb responses |
| `--force` | Re-organize files even if already tagged as organized |
| `--json` | Output as JSON |
| `--api-key` | TMDb API key |
| `--snapshot` | Replay from a snapshot JSON file instead of scanning live files |
| `--auto` | Skip interactive prompts, use best-guess defaults |

## Interactive mode

When running in a terminal (stdin is a TTY), `organize` presents interactive prompts at several decision points:

1. **Title confirmation**: After inferring the title from the folder name or MKV metadata, you can confirm or correct it.
2. **TMDb disambiguation**: If multiple TMDb matches exist for the title, a numbered list is shown for selection.
3. **dvdcompare release**: If multiple regional releases exist, a numbered list is shown (defaults to the American release).

To skip all prompts and use automatic defaults, pass `--auto`:

```bash
plex-planner organize path/to/rips/Oppenheimer --auto
```

Non-TTY environments (piped input, cron jobs, CI) are automatically non-interactive.
