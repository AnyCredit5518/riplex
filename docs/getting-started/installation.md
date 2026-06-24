# Installation

## Installing riplex

There are three ways to install riplex:

- **[Pre-built executables](#option-a-pre-built-executables)** — fastest
  way to try riplex. No Python required, but upgrades mean re-downloading.
- **[pipx](#option-b-install-with-pipx-recommended)** — recommended.
  Requires Python, but `pipx upgrade riplex` makes staying current effortless.
- **[From source](#option-c-install-from-source)** — for developers and
  platforms without a pre-built binary (Intel Mac, Linux).

### Option A: Pre-built executables

Download the latest release for your platform from the
[GitHub Releases page](https://github.com/AnyCredit5518/riplex/releases).

#### Windows

**GUI only (easiest):**

1. Download `riplex-ui-windows.exe`
2. Move it wherever you keep apps (e.g. `C:\Program Files\riplex\`)
3. Double-click to run. Windows SmartScreen may warn you because the app
   isn't code-signed -- click **More info** then **Run anyway**.
4. Optionally, right-click the `.exe` and select **Create shortcut** to add
   it to your desktop or Start menu.

**CLI (for terminal users):**

1. Download `riplex-windows.exe`
2. Rename it to `riplex.exe`
3. Move it to a folder of your choice (e.g. `C:\Program Files\riplex\`)
4. Add that folder to your system PATH:
    - Open **Settings** > **System** > **About** > **Advanced system settings**
    - Click **Environment Variables**
    - Under **User variables**, select **Path** and click **Edit**
    - Click **New** and paste the folder path (e.g. `C:\Program Files\riplex\`)
    - Click **OK** on all dialogs
5. Open a **new** terminal and run `riplex setup`

> [!TIP]
> You can install both. The GUI includes built-in setup, so you don't need
> the CLI unless you prefer working in a terminal.

#### macOS (Apple Silicon only)

> **Intel Mac?** Pre-built binaries aren't available for Intel Macs. GitHub
> [deprecated their Intel macOS build runners](https://github.blog/changelog/2024-09-16-github-actions-macos-13-larger-runner-image-brownout-dates/).
> Use [Option B: Install with pipx](#option-b-install-with-pipx-recommended)
> instead, which works on any Mac.

**GUI:**

1. Download `riplex-ui-macos.zip`
2. Unzip it and move `riplex-ui.app` to `/Applications/`
3. **Allow the app to open.** macOS blocks apps from unidentified developers.
   The first time you open it, you'll see a warning -- do **not** click
   "Move to Trash." Instead:

    - **Right-click** (or Control-click) `riplex-ui.app`, choose **Open**,
      then click **Open** in the dialog. macOS remembers this and won't ask
      again.

    - If that doesn't work, open Terminal and run:
      ```
      xattr -dr com.apple.quarantine /Applications/riplex-ui.app
      ```

**CLI:**

1. Download `riplex-macos`
2. Open Terminal and run:
    ```
    mv ~/Downloads/riplex-macos /usr/local/bin/riplex
    chmod +x /usr/local/bin/riplex
    xattr -dr com.apple.quarantine /usr/local/bin/riplex
    ```
3. Run `riplex setup`

#### Linux

Pre-built executables are not currently available for Linux. Use
[Option B: Install with pipx](#option-b-install-with-pipx-recommended)
instead.

### Option B: Install with pipx (recommended)

[pipx](https://pipx.pypa.io/) installs Python apps in isolated environments
but makes their commands available globally. No venv activation needed --
`riplex` and `riplex-ui` just work from any terminal.

#### 1. Install Python and pipx

**Windows:**

Download Python from https://www.python.org/downloads/ and run the installer.
**Check "Add Python to PATH"** at the bottom of the first screen. Then open
a terminal and run:

```
pip install pipx
pipx ensurepath
```

**macOS:**

```
brew install python pipx
pipx ensurepath
```

**Linux (Debian, Ubuntu, Mint, Pop!_OS, etc.):**

```
sudo apt install python3 pipx
pipx ensurepath
```

**Linux (Bazzite, Fedora Silverblue, and other immutable distros):**

Python and pipx aren't available via `apt` on immutable distros. Layer them
with `rpm-ostree`:

```
rpm-ostree install python3 python3-pip
```

Then reboot and run:

```
pip install --user pipx
pipx ensurepath
```

Restart your terminal after `ensurepath` so the new PATH takes effect.

#### 2. Install riplex

```bash
pipx install "riplex[gui]"
```

This installs both `riplex` (CLI) and `riplex-ui` (GUI) as globally available
commands.

> [!TIP]
> To install the CLI only (no GUI), run `pipx install riplex` instead.

#### Updating

```bash
pipx upgrade riplex
```

### Option C: Install from source

For developers who want to contribute or run the latest unreleased code.

#### 1. Clone the repository

```bash
git clone https://github.com/AnyCredit5518/riplex.git
cd riplex
```

#### 2. Create and activate a virtual environment

**Windows:**

```
py -m venv .venv
.venv\Scripts\activate
```

**macOS / Linux:**

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

#### 3. Install in development mode

```bash
pip install -e ".[dev,gui]"
```

> [!NOTE]
> With a venv, `riplex` and `riplex-ui` only work while the venv is
> activated. For a global install that works from any terminal, use
> [pipx](#option-b-install-with-pipx-recommended) instead.

> [!TIP]
> The repo's `.vscode/settings.json` points VS Code at `.venv`
> automatically, so the integrated terminal activates it on open.

#### macOS SSL fix (Homebrew Python only)

If you installed Python via Homebrew and `riplex-ui` crashes on first launch
with an SSL certificate error, run this one-time fix:

```bash
CERT=$(python3.12 -c "import certifi; print(certifi.where())")
echo "export SSL_CERT_FILE=\"$CERT\"" >> .venv/bin/activate
echo "export REQUESTS_CA_BUNDLE=\"$CERT\"" >> .venv/bin/activate
source .venv/bin/activate
```

#### GUI folder picker (tkinter)

The browse buttons in the GUI use tkinter, which some platforms don't include
by default. Without it, the browse buttons show a hint to type the path
manually instead.

- **macOS (Homebrew):** `brew install python-tk@3.12`
- **Linux (Debian/Ubuntu):** `sudo apt install python3-tk`

## Setup

After installing, run the setup wizard. You can do this from the CLI:

```bash
riplex setup
```

Or just launch the GUI -- it checks for missing tools on startup and walks you
through setup automatically.

If you want to preview the desktop flow before ripping a disc, see the
[GUI Walkthrough](../gui-guide/gui-walkthrough.md).

If you prefer the terminal workflow after setup, see the
[CLI Workflow guide](../cli-guide/workflow.md).

The setup wizard will:

1. Ask for your TMDb API key (free at https://www.themoviedb.org/settings/api)

    > [!TIP]
    > TMDb asks for an app name and URL when you request a key. You can just
    > enter "riplex" as the app name and `https://github.com/AnyCredit5518/riplex`
    > as the URL. The rest of the form can be filled with basic info -- it
    > doesn't need to be a real business. The key is approved instantly.
    >
    > The settings page offers both an **API Key** (v3) and an **API Read
    > Access Token** (v4). riplex accepts either one.

2. Ask where your Plex library and MakeMKV rip folders are
3. Check for required tools (MakeMKV, ffprobe, mkvmerge, mkvpropedit)
4. Offer to install any missing tools automatically (via winget on Windows,
   Homebrew on macOS, or apt on Debian/Ubuntu-based Linux)

If you skip setup, it runs automatically the first time you use any command.

### Verify

```bash
riplex --help
riplex-ui
```

Both commands should work from any terminal.

## Manual tool installation

Most users don't need this section -- the setup wizard installs tools
automatically on Windows, macOS (with Homebrew), and Debian/Ubuntu-based
Linux. If the wizard couldn't install a tool for your platform, or you prefer
to install manually, follow the instructions below.

riplex requires these three tools:

| Tool | Purpose |
|---|---|
| [MakeMKV](https://www.makemkv.com/) | Disc reading and ripping (`makemkvcon`) |
| [FFmpeg](https://ffmpeg.org/) | MKV metadata probing (`ffprobe`) |
| [MKVToolNix](https://mkvtoolnix.download/) | MKV splitting and tagging (`mkvmerge`, `mkvpropedit`) |

### Windows

```
winget install GuinpinSoft.MakeMKV
winget install Gyan.FFmpeg
winget install MoritzBunkus.MKVToolNix
```

Or download installers from the links above. These installers add the tools to
your PATH automatically.

### macOS

```
brew install ffmpeg mkvtoolnix
```

MakeMKV must be downloaded from https://www.makemkv.com/ since it isn't in
Homebrew. The app bundle includes `makemkvcon` automatically.

### Linux (Debian, Ubuntu, Pop!_OS, Mint, etc.)

```
sudo apt install ffmpeg mkvtoolnix
```

MakeMKV must be downloaded from https://www.makemkv.com/ or built from
source. See the [MakeMKV forum](https://forum.makemkv.com/forum/viewtopic.php?t=224)
for instructions.

### Linux (Bazzite, Fedora Silverblue, and other immutable distros)

On immutable distros, `apt` isn't available. Use `rpm-ostree` to install
packages:

```
rpm-ostree install ffmpeg mkvtoolnix
```

Then reboot for the changes to take effect.

MakeMKV must be downloaded from https://www.makemkv.com/.

> [!WARNING]
> If you installed MKVToolNix as a Flatpak, `mkvmerge` won't be on your
> system PATH even though the GUI works fine. Either layer it with
> `rpm-ostree install mkvtoolnix` (recommended) or create a wrapper script:
>
> ```
> sudo tee /usr/local/bin/mkvmerge << 'EOF'
> #!/bin/sh
> exec flatpak run --command=mkvmerge org.bunkus.mkvtoolnix-gui "$@"
> EOF
> sudo chmod +x /usr/local/bin/mkvmerge
> ```

### MakeMKV registration

MakeMKV requires a registration key. A free beta key is available at
https://forum.makemkv.com/forum/viewtopic.php?f=5&t=1053 and must be entered
in MakeMKV (Help > Register) before `makemkvcon` will work. The beta key is
updated periodically.
