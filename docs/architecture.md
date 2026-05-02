# Architecture

## Overview

riplex is a Python tool with a CLI and optional GUI, organized as a monorepo with three source packages:

- **`riplex`** (library): All business logic — metadata lookup, disc analysis, matching, organizing, ripping orchestration
- **`riplex_cli`** (CLI): Thin wrapper — argument parsing, terminal formatting, progress bars, interactive prompts
- **`riplex_app`** (GUI): Thin wrapper — Flet-based wizard screens, no business logic

Four commands target different stages of the disc ripping workflow:

- **`orchestrate`**: The primary workflow. Multi-disc rip-then-organize in a single session.
- **`rip`**: Single-disc rip via makemkvcon. Disc analysis, auto title selection, and optional post-rip organize.
- **`organize`**: The file organization pipeline. Scans MKV files, deduplicates, matches by runtime, and moves into Plex folder layout.
- **`lookup`**: TMDb + dvdcompare lookup. Shows disc contents and recommended rip strategy.

## Metadata provider

The metadata provider is abstracted behind a clean interface (`MetadataProvider`). The default implementation uses TMDb, which is the same source Plex uses for its metadata agents. The provider can be swapped out for TheTVDB or any other source by implementing the interface.

## Project structure

```
src/
    riplex/                     # Shared library (all business logic)
        __init__.py
        config.py               # Config file loading and setting resolution
        models.py               # Data models (ScannedFile, PlannedDisc, MatchCandidate, etc.)
        disc/                   # Physical disc interaction
            analysis.py         # Live disc analysis via makemkvcon (title classification, rip recs)
            makemkv.py          # makemkvcon wrapper (disc reading, title ripping, progress parsing)
            provider.py         # dvdcompare.net disc extras metadata bridge
        metadata/               # Metadata lookup
            provider.py         # Abstract provider interface
            planner.py          # TMDb planning orchestrator (builds PlannedMovie / PlannedShow)
            sources/
                tmdb.py         # TMDb API implementation
        lookup.py               # Shared entry point for TMDb + dvdcompare fetch and selection
        manifest.py             # Rip manifest reading (title index → filename mapping)
        title.py                # Title parsing (volume labels, year extraction, normalization)
        normalize.py            # Filename/path normalization and Plex naming
        formatter.py            # Text and JSON output formatters
        matcher.py              # Runtime-based file matching with disc constraints
        scanner.py              # MKV folder scanner (ffprobe-based metadata extraction)
        snapshot.py             # Snapshot capture/load, organized markers, debug directory
        detect.py               # Format auto-detection, title grouping, incomplete file detection
        dedup.py                # Duplicate MKV detection (metadata fingerprint + perceptual hash)
        cache.py                # File-based JSON cache with TTL (dvdcompare, TMDb)
        organizer.py            # Plex destination path builder, file mover, archive helper
        splitter.py             # Chapter-based MKV splitting via mkvmerge
        tagger.py               # MKV organized tagging via mkvpropedit
        ui.py                   # Interactive prompts (multi-select, confirmations, text input)
    riplex_cli/                 # CLI thin wrapper
        __init__.py
        main.py                 # Argparse and command dispatch
        formatting.py           # Terminal formatting, progress bars, logging setup
        commands/
            orchestrate.py      # Multi-disc rip and organize pipeline
            rip.py              # Single-disc rip with smart title selection
            organize.py         # Scan, match, and organize existing MKV rips
            lookup.py           # TMDb + dvdcompare lookup and disc content preview
            setup.py            # Interactive config wizard
    riplex_app/                 # GUI thin wrapper (optional, requires flet)
        __init__.py
        main.py                 # App entry point, screen navigation controller
        screens/
            welcome.py          # Config setup, tool verification, workflow picker
            disc_detection.py   # Drive scanning, disc reading
            metadata.py         # TMDb search and selection
            release.py          # dvdcompare release picker
            selection.py        # Title selection with classify_title
            progress.py         # Rip progress with makemkvcon
            done.py             # Rip results summary
            folder_picker.py    # Folder selection and MKV scan for organize workflow
            organize_preview.py # Organize dry-run plan preview
            organize_done.py    # Organize results summary
tests/
    test_*.py               # One test file per source module
    fixtures/               # makemkvcon output samples for parsing tests
    snapshots/              # MKV metadata snapshots for offline test replay
```

## Key data flow

### Orchestrate mode

```
Physical disc
  -> Drive detection (auto-scan optical drives)
  -> Volume label parsing (title auto-detection)
  -> TMDb API (canonical title lookup, disambiguation)
  -> dvdcompare (disc breakdown, content listings)
  -> Disc selection (interactive or --discs flag)
  -> Per-disc loop:
     -> makemkvcon (disc reading, title analysis)
     -> Disc analysis (classification, rip recommendations)
     -> makemkvcon (title ripping with progress)
     -> Manifest writing (disc metadata snapshot)
  -> Organize pipeline (dedup, match, move, split, tag)
  -> Archive (move rip folder to archive_root, optional)
```

### Rip mode

```
Physical disc
  -> Drive detection + volume label parsing
  -> TMDb API (canonical title lookup)
  -> dvdcompare (disc breakdown)
  -> makemkvcon (disc reading, title analysis)
  -> Disc analysis (classification, rip/skip recommendations)
  -> makemkvcon (title ripping with progress)
  -> Optional: Organize pipeline
```

### Lookup mode

```
User input (title, year)
  -> TMDb API (canonical title lookup)
  -> dvdcompare (disc breakdown, content listings)
  -> CLI (formatted disc guide output with rip recommendations)
```

### Organize mode

```
MakeMKV rip folder
  -> Scanner (ffprobe metadata extraction)
  -> Dedup (duplicate detection and removal)
  -> Detect (play-all detection, format inference, title grouping)
  -> TMDb API (canonical title lookup)
  -> dvdcompare (disc extras metadata)
  -> Matcher (runtime-based file-to-entry matching)
  -> Organizer (destination path builder)
  -> Splitter (chapter-based MKV splitting, if needed)
  -> Tagger (mark files as organized)
  -> Archive (move rip folder to archive_root, optional)
```
