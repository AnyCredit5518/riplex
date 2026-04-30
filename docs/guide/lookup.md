# Lookup

The `lookup` command shows disc contents and recommended rip strategy *before* you start ripping in MakeMKV. It looks up TMDb for the canonical title and year, then queries dvdcompare.net for the full disc breakdown.

## Basic usage

```bash
plex-planner lookup "Frozen Planet II"
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
plex-planner lookup "Blade Runner" --year 1982 --format "Blu-ray 4K" --create-folders
```

This creates folders like `<output_root>/_MakeMKV/Blade Runner (1982)/Disc 1/` through `Disc 8/` so you can point MakeMKV's output at the correct disc subfolder as you rip.

## Movie with extras

```bash
plex-planner lookup "Oppenheimer" --year 2023
```

For movies, the guide identifies which disc has the main film vs extras, and labels play-all bonus groups appropriately.

## Play-all tips

The play-all tip is key: instead of ripping 4 individual episode titles per disc (~130 GB), rip one play-all title per disc (~65 GB). plex-planner's chapter-split logic in `organize` handles the rest.

## JSON output

```bash
plex-planner lookup "Frozen Planet II" --json
```

When combined with `--drive`, the JSON includes a `disc_analysis` object with per-title recommendations:

```bash
plex-planner lookup "Frozen Planet II" --drive 0 --json
```

## Live disc analysis

Add `--drive` to read the physical disc in real time via makemkvcon and cross-reference its titles against dvdcompare metadata.

```bash
plex-planner lookup "Frozen Planet II" --drive 0
```

The `--drive` flag accepts:

- A drive index: `--drive 0`
- A device name: `--drive D:`
- Auto-detect: `--drive auto` (uses the first drive with a disc inserted)

This appends a title-by-title analysis table after the dvdcompare guide:

```
============================================================
Live disc analysis: Frozen Planet II - Disc 2
============================================================

    #   Duration      Size        Res   Ch  Recommendation
  ---  ---------  --------  ---------  ---  ----------------------------------------
    0      50:25   12.0 GB  1920x1080    5  Play-all (1080p) - skip (individual 4K titles available)
    1      52:20   22.7 GB  3840x2160    6  Frozen Worlds (4K) - rip this
    2      52:06   21.2 GB  3840x2160    6  Frozen Ocean (4K) - rip this
    3      51:53   19.7 GB  3840x2160    6  Frozen Peaks (4K) - rip this
    4    2:36:21   63.6 GB  3840x2160   18  Play-all (4K, 18 ch, 3 segments) - skip (rip #1, #2, #3 individually)

  Rip titles: 1, 2, 3 (63.6 GB total)
  Skip titles: 0, 4
```

Each title is classified as one of:

- **MAIN FILM**: runtime matches TMDb within 60 seconds (movies only)
- **Named episode/extra**: duration-matched to a dvdcompare entry within 30 seconds
- **Play-all**: duration matches the sum of other titles at the same resolution, or the dvdcompare total
- **Episode**: substantial title on a multi-title disc (no dvdcompare match)
- **Very short**: under 2 minutes, likely a menu or intro
- **Unknown content**: fallback for unrecognized titles

The summary line lists recommended rip/skip title indices with total size.

### Requirements

- [MakeMKV](https://www.makemkv.com/) must be installed. `makemkvcon` is located automatically from PATH or standard install paths.
- Close the MakeMKV GUI before using `--drive`, as only one process can access the drive at a time.

## Options

| Option | Description |
|---|---|
| `title` | Movie or TV show title (required) |
| `--year` | Release year |
| `--type` | Force `movie`, `tv`, or `auto` (default: `auto`) |
| `--format` | Disc format filter for dvdcompare (e.g. `Blu-ray 4K`) |
| `--release` | Regional release: 1-based index or name keyword (default: `america`) |
| `--drive` | Read live disc info: drive index (`0`), device (`D:`), or `auto` |
| `--output` | Output root for `--create-folders` (or set `PLEX_ROOT` env var, or config) |
| `--create-folders` | Pre-create the recommended MakeMKV rip folder structure |
| `--json` | Output as JSON (includes `disc_analysis` when `--drive` is also set) |
| `--verbose`, `-v` | Print debug logging to stderr |
| `--no-cache` | Bypass cached dvdcompare and TMDb responses |
| `--api-key` | TMDb API key |
