# plex-planner

A tool for planning and organizing MakeMKV disc rips into Plex-compatible folder structures.

Given a movie or TV show title, plex-planner looks up canonical metadata (title, year, type, episodes, runtimes) and outputs the exact folder structure, filenames, and runtimes that Plex expects. It can also scan MakeMKV rip folders, detect duplicates, look up disc extras metadata from dvdcompare.net, match ripped files to their correct identities by runtime, and move everything into the right Plex folder layout.

## Features

**Planning mode (`plan`)**
- Identifies whether a title is a movie or TV show via TMDb
- Outputs Plex-canonical folder structure and filenames
- Includes episode titles and runtimes for TV shows
- Includes specials (Season 00) when present
- Generates optional extras folder skeletons (Featurettes, Interviews, etc.)
- Optional runtime-based matching of ripped files to episodes
- Human-readable text and JSON output modes

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
- Debug logging to `%TEMP%\plex-planner\plex-planner.log` on every run; `--verbose` prints to stderr
- Dry-run preview by default, `--execute` to actually move files

**General**
- File-based JSON caching for dvdcompare (30-day TTL) and TMDb (7-day TTL) responses, stored in the OS cache directory; bypass with `--no-cache`
- Windows-safe filename normalization
- Configurable output root via CLI flag, environment variable, or config file

## Requirements

