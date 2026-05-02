# Installation

There are two ways to install riplex:

- **Download a pre-built executable** (easiest, no Python needed)
- **Install via pip** (for Python users who want automatic updates)

Both methods require the same external tools (MakeMKV, ffprobe, mkvmerge).

## Option A: Pre-built executables

Download the latest release for your platform from the [GitHub Releases page](https://github.com/AnyCredit5518/riplex/releases):

| Platform | CLI | GUI |
|---|---|---|
| Windows | `riplex-windows.exe` | `riplex-ui-windows.exe` |
| macOS | `riplex-macos` | `riplex-ui-macos.zip` |

### Windows

1. Download `riplex-windows.exe` (and optionally `riplex-ui-windows.exe`)
2. Place them in a folder on your PATH (e.g. `C:\Tools\`)
3. Open a terminal and run `riplex setup`

### macOS

1. Download `riplex-macos` and/or `riplex-ui-macos.zip`
2. Make the CLI executable: `chmod +x riplex-macos`
3. For the GUI, unzip `riplex-ui-macos.zip` and move `riplex-ui.app` to `/Applications/`
4. Run `./riplex-macos setup` to configure

## Option B: Install via pip

### 1. Install Python

riplex requires Python 3.11 or newer. If you don't have it:

- **Windows**: Download from https://www.python.org/downloads/ and run the installer. **Check "Add Python to PATH"** during installation.
- **macOS**: `brew install python` or download from https://www.python.org/downloads/
- **Linux**: Most distros include Python. If not: `sudo apt install python3 python3-pip`

To verify, open a terminal (Command Prompt, PowerShell, or Terminal) and run:

```bash
python --version
```

You should see `Python 3.11` or higher.

### 2. Install and register MakeMKV

Download MakeMKV from https://www.makemkv.com/ and install it.

Then register it with the free beta key:

1. Get the current beta key from https://forum.makemkv.com/forum/viewtopic.php?f=5&t=1053
2. Open MakeMKV, go to Help > Register, and paste the key

The beta key is updated periodically. Without it, `makemkvcon` (the command-line tool riplex uses) won't function.

### 3. Install riplex

```bash
pip install riplex
```

This installs the `riplex` command and all Python dependencies automatically.

### 4. Run setup

```bash
riplex setup
```

The setup wizard will:

1. Ask for your TMDb API key (free at https://www.themoviedb.org/settings/api)

    !!! tip "Getting a TMDb API key"
        TMDb asks for an app name and URL when you request a key. You can just
        enter "riplex" as the app name and `https://github.com/AnyCredit5518/riplex`
        as the URL. The rest of the form can be filled with basic info — it doesn't
        need to be a real business. The key is approved instantly.

2. Ask where your Plex library and MakeMKV rip folders are
3. Check for required tools (MakeMKV, ffprobe, mkvmerge, mkvpropedit)
4. Offer to install any missing tools for you (via winget on Windows, Homebrew on macOS, or apt on Linux)

If you skip setup, it runs automatically the first time you use any command.

### 5. Verify

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

To also install the Flet-based GUI:

```bash
pip install -e ".[dev,gui]"
```

Then launch it with:

```bash
riplex-ui
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

- **Windows**: `winget install MoritzBunkus.MKVToolNix` (or download from https://mkvtoolnix.download/)
- **macOS**: `brew install mkvtoolnix`
- **Linux**: `sudo apt install mkvtoolnix`
