# riplex

Automatically organizes MKV files from physical disc collections into Plex-compatible folder structures with the right names, the right folders, and no manual work.

## Desktop App

If you'd rather use a simple graphical interface instead of the command line, download the pre-built app from the [Releases page](https://github.com/AnyCredit5518/riplex/releases/latest):

- **Windows**: Download `riplex-ui-windows.exe` and double-click to run
- **macOS** (Apple Silicon): Download `riplex-ui-macos.zip`, unzip, and open `riplex-ui.app`
- **macOS** (Intel): [Install with pipx](docs/getting-started/installation.md#option-b-install-with-pipx-recommended) — GitHub [deprecated their Intel macOS build runners](https://github.blog/changelog/2024-09-16-github-actions-macos-13-larger-runner-image-brownout-dates/), so pre-built Intel binaries are no longer possible

No Python install required. The app walks you through setup and provides buttons for all workflows.

---

## Why?

After using MakeMKV to back up a disc, you're left with a pile of generically-named files (`title_t00.mkv`, `title_t01.mkv`, ...) and no idea which is the main film, which are featurettes, which are duplicates, and which is the play-all compilation you didn't need. For a multi-disc TV series, you're looking at hours of manual effort: reading disc cases, Googling runtimes, renaming files one by one, and building the exact folder hierarchy Plex demands.

riplex solves this by pulling metadata from TMDb (canonical titles, years, episode info) and [dvdcompare.net](https://www.dvdcompare.net) (per-disc content breakdowns — featurettes, deleted scenes, runtimes), then automatically classifying, deduplicating, matching, renaming, and organizing everything into the correct Plex structure.

## What it does

| Command | What it does |
|---|---|
| `orchestrate` | Full pipeline: detect a disc, look up metadata, select titles, hand off to MakeMKV for disc backup, and organize into Plex folders. Multi-disc with swap prompts. |
| `organize` | Scan existing MKV files, deduplicate, match to metadata by runtime, move into Plex layout. |
| `lookup` | Preview disc contents and see what's on each disc before doing anything. |

## Quick Start

### Install

```bash
pip install riplex
```

Then run the setup wizard:

```bash
riplex setup
```

This walks you through creating your config file (TMDb API key, output paths) and checks that required tools are on PATH. If anything is missing, it offers to install it for you. It also runs automatically the first time you use any command.

For detailed installation instructions (including how to install Python if you don't have it), see the [Getting Started guide](docs/getting-started/installation.md).

### Orchestrate (full pipeline)

Insert a disc and run:

```bash
riplex orchestrate --execute
```

riplex auto-detects the title from the volume label, looks up metadata, shows you what's on each disc, hands off to MakeMKV for disc backup, and organizes everything into Plex folders.

### Unattended mode

```bash
riplex orchestrate --execute --auto
```

Skips all prompts, uses best-guess defaults. Good for scripted or scheduled runs.

### Organize existing files

Already have MKV files from MakeMKV? Point `organize` at the folder:

```bash
riplex organize path/to/MyMovie --execute
```

## Requirements

- Python 3.11+
- [TMDb API key](https://www.themoviedb.org/settings/api) (free)
- [MakeMKV](https://www.makemkv.com/) with `makemkvcon` on PATH
- [ffmpeg](https://ffmpeg.org/) (`ffprobe`) for metadata extraction
- [MKVToolNix](https://mkvtoolnix.download/) (`mkvmerge`, `mkvpropedit`) for chapter splitting and tagging

`riplex setup` detects missing tools and offers to install them automatically via winget (Windows), Homebrew (macOS), or apt (Linux).

## Platform Support

riplex works on Windows, macOS, and Linux. All path handling, caching, and config locations follow OS conventions automatically.

## Data Sources

- **[TMDb](https://www.themoviedb.org/)**: Canonical movie and TV show metadata (titles, years, episodes, runtimes). Requires a free API key.
- **[dvdcompare.net](https://www.dvdcompare.net)**: Per-disc content breakdowns for physical media releases (featurettes, deleted scenes, interviews, runtimes, play-all groupings). An invaluable resource for the disc collecting community.

## Related Projects

- **[dvdcompare-scraper](https://github.com/AnyCredit5518/dvdcompare-scraper)**: Python client for looking up disc content metadata from [dvdcompare.net](https://www.dvdcompare.net). Powers riplex's disc content lookup. Contributions welcome.

## Documentation

Full documentation is in the [docs/](docs/) folder:

- [Getting Started](docs/getting-started/installation.md): installation, configuration
- [User Guide](docs/guide/workflow.md): workflows, command-by-command guides
- [CLI Reference](docs/reference/cli.md): all options for all commands
- [Architecture](docs/architecture.md): design, data flow, project structure

## License

MIT
