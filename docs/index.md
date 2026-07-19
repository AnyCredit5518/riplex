# riplex

A tool for planning and organizing MakeMKV disc rips into Plex-compatible folder structures.

Given a movie or TV show title, riplex looks up canonical metadata (title, year, type, episodes, runtimes) and outputs the exact folder structure, filenames, and runtimes that Plex expects. It can also scan MakeMKV rip folders, detect duplicates, look up disc extras metadata from dvdcompare.net, match ripped files to their correct identities by runtime, and move everything into the right Plex folder layout.

## What it does

riplex has four commands, each targeting a different stage of the disc ripping workflow:

| Command | Stage | What it does |
|---|---|---|
| [`orchestrate`](cli-guide/orchestrate.md) | Full pipeline | Multi-disc rip-then-organize in one session |
| [`rip`](reference/cli.md#rip) | Ripping | Single-disc rip via makemkvcon with auto title selection |
| [`organize`](cli-guide/organize.md) | After ripping | Scans MKV files, deduplicates, matches by runtime, moves into Plex layout |
| [`lookup`](cli-guide/lookup.md) | Before ripping | Shows disc contents from dvdcompare, recommends which titles to rip, creates folder structure |

## Quick start

```bash
# Install
pip install -e ".[dev]"

# See what's on a disc set before ripping
riplex lookup "Frozen Planet II"

# After ripping, organize into Plex structure (dry-run by default)
riplex organize path/to/rips/Oppenheimer

# Actually move the files
riplex organize path/to/rips/Oppenheimer --execute
```

See [Installation](getting-started/installation.md) for full setup instructions.

If you prefer the desktop app, see the [GUI Walkthrough](gui-guide/gui-walkthrough.md)
for the main flow with screenshots.

## Features

- **TMDb integration**: Identifies movies vs TV shows, gets canonical titles, episode lists, and runtimes
- **dvdcompare.net integration**: Looks up disc contents (featurettes, interviews, deleted scenes, trailers) with per-feature runtimes
- **Multi-work box sets**: Detects several films (or films plus a TV series) in one release and routes each work to its own Plex destination
- **Multi-season TV**: Rips a complete series season by season, nesting under `Season NN/` with a Season Select step and per-season disc grouping
- **Guided resume**: A session marker records the whole plan, so you can stop after any disc and resume the set later — from any disc
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
- **In-place updates (desktop, Windows)**: Downloads and checksum-verifies new versions, swaps the app in place, and relaunches — no manual re-download
- **Auto-eject (desktop)**: Ejects the disc automatically once a rip finishes
