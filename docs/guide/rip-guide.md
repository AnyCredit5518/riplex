# Rip Guide

The `rip-guide` command shows disc contents and recommended rip strategy *before* you start ripping in MakeMKV. It looks up TMDb for the canonical title and year, then queries dvdcompare.net for the full disc breakdown.

## Basic usage

```bash
plex-planner rip-guide "Frozen Planet II"
```

Output:

```
Frozen Planet II (2022) [TV Show]
============================================================

Recommended rip folder structure:
  _MakeMKV/Frozen Planet II (2022)/Disc 1/ [Blu-ray 4K] (episodes)
  _MakeMKV/Frozen Planet II (2022)/Disc 2/ [Blu-ray 4K] (episodes + extras)
  _MakeMKV/Frozen Planet II (2022)/Disc 3/ [Blu-ray] (episodes)
  _MakeMKV/Frozen Planet II (2022)/Disc 4/ [Blu-ray] (episodes)

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

## Pre-create folder structure

Add `--create-folders` to create the recommended rip subfolders under your output root:

```bash
plex-planner rip-guide "Blade Runner" --year 1982 --format "Blu-ray 4K" --create-folders
```

This creates folders like `<output_root>/_MakeMKV/Blade Runner (1982)/Disc 1/` through `Disc 8/` so you can point MakeMKV's output at the correct disc subfolder as you rip.

## Movie with extras

```bash
plex-planner rip-guide "Oppenheimer" --year 2023
```

For movies, the guide identifies which disc has the main film vs extras, and labels play-all bonus groups appropriately.

## Play-all tips

The play-all tip is key: instead of ripping 4 individual episode titles per disc (~130 GB), rip one play-all title per disc (~65 GB). plex-planner's chapter-split logic in `organize` handles the rest.

## JSON output

```bash
plex-planner rip-guide "Frozen Planet II" --json
```

## Options

| Option | Description |
|---|---|
| `title` | Movie or TV show title (required) |
| `--year` | Release year |
| `--type` | Force `movie`, `tv`, or `auto` (default: `auto`) |
| `--format` | Disc format filter for dvdcompare (e.g. `Blu-ray 4K`) |
| `--release` | Regional release: 1-based index or name keyword (default: `america`) |
| `--output` | Output root for `--create-folders` (or set `PLEX_ROOT` env var, or config) |
| `--create-folders` | Pre-create the recommended MakeMKV rip folder structure |
| `--json` | Output as JSON |
| `--verbose`, `-v` | Print debug logging to stderr |
| `--no-cache` | Bypass cached dvdcompare and TMDb responses |
| `--api-key` | TMDb API key |
