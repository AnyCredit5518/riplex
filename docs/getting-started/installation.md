# Installation

## Requirements

- Python 3.11+
- A TMDb API key (free at <https://www.themoviedb.org/settings/api>)
- ffprobe (from ffmpeg, required for `organize` mode)
- mkvmerge (from MKVToolNix, required for chapter splitting in `organize` mode)
- mkvpropedit (from MKVToolNix, required for organized tagging in `organize` mode)
- [dvdcompare-scraper](https://github.com/OWNER/dvdcompare-scraper) (sibling project, required for `organize` and `rip-guide` modes)

## Install from source

```bash
cd Projects/plex-planner
pip install -e ".[dev]"
```

This installs the `plex-planner` CLI command and all dependencies including test tooling.

## Verify installation

```bash
plex-planner --help
```

You should see the four subcommands: `plan`, `organize`, `rip-guide`, and `snapshot`.

## External tools

### ffprobe / ffmpeg

Download from <https://ffmpeg.org/download.html> and ensure `ffprobe` is on your PATH.

On Windows, you can verify with:

```powershell
ffprobe -version
```

### MKVToolNix

Download from <https://mkvtoolnix.download/downloads.html>. The installer adds `mkvmerge` and `mkvpropedit` to your PATH automatically.

On Windows, the default install location is `C:\Program Files\MKVToolNix\`.
