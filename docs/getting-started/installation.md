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
| macOS (Apple Silicon) | `riplex-macos` | `riplex-ui-macos.zip` |
| macOS (Intel) | — | — |

> **Intel Mac users:** GitHub [deprecated their Intel macOS (macos-13) build
> runners](https://github.blog/changelog/2024-09-16-github-actions-macos-13-larger-runner-image-brownout-dates/),
> which were the only way to produce Intel-compatible binaries. Please
> [install with pipx](#option-b-install-with-pipx-recommended) instead — it's
> straightforward and works on any Mac.

### Windows

1. Download `riplex-windows.exe` (and optionally `riplex-ui-windows.exe`)
2. Place them in a folder on your PATH (e.g. `C:\Tools\`)
3. Open a terminal and run `riplex setup`

### macOS

1. Download `riplex-macos` and `riplex-ui-macos.zip` (Apple Silicon only).

    **Intel Mac?** GitHub deprecated the build runners needed to produce Intel
    binaries, so these won't work on your machine.
    Skip to [Option B: Install with pipx](#option-b-install-with-pipx-recommended) instead.

2. For the GUI, unzip the `.zip` and move `riplex-ui.app` to `/Applications/`.

3. **Allow the app to open.** macOS blocks apps from unidentified developers by
   default. The first time you try to open it, you'll see a warning — do **not**
   click "Move to Trash." Instead:

    - **Right-click** (or Control-click) on `riplex-ui.app` → choose **Open** →
      click **Open** in the dialog. macOS remembers this and won't ask again.

    - If that doesn't work, open Terminal and run:
      ```
      xattr -dr com.apple.quarantine /Applications/riplex-ui.app
      ```
      Then open the app normally.

4. For the CLI, make it executable and remove the quarantine flag:
    ```
    chmod +x riplex-macos
    xattr -dr com.apple.quarantine riplex-macos
    ```
    Then run `./riplex-macos setup` to configure.

## Option B: Install with pipx (recommended)

[pipx](https://pipx.pypa.io/) installs Python apps in isolated environments but makes their commands available globally — no venv activation needed. `riplex` and `riplex-ui` just work from any terminal.

### 1. Install Python and pipx

- **Windows**: Download Python from https://www.python.org/downloads/ (**check "Add Python to PATH"**), then:
    ```
    pip install pipx
    pipx ensurepath
    ```
- **macOS**:
    ```
    brew install python pipx
    pipx ensurepath
    ```
- **Linux**:
    ```
    sudo apt install python3 pipx
    pipx ensurepath
    ```

Restart your terminal after `ensurepath` so the new PATH takes effect.

### 2. Install and register MakeMKV

Download MakeMKV from https://www.makemkv.com/ and install it.

Then register it with the free beta key:

1. Get the current beta key from https://forum.makemkv.com/forum/viewtopic.php?f=5&t=1053
2. Open MakeMKV, go to Help > Register, and paste the key

The beta key is updated periodically. Without it, `makemkvcon` (the command-line tool riplex uses) won't function.

### 3. Install riplex

```bash
pipx install "riplex[gui]"
```

This installs both `riplex` (CLI) and `riplex-ui` (GUI) as globally available commands.

> [!TIP]
> To install the CLI only (no GUI), run `pipx install riplex` instead.

### 4. Run setup

```bash
riplex setup
```

The setup wizard will:

1. Ask for your TMDb API key (free at https://www.themoviedb.org/settings/api)

    > [!TIP]
    > TMDb asks for an app name and URL when you request a key. You can just
    > enter "riplex" as the app name and `https://github.com/AnyCredit5518/riplex`
    > as the URL. The rest of the form can be filled with basic info - it doesn't
    > need to be a real business. The key is approved instantly.

2. Ask where your Plex library and MakeMKV rip folders are
3. Check for required tools (MakeMKV, ffprobe, mkvmerge, mkvpropedit)
4. Offer to install any missing tools for you (via winget on Windows, Homebrew on macOS, or apt on Linux)

If you skip setup, it runs automatically the first time you use any command.

### 5. Verify

```bash
riplex --help
riplex-ui
```

Both commands should work from any terminal without activating anything.

### Updating

```bash
pipx upgrade riplex
```

## Installing from source (for developers)

If you want to contribute or run the latest unreleased code, use a venv:

```bash
git clone https://github.com/AnyCredit5518/riplex.git
cd riplex
python3.12 -m venv .venv
source .venv/bin/activate   # macOS/Linux
pip install -e ".[dev,gui]"
```

> [!NOTE]
> With a venv, `riplex` and `riplex-ui` only work while the venv is activated.
> For a global install that works from any terminal, use
> [pipx](#option-b-install-with-pipx-recommended) instead.

The repo's `.vscode/settings.json` points VS Code at `.venv` automatically, so
the integrated terminal activates it on open. In any external terminal, run
`source .venv/bin/activate` first.

Then launch the GUI with:

```bash
riplex-ui
```

### macOS SSL fix (Homebrew Python only)

If you installed Python via Homebrew and `riplex-ui` crashes on first launch with
an SSL certificate error, run this one-time fix:

```bash
CERT=$(python3.12 -c "import certifi; print(certifi.where())")
echo "export SSL_CERT_FILE=\"$CERT\"" >> .venv/bin/activate
echo "export REQUESTS_CA_BUNDLE=\"$CERT\"" >> .venv/bin/activate
source .venv/bin/activate
```

### macOS folder picker (Homebrew Python only)

The browse buttons in the GUI use tkinter, which Homebrew ships separately:

```bash
brew install python-tk@3.12
```

Without this, clicking a browse button shows a hint to type the path manually instead.

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
