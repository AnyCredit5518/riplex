# CLI Reference

Complete reference for all plex-planner subcommands and their options.

## Global behavior

- **Dry-run by default**: The `organize` command previews changes without moving files. Add `--execute` to apply.
- **Logging**: Every `organize` run writes debug logs to the OS temp directory. Add `--verbose` for stderr output.
- **Caching**: dvdcompare responses are cached for 30 days, TMDb for 7 days. Use `--no-cache` to bypass.

## `plan`

Look up a title on TMDb and output the Plex-canonical folder structure and filenames.

```bash
plex-planner plan <title> [options]
```

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
| `--release` | Regional release: 1-based index or name keyword (default: `america`) |
| `--output` | Output root directory (or set `PLEX_ROOT` env var, or `output_root` in config) |
| `--execute` | Actually move files (default: dry-run preview only) |
| `--unmatched` | Policy for unmatched files: `ignore` (default), `move`, `delete`, or `extras` |
| `--verbose`, `-v` | Print debug logging to stderr (log file is always written) |
| `--no-cache` | Bypass cached dvdcompare and TMDb responses |
| `--force` | Re-organize files even if already tagged as organized |
| `--json` | Output as JSON |
| `--api-key` | TMDb API key |
| `--snapshot` | Replay from a snapshot JSON file instead of scanning live files |

## `rip-guide`

Show disc contents and recommended rip strategy before ripping.

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
| `--output` | Output root for `--create-folders` (or set `PLEX_ROOT` env var, or config) |
| `--create-folders` | Pre-create the recommended MakeMKV rip folder structure |
| `--json` | Output as JSON |
| `--verbose`, `-v` | Print debug logging to stderr |
| `--no-cache` | Bypass cached dvdcompare and TMDb responses |
| `--api-key` | TMDb API key |

## `snapshot`

Capture MKV metadata to a JSON file for offline replay and debugging.

```bash
plex-planner snapshot <folder> [options]
```

| Option | Description |
|---|---|
| `folder` | Path to a MakeMKV rip folder (required) |
| `-o`, `--output` | Output file path (default: `<folder>.snapshot.json` in current directory) |
