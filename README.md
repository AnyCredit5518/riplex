# plex-planner

A tool for planning and organizing MakeMKV disc rips into Plex-compatible folder structures.

Given a movie or TV show title, plex-planner looks up canonical metadata (title, year, type, episodes, runtimes) and outputs the exact folder structure, filenames, and runtimes that Plex expects. It can also scan MakeMKV rip folders, detect duplicates, look up disc extras metadata from dvdcompare.net, match ripped files to their correct identities by runtime, and move everything into the right Plex folder layout.

## Features

**Orchestrate mode (`orchestrate`)**
- Full multi-disc rip-then-organize pipeline in a single command
- Auto-detects title from disc volume label (no arguments required)
- Looks up dvdcompare for disc contents, shows what is on each disc
- Select which discs to rip (skip standard Blu-ray copies, bonus discs, etc.)
- Resumes from previously ripped discs (detects existing rip folders)
- Disc-swap prompts with content descriptions between discs
- Live disc analysis: title classification, rip/skip recommendations, size estimates
- After ripping, automatically organizes all files into Plex folder structure
- Archives the rip folder to a configurable location after organize (optional)
- Dry-run preview by default, `--execute` to actually rip and organize
- `--snapshot` mode: scan disc and write manifest without ripping (useful for already-ripped files)
- `--auto` mode: skip all interactive prompts for scripted/scheduled use

**Rip mode (`rip`)**
- Rip selected titles from a physical disc using makemkvcon
- Live disc analysis with title classification (main film, episodes, extras, duplicates, play-all)
- Auto-selects titles to rip (skips play-all compilations, lower-resolution duplicates, very short titles)
- Manual title selection via `--titles` or `--all`
- Auto-detects title from disc volume label
- Optional post-rip organize with `--organize`
- Dry-run preview by default, `--execute` to actually rip

**Organize mode (`organize`)**
- Scans MakeMKV rip folders and extracts MKV metadata via ffprobe
- Detects and removes duplicate MKV files (same content ripped from different playlists)
  - Tier 1: fast metadata fingerprint (duration, file size, stream layout, chapter durations)
  - Tier 2: perceptual hashing via ffmpeg for visual confirmation
