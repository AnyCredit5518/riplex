# Architecture

## Overview

plex-planner is a Python CLI application with six modes, each targeting a different stage of the disc ripping workflow:

- **`orchestrate`**: The primary workflow. Multi-disc rip-then-organize in a single session. Combines disc detection, dvdcompare lookup, disc selection, ripping, and organizing.
- **`rip`**: Single-disc rip via makemkvcon. Disc analysis, auto title selection, and optional post-rip organize.
- **`organize`**: The file organization pipeline. Scans MKV files, deduplicates, looks up TMDb + dvdcompare, matches files by runtime, and moves everything into Plex folder layout.
- **`rip-guide`**: TMDb + dvdcompare lookup. Shows disc contents and recommended rip strategy before ripping. Helps users decide which MakeMKV titles to rip vs skip, and creates correct folder structure.
- **`plan`** *(deprecated)*: Alias for `rip-guide`.
- **`snapshot`**: Captures MKV metadata to JSON for offline replay and debugging.

## Metadata provider

The metadata provider is abstracted behind a clean interface (`MetadataProvider`). The default implementation uses TMDb, which is the same source Plex uses for its metadata agents. The provider can be swapped out for TheTVDB or any other source by implementing the interface.

## Project structure

```
src/plex_planner/
    __init__.py
    cli.py                  # CLI entry point (orchestrate, rip, organize, rip-guide, snapshot subcommands)
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

### Plan mode

```
User input (title, year)
  -> TMDb API (via MetadataProvider)
  -> Planner (builds PlannedMovie or PlannedShow)
  -> Formatter (text or JSON output)
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
```

### Rip guide mode

```
User input (title, year)
  -> TMDb API (canonical title lookup)
  -> dvdcompare (disc breakdown)
  -> CLI (formatted disc guide output)
```
