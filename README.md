# riplex

Automates the tedious manual work around MakeMKV: figuring out what to rip, which MKV files are actually what, and organizing everything into Plex-compatible folder structures.

## Why?

MakeMKV is great at one thing: reading a disc and dumping raw MKV files. But that's where its job ends and yours begins.

You're left with a pile of generically-named files (`title_t00.mkv`, `title_t01.mkv`, ...) and no idea which is the main film, which are featurettes, which are duplicates, and which is the play-all compilation you didn't need. For a multi-disc TV series, you're looking at hours of manual effort: reading disc cases, Googling runtimes, renaming files one by one, and building the exact folder hierarchy Plex demands.

We identified the best sources of disc metadata (TMDb for canonical titles and episode info, dvdcompare.net for per-disc content breakdowns) and automated the entire pipeline. riplex pulls that data, figures out what's on every disc in a release, tells you exactly which MakeMKV titles to rip (and which to skip), then matches, renames, deduplicates, splits, and organizes everything into the correct Plex structure automatically.

## What it does

| Command | What it does |
|---|---|
| `orchestrate` | Full pipeline: insert a disc, riplex handles detection, metadata lookup, ripping, and organizing. Multi-disc with swap prompts. |
| `rip` | Single-disc rip with smart title selection (skips play-alls, duplicates, junk). |
| `organize` | Scan existing MKV rips, deduplicate, match to metadata by runtime, move into Plex layout. |
| `lookup` | Preview disc contents and recommended rip strategy before touching MakeMKV. |

## Quick Start

### Install

```bash
pip install -e ".[dev]"
```

### Configure

Create a config file at `%APPDATA%\riplex\config.toml` (Windows) or `~/.config/riplex/config.toml`:

```toml
tmdb_api_key = "your_key_here"
output_root = "E:/Media"
rip_output = "E:/Media/Rips"
```

Get a free TMDb API key at https://www.themoviedb.org/settings/api.

### Rip a disc (interactive)

Insert a disc and run:

```bash
riplex orchestrate --execute
```

riplex auto-detects the title from the volume label, looks up disc metadata, shows you what's on each disc, lets you choose which to rip, and organizes everything into Plex folders when done.

### Rip a disc (unattended)

```bash
riplex orchestrate --execute --auto
```

Skips all prompts, uses best-guess defaults. Good for scripted or scheduled runs.

### Organize existing rips

Already ripped with MakeMKV manually? Point `organize` at the folder:

```bash
riplex organize path/to/rips/Oppenheimer --execute
```

## Requirements

- Python 3.11+
- [TMDb API key](https://www.themoviedb.org/settings/api) (free)
- [MakeMKV](https://www.makemkv.com/) with `makemkvcon` on PATH
- [ffmpeg](https://ffmpeg.org/) (`ffprobe`) for metadata extraction
- [MKVToolNix](https://mkvtoolnix.download/) (`mkvmerge`, `mkvpropedit`) for chapter splitting and tagging

## Related Projects

- **[dvdcompare-scraper](https://github.com/AnyCredit5518/dvdcompare-scraper)**: Scrapes per-disc content metadata from dvdcompare.net (featurettes, interviews, deleted scenes, runtimes). Required dependency that powers riplex's disc content lookup. Contributions welcome.

## Documentation

Full documentation is in the [docs/](docs/) folder:

- [Getting Started](docs/getting-started/installation.md): installation, configuration
- [User Guide](docs/guide/workflow.md): workflows, command-by-command guides
- [CLI Reference](docs/reference/cli.md): all options for all commands
- [Architecture](docs/architecture.md): design, data flow, project structure

## License

MIT
