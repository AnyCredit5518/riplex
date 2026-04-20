# Architecture

## Overview

plex-planner is a Python CLI application with four modes, each targeting a different stage of the disc ripping workflow:

- **`plan`**: TMDb lookup only. Outputs Plex-canonical folder structure and filenames.
- **`rip-guide`**: TMDb + dvdcompare lookup. Shows disc contents and recommended rip strategy before ripping. Helps users decide which MakeMKV titles to rip vs skip, and creates correct folder structure.
- **`organize`**: The full pipeline. Scans MKV files, deduplicates, looks up TMDb + dvdcompare, matches files by runtime, and moves everything into Plex folder layout.
- **`snapshot`**: Captures MKV metadata to JSON for offline replay and debugging.

## Metadata provider

The metadata provider is abstracted behind a clean interface (`MetadataProvider`). The default implementation uses TMDb, which is the same source Plex uses for its metadata agents. The provider can be swapped out for TheTVDB or any other source by implementing the interface.

## Project structure

```
src/plex_planner/
    __init__.py
    cli.py                  # CLI entry point (plan, organize, rip-guide, snapshot subcommands)
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
    organizer.py            # Plex destination path builder and file mover
    splitter.py             # Chapter-based MKV splitting via mkvmerge
    tagger.py               # MKV organized tagging via mkvpropedit
tests/
    test_cache.py
    test_cli_utils.py
    test_config.py
    test_dedup.py
    test_detect.py
    test_disc_provider.py
    test_formatter.py
    test_matcher.py
    test_normalize.py
    test_organizer.py
    test_planner.py
    test_rip_guide.py
    test_scanner.py
    test_splitter.py
    test_tagger.py
    snapshots/              # MKV metadata snapshots for offline test replay
```

## Key data flow

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