- Python 3.11+
- A TMDb API key (free at https://www.themoviedb.org/settings/api)
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
output_root = "E:\\Media"
```

| Key | Description |
|---|---|
| `tmdb_api_key` | TMDb API key |
| `output_root` | Root directory for organized output (e.g. `E:\Media`). Plex subfolders like `Movies\` and `TV Shows\` are created under this. |

Both settings can also be provided via environment variables or CLI flags:

| Setting | CLI flag | Env var | Config key |
|---|---|---|---|
| TMDb API key | `--api-key` | `TMDB_API_KEY` | `tmdb_api_key` |
| Output root | `--output` | `PLEX_ROOT` | `output_root` |

Priority order: CLI flag > environment variable > config file.

## Usage

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
plex-planner organize E:\Media\_MakeMKV\Oppenheimer --year 2023 --format "Blu-ray 4K"
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
Scanning E:\Media\_MakeMKV\Oppenheimer ...
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

  WOULD MOVE: Special Features_t17.mkv
          TO: E:\Media\Movies\Oppenheimer (2023)\Interviews\Meet the Press Q&A Panel Oppenheimer.mkv
       MATCH: [high] Disc 3: Meet the Press Q&A Panel: Oppenheimer (interviews)
  ...
```

Add `--execute` to actually move the files:

```bash
plex-planner organize E:\Media\_MakeMKV\Oppenheimer --year 2023 --format "Blu-ray 4K" --execute
```

### Organize: TV show (multi-disc)

```bash
plex-planner organize "E:\Media\_MakeMKV\PLANET EARTH II" --type tv --format "Blu-ray 4K"
```

Output:
```
Scanning E:\Media\_MakeMKV\PLANET EARTH II ...
Found 7 MKV files in 3 disc group(s).
TMDb: Planet Earth II (2016)
Looking up disc metadata on dvdcompare.net ...
Found 3 disc(s) on dvdcompare.
  PLANET EARTH II - DISC 1 -> Disc 1
  PLANET EARTH II - DISC 2 -> Disc 2
  PLANET EARTH II - DISC 3 -> Disc 3
Matched 7 files, 0 unmatched, 0 missing.

--- DRY RUN (use --execute to move files) ---

  WOULD MOVE: PLANET EARTH II - DISC 1_t01.mkv
          TO: E:\Media\TV Shows\Planet Earth II (2016)\Season 01\Planet Earth II (2016) - s01e01 - Islands.mkv
       MATCH: [high] Disc 1: Islands

  WOULD MOVE: PLANET EARTH II - DISC 1_t02.mkv
          TO: E:\Media\TV Shows\Planet Earth II (2016)\Season 01\Planet Earth II (2016) - s01e02 - Mountains.mkv
       MATCH: [high] Disc 1: Mountains

  WOULD MOVE: PLANET EARTH II - DISC 1_t00.mkv
          TO: E:\Media\TV Shows\Planet Earth II (2016)\Season 01\Planet Earth II (2016) - s01e03 - Jungles.mkv
       MATCH: [high] Disc 1: Jungles

  WOULD MOVE: PLANET EARTH II - DISC 2_t00.mkv
          TO: E:\Media\TV Shows\Planet Earth II (2016)\Season 01\Planet Earth II (2016) - s01e04 - Deserts.mkv
       MATCH: [low] Disc 2: Deserts

  WOULD MOVE: PLANET EARTH II - DISC 2_t02.mkv
          TO: E:\Media\TV Shows\Planet Earth II (2016)\Season 01\Planet Earth II (2016) - s01e05 - Grasslands.mkv
       MATCH: [high] Disc 2: Grasslands

  WOULD MOVE: PLANET EARTH II - DISC 2_t01.mkv
          TO: E:\Media\TV Shows\Planet Earth II (2016)\Season 01\Planet Earth II (2016) - s01e06 - Cities.mkv
       MATCH: [low] Disc 2: Cities

  WOULD MOVE: PLANET EARTH II DIARIES_t00.mkv
          TO: E:\Media\TV Shows\Planet Earth II (2016)\Featurettes\Planet Earth Diaries.mkv
       MATCH: [high] Disc 3: Planet Earth Diaries (featurettes)
```

When the scanner detects that a file (like Planet Earth Diaries) has chapter markers matching the number of TMDb Season 00 episodes, the tool automatically plans a chapter split instead of a single move:

```
  WOULD SPLIT: PLANET EARTH II DIARIES_t00.mkv
     ORIGINAL: Disc 3: Planet Earth Diaries (featurettes)
   CHAPTER -> E:\Media\TV Shows\Planet Earth II (2016)\Season 00\Planet Earth II (2016) - s00e01 - Diaries Islands.mkv
      MATCH: [high] s00e01 - Diaries: Islands
   CHAPTER -> E:\Media\TV Shows\Planet Earth II (2016)\Season 00\Planet Earth II (2016) - s00e02 - Diaries Mountains.mkv
      MATCH: [high] s00e02 - Diaries: Mountains
   ...
```

With `--execute`, this uses mkvmerge to split the file by chapters and moves each piece to the correct Season 00 location. This ensures each special appears as a separate episode in Plex.

### Organize: regional release selection

dvdcompare lists multiple regional releases. By default, the first American release is used. You can specify a different release by name keyword or 1-based index:

```bash
plex-planner organize E:\Media\_MakeMKV\Oppenheimer --format "Blu-ray 4K" --release uk
plex-planner organize E:\Media\_MakeMKV\Oppenheimer --format "Blu-ray 4K" --release 2
```

### Organize: unmatched file policy

Files that can't be confidently matched are handled by the `--unmatched` flag:

- `ignore` (default): leave files in place, just report them
- `move`: move unmatched files to `_Unmatched/<title>/` under the output root
- `delete`: remove unmatched files
- `extras`: route files >= 60s to the Plex `Other/` extras folder for the title, named `Extra 1.mkv`, `Extra 2.mkv`, etc.

```bash
# Preview what would happen
plex-planner organize E:\Media\_MakeMKV\Oppenheimer --unmatched move

# Actually move matched files and relocate unmatched ones
plex-planner organize E:\Media\_MakeMKV\Oppenheimer --unmatched move --execute

# Route unmatched files to the Plex extras folder
plex-planner organize E:\Media\_MakeMKV\Oppenheimer --unmatched extras
```

### Organize: batch mode

Point `organize` at a parent folder containing multiple rip subfolders. The tool auto-detects title groups, infers format from resolution, and processes each title in sequence:

```bash
plex-planner organize E:\Media\_MakeMKV
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
Scanning E:\Media\_MakeMKV\Batman Begins ...
...
```

Multi-disc rips in separate folders (e.g. "Planet Earth III - Disc 1", "Planet Earth III - Disc 2") are automatically grouped into a single title.

### Organize: re-organize (--force)

After a successful `--execute`, each organized file is tagged with a `PLEX_PLANNER` marker in the MKV container (via mkvpropedit). Subsequent runs automatically skip these files:

```bash
# First run organizes everything
plex-planner organize E:\Media\_MakeMKV\Oppenheimer --execute

# Second run skips already-organized files
plex-planner organize E:\Media\_MakeMKV\Oppenheimer
# "Skipping 17 already-organized file(s)."

# Force re-organize
plex-planner organize E:\Media\_MakeMKV\Oppenheimer --force
```

### Organize: debug logging

Every `organize` run writes detailed debug logs to `%TEMP%\plex-planner\plex-planner.log`. The log captures every decision: file probing, duplicate/compilation detection, disc mapping heuristics, target matching, destination routing, and chapter split logic.

Add `--verbose` to also print debug output to stderr:

```bash
plex-planner organize E:\Media\_MakeMKV\Oppenheimer --year 2023 --verbose
```

## CLI Reference

### `plan` subcommand

| Option | Description |
|---|---|
| `title` | Movie or TV show title (required) |
| `--year` | Release year (strongly recommended) |
| `--type` | Force `movie`, `tv`, or `auto` (default: `auto`) |
| `--json` | Output as JSON |
| `--no-specials` | Exclude Season 00 specials |
| `--no-extras` | Omit extras folder skeleton |
| `--match` | Match ripped files by duration (format: `file:duration`) |
| `--api-key` | TMDb API key |

### `organize` subcommand

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

## Running Tests

```bash
pytest
```

## Project Structure

```
src/plex_planner/
    __init__.py
    cli.py                  # CLI entry point (plan + organize subcommands)
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
    dedup.py                # Duplicate MKV detection (metadata fingerprint + perceptual hash)
    cache.py                # File-based JSON cache with TTL (dvdcompare, TMDb)
    disc_provider.py        # dvdcompare.net disc extras metadata bridge
    organizer.py            # Plex destination path builder and file mover
    splitter.py             # Chapter-based MKV splitting via mkvmerge
    tagger.py               # MKV organized tagging via mkvpropedit
tests/
    test_cache.py
    test_config.py
    test_dedup.py
    test_detect.py
    test_disc_provider.py
    test_formatter.py
    test_matcher.py
    test_normalize.py
    test_organizer.py
    test_planner.py
    test_scanner.py
    test_splitter.py
    test_tagger.py
```

## Architecture

The metadata provider is abstracted behind a clean interface (`MetadataProvider`). The default implementation uses TMDb, which is the same source Plex uses for its metadata agents. The provider can be swapped out for TheTVDB or any other source by implementing the interface.

The organize workflow chains several stages: scanning (ffprobe), dedup (metadata fingerprint with perceptual hash confirmation, plus compilation/play-all detection via chapter analysis), TMDb lookup, dvdcompare disc extras lookup, disc-constrained matching (mapping scanned folders to disc numbers via naming heuristics, then matching files to extras by runtime), chapter-to-missing split detection, and finally building Plex-canonical paths and moving files. Comprehensive debug logging captures every decision for post-run analysis.

## Naming Rules

See [plex_naming_rules.md](plex_naming_rules.md) for the full Plex naming reference this tool follows.