- Detects and removes "play all" compilation files (e.g. a single MKV that concatenates multiple episodes)
  - Matches individual chapter durations to other files with the same stream layout
  - Supports both one-chapter-per-file and grouped chapters (consecutive chapters summing to a file's duration)
- Looks up disc extras metadata from dvdcompare.net (featurettes, interviews, deleted scenes, trailers, etc.)
- Maps scanned folders to disc numbers using naming heuristics
- Matches ripped files to disc extras by runtime with confidence levels
- Builds Plex-canonical destination paths and moves/renames files
- Automatically splits multi-episode "play all" files by chapters (using mkvmerge) when chapter count matches TMDb Season 00 episodes
- Detects files whose chapters match missing disc entries and converts them to chapter-based splits
- Routes unmatched files to Plex extras folders with `--unmatched extras`
- Tags organized files with a `PLEX_PLANNER` MKV global tag via mkvpropedit; re-runs skip tagged files unless `--force`
- Auto-detects disc format from video resolution (3840x2160 = 4K, 1920x1080 = Blu-ray, 720x480 = DVD) when `--format` not specified
- Detects incomplete/still-ripping files (0 duration or no streams) and skips them with a warning
- Batch mode: point `organize` at a parent folder containing multiple rip subfolders; auto-groups by title, auto-detects format, and processes each title in sequence
- Debug logging to the OS temp directory on every run; `--verbose` prints to stderr
- Dry-run preview by default, `--execute` to actually move files

**Lookup mode (`lookup`)**
- Shows disc contents and recommended rip strategy *before* ripping in MakeMKV
- Looks up TMDb for canonical title/year, then dvdcompare for full disc breakdown
- Outputs recommended staging folder structure
- Per-disc content listings with runtimes, chapter counts, and feature types
- Identifies film discs, extras discs, and play-all groups
- Suggests which MakeMKV titles to rip vs skip (play-all detection, duplicate avoidance)
- Live disc analysis via `--drive` (reads physical disc with makemkvcon)
- `--create-folders` pre-creates the directory structure for ripping
- Human-readable text and JSON output modes

**General**
- Interactive mode by default: numbered-list prompts for ambiguous TMDb matches, dvdcompare release selection, and title confirmation when running in a terminal. Pass `--auto` to skip all prompts for scripted/scheduled use.
- File-based JSON caching for dvdcompare (30-day TTL) and TMDb (7-day TTL) responses, stored in the OS cache directory; bypass with `--no-cache`
- Windows-safe filename normalization
- Configurable output root via CLI flag, environment variable, or config file

## Requirements

- Python 3.11+
- A TMDb API key (free at https://www.themoviedb.org/settings/api)
- MakeMKV with makemkvcon (required for `rip` and `orchestrate` modes)
- ffprobe (from ffmpeg, required for `organize` mode)
- mkvmerge (from MKVToolNix, required for chapter splitting in `organize` mode)
- mkvpropedit (from MKVToolNix, required for organized tagging in `organize` mode)
- [dvdcompare-scraper](../dvdcompare-scraper) (file dependency, required for `organize` mode)

## Installation

```bash
cd Projects/plex-planner
pip install -e ".[dev]"
```

## Configuration

Create a config file at `%APPDATA%\plex-planner\config.toml` (Windows) or `~/.config/plex-planner/config.toml` (Linux/macOS), or place a `plex-planner.toml` in the current working directory:

```toml
tmdb_api_key = "your_api_key_here"
output_root = "/path/to/media"
rip_output = "/path/to/media/Rips"
archive_root = "/path/to/media/Rips/_archive"
```

| Key | Description |
|---|---|
| `tmdb_api_key` | TMDb API key |
| `output_root` | Root directory for organized output. Plex subfolders like `Movies\` and `TV Shows\` are created under this. |
| `rip_output` | Directory for MakeMKV rip output. Default: `{output_root}/Rips`. Used by `rip` and `orchestrate`. |
| `archive_root` | Directory to move rip folders after successful organize. Optional; if not set, rip folders are left in place. |

Both settings can also be provided via environment variables or CLI flags:

| Setting | CLI flag | Env var | Config key |
|---|---|---|---|
| TMDb API key | `--api-key` | `TMDB_API_KEY` | `tmdb_api_key` |
| Output root | `--output` | `PLEX_ROOT` | `output_root` |
| Rip output | `--output` | - | `rip_output` |
| Archive root | - | - | `archive_root` |

Priority order: CLI flag > environment variable > config file.

## Usage

### Orchestrate: full multi-disc rip and organize

Insert a disc and run with no arguments (title auto-detected from volume label):

```bash
plex-planner orchestrate --execute
```

Output:
```
Scanning drives ...
Found disc in drive 0: 300 (D:)
Reading disc info ...
Auto-detected title from volume label: 300
TMDb: 300 (2007)
Looking up disc metadata on dvdcompare.net ...

Blu-ray ALL America - Warner Home Video [2 discs]
  Disc 1 (Blu-ray 4K): Audio commentary, Main Film  [INSERTED]
  Disc 2 (Blu-ray): Behind The Story, Webisodes, Deleted scenes

Which discs do you want to rip?
  1. Disc 1 (Blu-ray 4K): Audio commentary, Main Film
  2. Disc 2 (Blu-ray): Behind The Story, Webisodes, Deleted scenes

Selection [default=all]: all

Live disc analysis: 300

    #   Duration      Size        Res   Ch  Recommendation
  ---  ---------  --------  ---------  ---  ----------------------------------------
    0    1:56:38   58.3 GB  3840x2160   30  MAIN FILM (4K) - rip this
    1       2:20    0.8 GB  3840x2160    3  Episode (4K) - rip this
    2       5:40    0.2 GB  3840x2160   34  Episode (4K) - rip this
    3    1:56:38   58.3 GB  3840x2160   30  Duplicate of #0 (4K) - skip

Will rip 3 title(s) [0, 1, 2] (59.2 GB)
Output: /path/to/rips/300 (2007)/Disc 1
...
```

### Orchestrate: dry-run preview (default)

```bash
plex-planner orchestrate
```

Without `--execute`, shows what would be ripped and organized without making changes.

### Orchestrate: skip interactive prompts

```bash
plex-planner orchestrate --execute --auto
```

Uses best-guess defaults for all selections (TMDb match, dvdcompare release, disc selection).

### Orchestrate: select specific discs

```bash
plex-planner orchestrate --execute --discs 1,3
```

### Orchestrate: snapshot mode (scan without ripping)

```bash
plex-planner orchestrate --snapshot
```

Scans the inserted disc and writes a manifest file without ripping. Useful to regenerate manifests for files already ripped manually.

### Rip: single disc with auto-selection

```bash
plex-planner rip --execute
```

Reads the disc, auto-detects the title from the volume label, shows a disc analysis table, and rips the recommended titles.

### Rip: manual title selection

```bash
plex-planner rip "Oppenheimer" --titles 0,1,2 --execute
```

### Rip: with post-rip organize

```bash
plex-planner rip --execute --organize
```

### Plan: basic lookup

```bash
plex-planner plan "Oppenheimer" --year 2023
```

Output:
```
type: movie
canonical_title: Oppenheimer
year: 2023
runtime: 3h 1m

relative_paths:
  \Movies\Oppenheimer (2023)\
  \Movies\Oppenheimer (2023)\Featurettes\
  \Movies\Oppenheimer (2023)\Interviews\
  \Movies\Oppenheimer (2023)\Behind The Scenes\
  \Movies\Oppenheimer (2023)\Deleted Scenes\
  \Movies\Oppenheimer (2023)\Trailers\
  \Movies\Oppenheimer (2023)\Other\

main_file:
  Oppenheimer (2023).mkv
```

### Plan: TV show

```bash
plex-planner plan "A Perfect Planet" --year 2021
```

Output:
```
type: tv
canonical_title: A Perfect Planet
year: 2021

relative_paths:
  \TV Shows\A Perfect Planet (2021)\Season 00\
  \TV Shows\A Perfect Planet (2021)\Season 01\

items:
  s00e01 - Making a Perfect Planet - 44m
    file: A Perfect Planet (2021) - s00e01 - Making a Perfect Planet.mkv
  s01e01 - Volcano - 48m
    file: A Perfect Planet (2021) - s01e01 - Volcano.mkv
  ...
```

### Plan: JSON output

```bash
plex-planner plan "Top Gun Maverick" --year 2022 --json
```

### Plan: force media type

```bash
plex-planner plan "Planet Earth III" --year 2023 --type tv
```

### Plan: exclude specials or extras

```bash
plex-planner plan "X-Men The Animated Series" --year 1992 --no-specials
plex-planner plan "Oppenheimer" --year 2023 --no-extras
```

### Plan: match ripped files by runtime

```bash
plex-planner plan "A Perfect Planet" --year 2021 \
  --match title_t00.mkv:48m12s title_t01.mkv:47m58s title_t02.mkv:44m03s
```

This produces a match report comparing each ripped file's duration against the planned episode runtimes, with confidence levels (high/medium/low).

### Organize: scan and sort a MakeMKV rip folder

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

Output:
```
Scanning path/to/rips/Oppenheimer ...
Found 9 MKV files in 2 disc group(s).
Detected 1 duplicate(s) in 1 group(s):
  DUPLICATE: Special Features_t02.mkv (keeping Special Features_t17.mkv)
Proceeding with 8 files after dedup.
TMDb: Oppenheimer (2023)
Looking up disc metadata on dvdcompare.net ...
Found 3 disc(s) on dvdcompare.
  Oppenheimer -> Disc 1
  Special Features -> Disc 3

--- DRY RUN (use --execute to move files) ---

Would organize to: Movies/Oppenheimer (2023)

Main Feature (1 file)
  Oppenheimer (2023).mkv                        <- Oppenheimer_t00.mkv

Featurettes (3 files)
  The Story of Our Time.mkv                     <- Special Features_t03.mkv
  To End All War.mkv                            <- Special Features_t04.mkv
  An Event That Changed the World.mkv           <- Special Features_t05.mkv

Interviews (2 files)
  Meet the Press Q&A Panel Oppenheimer.mkv      <- Special Features_t17.mkv
  Innovation in Film.mkv                        <- Special Features_t06.mkv

Unmatched (2 files, would move to Other/)
  Extra 1.mkv                                   <- Special Features_t01.mkv
  Extra 2.mkv                                   <- Special Features_t08.mkv
```

Add `--execute` to actually move the files:

```bash
plex-planner organize path/to/rips/Oppenheimer --year 2023 --format "Blu-ray 4K" --execute
```

### Organize: TV show (multi-disc)

```bash
plex-planner organize "path/to/rips/PLANET EARTH II" --type tv --format "Blu-ray 4K"
```

Output:
```
Scanning path/to/rips/PLANET EARTH II ...
Found 7 MKV files in 3 disc group(s).
TMDb: Planet Earth II (2016)
Looking up disc metadata on dvdcompare.net ...
Found 3 disc(s) on dvdcompare.
  PLANET EARTH II - DISC 1 -> Disc 1
  PLANET EARTH II - DISC 2 -> Disc 2
  PLANET EARTH II - DISC 3 -> Disc 3
Matched 7 files, 0 unmatched, 0 missing.

--- DRY RUN (use --execute to move files) ---

Would organize to: TV Shows/Planet Earth II (2016)/Season 01

Season 01 (6 files)
  Planet Earth II (2016) - s01e01 - Islands.mkv       <- PLANET EARTH II - DISC 1_t01.mkv
  Planet Earth II (2016) - s01e02 - Mountains.mkv     <- PLANET EARTH II - DISC 1_t02.mkv
  Planet Earth II (2016) - s01e03 - Jungles.mkv       <- PLANET EARTH II - DISC 1_t00.mkv
  Planet Earth II (2016) - s01e04 - Deserts.mkv       <- PLANET EARTH II - DISC 2_t00.mkv
  Planet Earth II (2016) - s01e05 - Grasslands.mkv    <- PLANET EARTH II - DISC 2_t02.mkv
  Planet Earth II (2016) - s01e06 - Cities.mkv        <- PLANET EARTH II - DISC 2_t01.mkv

Featurettes (1 file)
  Planet Earth Diaries.mkv                            <- PLANET EARTH II DIARIES_t00.mkv
```

When the scanner detects that a file (like Planet Earth Diaries) has chapter markers matching the number of TMDb Season 00 episodes, the tool automatically plans a chapter split instead of a single move:

```
Would organize to: TV Shows/Planet Earth II (2016)/Season 00

Main (6 files)
  Planet Earth II (2016) - s00e01 - Diaries Islands.mkv       <- PLANET EARTH II DIARIES_t00.mkv (split)
  Planet Earth II (2016) - s00e02 - Diaries Mountains.mkv     <- PLANET EARTH II DIARIES_t00.mkv (split)
  ...
```

With `--execute`, this uses mkvmerge to split the file by chapters and moves each piece to the correct Season 00 location. This ensures each special appears as a separate episode in Plex.

### Organize: regional release selection

dvdcompare lists multiple regional releases. By default, the first American release is used. You can specify a different release by name keyword or 1-based index:

```bash
plex-planner organize path/to/rips/Oppenheimer --format "Blu-ray 4K" --release uk
plex-planner organize path/to/rips/Oppenheimer --format "Blu-ray 4K" --release 2
```

### Organize: unmatched file policy

Files that can't be confidently matched are handled by the `--unmatched` flag:

- `ignore` (default): leave files in place, just report them
- `move`: move unmatched files to `_Unmatched/<title>/` under the output root
- `delete`: remove unmatched files
- `extras`: route files >= 60s to the Plex `Other/` extras folder for the title, named `Extra 1.mkv`, `Extra 2.mkv`, etc.

```bash
# Preview what would happen
plex-planner organize path/to/rips/Oppenheimer --unmatched move

# Actually move matched files and relocate unmatched ones
plex-planner organize path/to/rips/Oppenheimer --unmatched move --execute

# Route unmatched files to the Plex extras folder
plex-planner organize path/to/rips/Oppenheimer --unmatched extras
```

### Organize: batch mode

Point `organize` at a parent folder containing multiple rip subfolders. The tool auto-detects title groups, infers format from resolution, and processes each title in sequence:

```bash
plex-planner organize path/to/rips
```

Output:
```
Batch mode: found 3 title group(s).
  Batman Begins (1 folder(s): Batman Begins)
  Dark Knight Rises (1 folder(s): Dark Knight Rises)
  The Dark Knight (1 folder(s): The Dark Knight)

============================================================
[1/3] Batman Begins
============================================================
Scanning path/to/rips/Batman Begins ...
...
```

Multi-disc rips in separate folders (e.g. "Planet Earth III - Disc 1", "Planet Earth III - Disc 2") are automatically grouped into a single title.

### Organize: re-organize (--force)

After a successful `--execute`, each organized file is tagged with a `PLEX_PLANNER` marker in the MKV container (via mkvpropedit). Subsequent runs automatically skip these files:

```bash
# First run organizes everything
plex-planner organize path/to/rips/Oppenheimer --execute

# Second run skips already-organized files
plex-planner organize path/to/rips/Oppenheimer
# "Skipping 17 already-organized file(s)."

# Force re-organize
plex-planner organize path/to/rips/Oppenheimer --force
```

### Organize: debug logging

Every `organize` run writes detailed debug logs to the OS temp directory. The log captures every decision: file probing, duplicate/compilation detection, disc mapping heuristics, target matching, destination routing, and chapter split logic.

Add `--verbose` to also print debug output to stderr:

```bash
plex-planner organize path/to/rips/Oppenheimer --year 2023 --verbose
```

### Lookup: plan before ripping

Before inserting a disc, use `lookup` to see what's on it and how to rip efficiently:

```bash
plex-planner lookup "Frozen Planet II"
```

Output:
```
Frozen Planet II (2022) [TV Show]
============================================================

Recommended rip folder structure:
  Rips/Frozen Planet II (2022)/Disc 1/ [Blu-ray 4K] (episodes)
  Rips/Frozen Planet II (2022)/Disc 2/ [Blu-ray 4K] (episodes + extras)
  Rips/Frozen Planet II (2022)/Disc 3/ [Blu-ray] (episodes)
  Rips/Frozen Planet II (2022)/Disc 4/ [Blu-ray] (episodes)

Disc contents (4 disc(s)):
------------------------------------------------------------

  Disc 1 [Blu-ray 4K]
    Episodes (3, total 2:36:33):
      Frozen Worlds (52:11)
      Frozen Ocean (51:47)
      Frozen Peaks (52:35)
  ...

Rip tips:
  - Disc 1: has 3 episodes (total 2:36:33). If MakeMKV shows a single
    title with 3 or more chapters totaling ~2:36:33, that is the play-all.
    You can rip just that one title; plex-planner will split it by chapters.
  ...
```

The play-all tip is key: instead of ripping 4 titles per disc (~130 GB), rip one play-all title per disc (~65 GB). plex-planner's chapter-split logic handles the rest.

### Lookup: pre-create folder structure

```bash
plex-planner lookup "Blade Runner" --year 1982 --format "Blu-ray 4K" --create-folders
```

This creates the recommended rip folder structure (e.g. `<rip_output>/Blade Runner (1982)/Disc 1/` through `Disc 8/`) so you can point MakeMKV's output at the correct disc subfolder as you rip.

### Lookup: movie with extras

```bash
plex-planner lookup "Oppenheimer" --year 2023
```

For movies, the guide identifies which disc has the main film vs extras, and labels play-all bonus groups appropriately.

## CLI Reference

### `orchestrate` subcommand

| Option | Description |
|---|---|
| `--title` | Movie or TV show title (auto-detected from volume label if omitted) |
| `--drive` | Drive index (`0`), device (`D:`), or `auto` (default: `auto`) |
| `--year` | Release year |
| `--type` | Force `movie`, `tv`, or `auto` (default: `auto`) |
| `--format` | Disc format filter for dvdcompare (auto-detected from disc resolution if omitted) |
| `--release` | Regional release: 1-based index or name keyword (default: auto-detect) |
| `--output` | Output root directory (or set `PLEX_ROOT` env var, or config) |
| `--execute` | Actually rip and organize (default: dry-run preview only) |
| `--unmatched` | Policy for unmatched files during organize: `ignore`, `move`, `delete`, or `extras` (default: `extras`) |
| `--discs` | Comma-separated disc numbers to rip (e.g. `1,3`). Skips others. |
| `--snapshot` | Scan disc and write manifest without ripping |
| `--yes`, `-y` | Skip confirmation prompts |
| `--auto` | Skip interactive prompts, use best-guess defaults |
| `--json` | Output as JSON |
| `--verbose`, `-v` | Print debug logging to stderr |
| `--no-cache` | Bypass cached dvdcompare and TMDb responses |
| `--api-key` | TMDb API key |

### `rip` subcommand

| Option | Description |
|---|---|
| `title` | Movie or TV show title (positional, auto-detected from volume label if omitted) |
| `--drive` | Drive index (`0`), device (`D:`), or `auto` (default: `auto`) |
| `--year` | Release year |
| `--type` | Force `movie`, `tv`, or `auto` (default: `auto`) |
| `--format` | Disc format filter for dvdcompare (auto-detected from disc resolution if omitted) |
| `--release` | Regional release: 1-based index or name keyword (default: auto-detect) |
| `--output` | Output root directory (or set `PLEX_ROOT` env var, or config) |
| `--titles` | Comma-separated title indices to rip (overrides auto-recommendation) |
| `--all` | Rip all titles (skip recommendation filter) |
| `--execute` | Actually rip (default: dry-run preview only) |
| `--organize` | Automatically run organize after ripping |
| `--yes`, `-y` | Skip confirmation prompt |
| `--auto` | Skip interactive prompts, use best-guess defaults |
| `--json` | Output as JSON |
| `--verbose`, `-v` | Print debug logging to stderr |
| `--no-cache` | Bypass cached dvdcompare and TMDb responses |
| `--api-key` | TMDb API key |

### `organize` subcommand

| Option | Description |
|---|---|
| `folder` | Path to a MakeMKV rip folder (required) |
| `--title` | Override title (default: folder name) |
| `--year` | Release year |
| `--type` | Force `movie`, `tv`, or `auto` (default: `auto`) |
| `--format` | Disc format filter for dvdcompare (e.g. `Blu-ray 4K`). Auto-detected from resolution if omitted. |
| `--release` | Regional release: 1-based index or name keyword (default: auto-detect) |
| `--output` | Output root directory (or set `PLEX_ROOT` env var, or `output_root` in config) |
| `--execute` | Actually move files (default: dry-run preview only) |
| `--unmatched` | Policy for unmatched files: `ignore` (default), `move`, `delete`, or `extras` |
| `--snapshot` | Replay from a snapshot JSON file instead of scanning live files |
| `--auto` | Skip interactive prompts, use best-guess defaults |
| `--verbose`, `-v` | Print debug logging to stderr (log file is always written) |
| `--no-cache` | Bypass cached dvdcompare and TMDb responses |
| `--force` | Re-organize files even if already tagged as organized |
| `--json` | Output as JSON |
| `--api-key` | TMDb API key |

### `lookup` subcommand

| Option | Description |
|---|---|
| `title` | Movie or TV show title (required) |
| `--year` | Release year |
| `--type` | Force `movie`, `tv`, or `auto` (default: `auto`) |
| `--format` | Disc format filter for dvdcompare (e.g. `Blu-ray 4K`) |
| `--release` | Regional release: 1-based index or name keyword (default: `america`) |
| `--drive` | Read live disc info: drive index (`0`), device (`D:`), or `auto` |
| `--output` | Output root for `--create-folders` (or set `PLEX_ROOT` env var, or config) |
| `--create-folders` | Pre-create the recommended rip folder structure |
| `--json` | Output as JSON (includes `disc_analysis` when `--drive` is also set) |
| `--verbose`, `-v` | Print debug logging to stderr |
| `--no-cache` | Bypass cached dvdcompare and TMDb responses |
| `--api-key` | TMDb API key |

## Running Tests

```bash
pytest
```

## Project Structure

```
src/plex_planner/
    __init__.py
    cli.py                  # CLI entry point (orchestrate, rip, organize, lookup subcommands)
    config.py               # Config file loading and setting resolution
    models.py               # Data models (ScannedFile, PlannedDisc, MatchCandidate, etc.)
    metadata_provider.py    # Abstract provider interface
    metadata_sources/
        tmdb.py             # TMDb API implementation
    normalize.py            # Filename/path normalization
    formatter.py            # Text and JSON output formatters
    planner.py              # Core planning orchestrator
    matcher.py              # Runtime-based file matching with disc constraints
    scanner.py              # MakeMKV folder scanner (ffprobe-based metadata extraction)
    snapshot.py             # Snapshot capture and loading (JSON serialization of scan results)
    detect.py               # Format auto-detection, title grouping, incomplete file detection
    dedup.py                # Duplicate MKV detection (metadata fingerprint + perceptual hash)
    cache.py                # File-based JSON cache with TTL (dvdcompare, TMDb)
    disc_provider.py        # dvdcompare.net disc extras metadata bridge
    disc_analysis.py        # Live disc analysis via makemkvcon (title classification, rip recommendations)
    makemkv.py              # makemkvcon wrapper (disc reading, title ripping, progress parsing)
    organizer.py            # Plex destination path builder and file mover
    splitter.py             # Chapter-based MKV splitting via mkvmerge
    tagger.py               # MKV organized tagging via mkvpropedit
    ui.py                   # Interactive prompts (multi-select, confirmations, text input)
tests/
    test_cache.py
    test_cli_utils.py
    test_config.py
    test_dedup.py
    test_detect.py
    test_disc_analysis.py
    test_disc_provider.py
    test_formatter.py
    test_makemkv.py
    test_matcher.py
    test_normalize.py
    test_organizer.py
    test_planner.py
    test_rip_guide.py
    test_scanner.py
    test_splitter.py
    test_tagger.py
    test_ui.py
    snapshots/              # MKV metadata snapshots for offline test replay
```

## Architecture

The metadata provider is abstracted behind a clean interface (`MetadataProvider`). The default implementation uses TMDb, which is the same source Plex uses for its metadata agents. The provider can be swapped out for TheTVDB or any other source by implementing the interface.

The tool has six modes:

- **`orchestrate`**: The primary workflow. Handles multi-disc rip-then-organize in a single session. Combines disc detection, dvdcompare lookup, disc selection, ripping (via makemkvcon), and organizing into one command.
- **`rip`**: Single-disc rip via makemkvcon. Disc analysis, auto title selection, and optional post-rip organize.
- **`organize`**: The file organization pipeline. Scans MKV files, deduplicates, looks up TMDb + dvdcompare, matches files by runtime, and moves everything into Plex folder layout.
- **`rip-guide`**: TMDb + dvdcompare lookup. Shows disc contents and recommended rip strategy before ripping.
- **`plan`** *(deprecated)*: Alias for `rip-guide`.
- **`snapshot`**: Captures MKV metadata to JSON for offline replay and debugging.

The organize workflow chains several stages: scanning (ffprobe), dedup (metadata fingerprint with perceptual hash confirmation, plus compilation/play-all detection via chapter analysis), TMDb lookup, dvdcompare disc extras lookup, disc-constrained matching (mapping scanned folders to disc numbers via naming heuristics, then matching files to extras by runtime), chapter-to-missing split detection, and finally building Plex-canonical paths and moving files. Comprehensive debug logging captures every decision for post-run analysis.

## Naming Rules

See [plex_naming_rules.md](plex_naming_rules.md) for the full Plex naming reference this tool follows.
