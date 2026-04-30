# plex-planner

A tool for planning and organizing MakeMKV disc rips into Plex-compatible folder structures.

Given a movie or TV show title, plex-planner looks up canonical metadata (title, year, type, episodes, runtimes) and outputs the exact folder structure, filenames, and runtimes that Plex expects. It can also scan MakeMKV rip folders, detect duplicates, look up disc extras metadata from dvdcompare.net, match ripped files to their correct identities by runtime, and move everything into the right Plex folder layout.

## What it does

plex-planner has four commands, each targeting a different stage of the disc ripping workflow:

| Command | Stage | What it does |
|---|---|---|
| [`orchestrate`](guide/orchestrate.md) | Full pipeline | Multi-disc rip-then-organize in one session |
| [`rip`](reference/cli.md#rip) | Ripping | Single-disc rip via makemkvcon with auto title selection |
| [`organize`](guide/organize.md) | After ripping | Scans MKV files, deduplicates, matches by runtime, moves into Plex layout |
| [`lookup`](guide/lookup.md) | Before ripping | Shows disc contents from dvdcompare, recommends which titles to rip, creates folder structure |

## Quick start

```bash
# Install
pip install -e ".[dev]"

# See what's on a disc set before ripping
plex-planner lookup "Frozen Planet II"

# After ripping, organize into Plex structure (dry-run by default)
plex-planner organize path/to/rips/Oppenheimer

# Actually move the files
plex-planner organize path/to/rips/Oppenheimer --execute
```

See [Installation](getting-started/installation.md) for full setup instructions.

## Features

- **TMDb integration**: Identifies movies vs TV shows, gets canonical titles, episode lists, and runtimes
- **dvdcompare.net integration**: Looks up disc contents (featurettes, interviews, deleted scenes, trailers) with per-feature runtimes
- **Duplicate detection**: Removes duplicate MKV rips using metadata fingerprinting and perceptual hashing
- **Play-all handling**: Detects and removes compilation files; splits play-all files by chapters when needed
- **Runtime matching**: Matches ripped files to their correct identity by comparing durations against known runtimes
- **Disc-aware matching**: Maps rip folders to disc numbers, constraining matches to the correct disc
- **Chapter splitting**: Splits multi-episode files by chapters using mkvmerge
- **Batch mode**: Process multiple titles at once from a parent folder
- **Pre-rip guidance**: Shows disc contents and recommends which titles to rip vs skip
- **Dry-run by default**: Preview all changes before committing; `--execute` to apply
- **Snapshot replay**: Capture and replay organize workflows from JSON metadata snapshots
- **Caching**: File-based JSON caching for dvdcompare (30-day TTL) and TMDb (7-day TTL) responses
