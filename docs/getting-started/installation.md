# Installation

## 1. Install Python

riplex requires Python 3.11 or newer. If you don't have it:

- **Windows**: Download from https://www.python.org/downloads/ and run the installer. **Check "Add Python to PATH"** during installation.
- **macOS**: `brew install python` or download from https://www.python.org/downloads/
- **Linux**: Most distros include Python. If not: `sudo apt install python3 python3-pip`

To verify, open a terminal (Command Prompt, PowerShell, or Terminal) and run:

```bash
python --version
```

You should see `Python 3.11` or higher.

## 2. Install riplex

```bash
pip install riplex
```

This installs the `riplex` command and all Python dependencies automatically.

## 3. Run setup

```bash
riplex setup
```

The setup wizard will:

1. Ask for your TMDb API key (free at https://www.themoviedb.org/settings/api)
2. Ask where your Plex library and MakeMKV rip folders are
3. Check for required tools (MakeMKV, ffprobe, mkvmerge, mkvpropedit)
4. Offer to install any missing tools for you (via winget on Windows, Homebrew on macOS, or apt on Linux)

If you skip setup, it runs automatically the first time you use any command.

## 4. Verify

```bash
riplex --help
```

You should see the subcommands: `orchestrate`, `rip`, `organize`, `lookup`, and `setup`.

## Installing from source (for developers)

If you want to contribute or run the latest unreleased code:

```bash
git clone https://github.com/AnyCredit5518/riplex.git
cd riplex
pip install -e ".[dev]"
```

## External tools

riplex uses these tools under the hood. The setup wizard handles installation, but if you prefer to install manually:

### MakeMKV

Download from https://www.makemkv.com/. Ensure `makemkvcon` is on your PATH.

- Windows default location: `C:\Program Files (x86)\MakeMKV\`
- macOS: The app bundle includes makemkvcon

MakeMKV requires a registration key. A free beta key is available at https://forum.makemkv.com/forum/viewtopic.php?f=5&t=1053 and must be entered in MakeMKV (Help > Register) before `makemkvcon` will work. The beta key is updated periodically.

### ffprobe (from ffmpeg)

- **Windows**: `winget install Gyan.FFmpeg`
- **macOS**: `brew install ffmpeg`
- **Linux**: `sudo apt install ffmpeg`

### MKVToolNix (mkvmerge, mkvpropedit)

- **Windows**: `winget install MKVToolNix.MKVToolNix` (or download from https://mkvtoolnix.download/)
- **macOS**: `brew install mkvtoolnix`
- **Linux**: `sudo apt install mkvtoolnix`
