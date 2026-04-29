# CLI Reference

Complete reference for all plex-planner subcommands and their options.

## Global behavior

- **Interactive by default**: When stdin is a terminal, `organize` and `rip` present numbered lists for ambiguous TMDb matches, dvdcompare release selection, and title confirmation. Pass `--auto` to skip all interactive prompts and use best-guess defaults. Non-TTY environments (piped input, cron jobs) are automatically non-interactive.
- **Dry-run by default**: Both `organize` and `rip` preview changes without acting. Add `--execute` to apply.
- **Logging**: Every `organize` run writes debug logs to the OS temp directory. Add `--verbose` for stderr output.
- **Caching**: dvdcompare responses are cached for 30 days, TMDb for 7 days. Use `--no-cache` to bypass.

## `plan` (deprecated)

> **Deprecated**: `plan` is now an alias for `rip-guide`. Use `rip-guide` instead.

Look up a title on TMDb and output the Plex-canonical folder structure and filenames.

```bash
plex-planner plan <title> [options]
```

All options are identical to `rip-guide`. A deprecation warning is printed to stderr on each invocation.

## `organize`

Scan MakeMKV rip folders, deduplicate, match files to metadata, and move into Plex layout.

```bash
plex-planner organize <folder> [options]
```

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
| `--verbose`, `-v` | Print debug logging to stderr (log file is always written) |
| `--no-cache` | Bypass cached dvdcompare and TMDb responses |
| `--force` | Re-organize files even if already tagged as organized |
| `--json` | Output as JSON |
| `--api-key` | TMDb API key |
| `--snapshot` | Replay from a snapshot JSON file instead of scanning live files |
| `--auto` | Skip interactive prompts, use best-guess defaults |

## `rip-guide`

Show disc contents and recommended rip strategy before ripping. Optionally reads the physical disc via makemkvcon.

```bash
plex-planner rip-guide <title> [options]
```

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

## `rip`

Rip selected titles from a physical disc using makemkvcon. Combines disc analysis, title selection, and optional post-rip organize into a single command.

```bash
plex-planner rip <title> --drive <drive> [options]
```

| Option | Description |
|---|---|
| `title` | Movie or TV show title (auto-detected from volume label if omitted) |
| `--drive` | Drive index (`0`), device (`D:`), or `auto` (default: `auto`) |
| `--year` | Release year |
| `--type` | Force `movie`, `tv`, or `auto` (default: `auto`) |
| `--format` | Disc format filter for dvdcompare (e.g. `Blu-ray 4K`) |
| `--release` | Regional release: 1-based index or name keyword (default: auto-detect) |
| `--output` | Output root directory (or set `PLEX_ROOT` env var, or config) |
| `--titles` | Comma-separated title indices to rip (e.g. `1,2,3`) |
| `--all` | Rip all titles on the disc |
| `--yes`, `-y` | Skip the final rip confirmation prompt |
| `--execute` | Actually rip (default: dry-run preview only) |
| `--auto` | Skip interactive prompts (title, TMDb, release selection), use best-guess defaults |
| `--organize` | Auto-organize ripped files into Plex layout after ripping |
| `--json` | Output rip results as JSON |
| `--verbose`, `-v` | Print debug logging to stderr |
| `--no-cache` | Bypass cached dvdcompare and TMDb responses |
| `--api-key` | TMDb API key |

When neither `--titles` nor `--all` is specified, the command auto-selects titles using disc analysis (skipping play-all compilations, lower-resolution duplicates, and very short titles).

## `snapshot`

Capture MKV metadata to a JSON file for offline replay and debugging.

```bash
plex-planner snapshot <folder> [options]
```

| Option | Description |
|---|---|
| `folder` | Path to a MakeMKV rip folder (required) |
| `-o`, `--output` | Output file path (default: `<folder>.snapshot.json` in current directory) |
