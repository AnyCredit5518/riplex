# riplex

Rip a disc, get a Plex-ready folder. No renaming, no guessing which `title_t07.mkv` is the main feature.

![Rip flow demo](screenshots/0_Rip_Flow_BTTF.gif)

## Why?

After MakeMKV finishes with a disc, you're left with a pile of files named `title_t00.mkv`, `title_t01.mkv`, ... — and no idea which is the main feature, which are featurettes, which are duplicates, and which is the play-all compilation you didn't want. Multi-disc box sets multiply the pain.

riplex automates the rest of the job:

- Reads the disc and identifies the title from the volume label
- Looks up canonical metadata from [TMDb](https://www.themoviedb.org/) and per-disc content breakdowns from [dvdcompare.net](https://www.dvdcompare.net)
- Classifies every title (main feature, episode, featurette, play-all, duplicate, junk) and picks what's worth ripping
- Hands off to MakeMKV, then renames and files everything into the exact Plex folder structure

## Get started

### Desktop app (recommended)

Download the latest release from the [Releases page](https://github.com/AnyCredit5518/riplex/releases/latest):

- **Windows** — `riplex-ui-windows.exe`, double-click to run
- **macOS** (Apple Silicon) — `riplex-ui-macos.zip`, unzip, open `riplex-ui.app`
- **macOS** (Intel) / **Linux** — [install with pipx](docs/getting-started/installation.md#option-b-install-with-pipx-recommended)

The app walks you through setup on first launch (TMDb key, paths, missing tools).

### Command line

For scripted runs, headless servers, or if you just prefer a terminal:

```bash
pipx install "riplex[gui]"
riplex setup
riplex orchestrate --execute
```

Full CLI reference: [docs/reference/cli.md](docs/reference/cli.md).

## What it looks like

**Multi-disc box sets** — riplex understands that a "Back to the Future Trilogy" Blu-ray set is six physical discs and walks you through ripping each one:

![Multi-disc overview](screenshots/5_Multi_Disc_Overview_BTTF.png)

More screenshots: [welcome](screenshots/1_Welcome_Screen.png), [disc detection](screenshots/2_Disc_Detection_BTTF.png), [metadata lookup](screenshots/3_Metadata_Lookup_BTTF.png), [release picker](screenshots/4_Disc_Release_BTTF.png), [title selection](screenshots/5_Select_Title_to_RIP_BTTF.png).

## Requirements

riplex uses MakeMKV, ffmpeg, and MKVToolNix under the hood. The setup wizard installs them for you on Windows (winget), macOS (Homebrew), and Debian/Ubuntu Linux (apt). On other platforms see [the installation guide](docs/getting-started/installation.md).

You'll also need a free [TMDb API key](https://www.themoviedb.org/settings/api) — the wizard prompts you for it.

## Data sources

- **[TMDb](https://www.themoviedb.org/)** — canonical movie and TV metadata (titles, years, episodes, runtimes)
- **[dvdcompare.net](https://www.dvdcompare.net)** — per-disc content breakdowns (featurettes, deleted scenes, play-all groupings, runtimes). An invaluable community resource

## Related projects

- **[dvdcompare-scraper](https://github.com/AnyCredit5518/dvdcompare-scraper)** — Python client for dvdcompare.net. Powers riplex's disc lookup. Contributions welcome.

## Documentation

- [Getting started](docs/getting-started/installation.md) — installation, configuration
- [User guide](docs/guide/workflow.md) — end-to-end workflows
- [CLI reference](docs/reference/cli.md) — every command and flag
- [Architecture](docs/architecture.md) — design, data flow, project structure

## License

MIT
