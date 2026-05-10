# Documentation Changelog

All notable changes to the riplex documentation are recorded here.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## 2026-05-09

### Changed

- Installation guide: complete restructure for clarity. Install riplex first, then setup, then manual tool installation as a fallback. Each install option now covers all platforms (Windows, macOS, Linux, immutable Linux distros).
- Installation guide: Windows executable instructions rewritten with step-by-step PATH setup, SmartScreen guidance, and separate GUI vs CLI paths.
- Installation guide: macOS CLI now installs to `/usr/local/bin/riplex` with proper rename.
- Installation guide: Option C (from source) split into numbered steps with separate Windows and macOS/Linux commands.
- Installation guide: tkinter/folder picker note now covers both macOS and Linux.

### Added

- Installation guide: Linux (Bazzite, Fedora Silverblue, immutable distros) sections for pipx install and manual tool installation, including Flatpak wrapper script for MKVToolNix.
- Installation guide: MakeMKV registration pulled into its own subsection.

## 2026-05-08

### Added

- Disc fixture testing pattern for end-to-end classification tests using captured disc data.
- `tests/test_disc_fixtures.py`: new test file for classification testing against real disc layouts.

## 2026-05-04

### Added

- Troubleshooting guide: macOS-specific sections for tkinter/browse button, SSL certificate errors, Gatekeeper blocking, and tools not found despite being installed.
- Installation guide: new "Install with pipx" section as the recommended install method for end users — provides globally available `riplex` and `riplex-ui` commands without venv activation.

### Changed

- Installation guide: dropped pre-built Intel macOS binary; macOS downloads are now Apple Silicon only. Intel Mac users directed to install with pipx.
- Installation guide: "Installing from source" section now clearly scoped to developers, with a note pointing users to pipx for global installs.
- Installation guide: clearer Gatekeeper instructions as a dedicated step with right-click method.
- Installation guide: added tip for macOS users recommending install from source.

## 2026-05-03

### Changed

- Installation guide: macOS pre-built executables now ship as `arm64` (Apple Silicon) only; added instructions to remove the Gatekeeper quarantine flag.
- Installation guide: "Installing from source" section now includes venv setup steps and a macOS SSL fix for Homebrew Python users (`SSL_CERT_FILE` via certifi).
- Installation guide: added macOS tkinter section for folder picker support.

### Added

- New troubleshooting guide (`docs/troubleshooting.md`) covering: makemkvcon not on PATH (Flatpak issue), drive not detected, invalid config file, TMDb API key signup, and dvdcompare lookup failures
- `find_ffprobe()` helper: all ffprobe consumers now check `~/.riplex/bin/`, `/usr/local/bin/`, and `/opt/homebrew/bin/` in addition to PATH.
- macOS auto-download: "Install Missing Tools" on macOS < 14 auto-downloads ffprobe from evermeet.cx to `~/.riplex/bin/`; opens download pages for MakeMKV and MKVToolNix.
- macOS .app bundle detection: `find_makemkvcon()` checks `/Applications/MakeMKV.app/`; `find_mkvmerge()` and `find_mkvpropedit()` check `/Applications/MKVToolNix.app/`.
- Dual-arch macOS CI builds (`macos-13`/x86_64 and `macos-14`/arm64) in release workflow.
- Arch-aware macOS update checker in GUI updater.
- Install progress bar and streaming output for Homebrew installs on macOS 14+.
- Graceful tkinter fallback in folder picker and welcome screen browse buttons.
- Linux apt support in GUI tool installer.

## 2026-05-02

### Changed

- Architecture doc: complete rewrite of project structure to reflect current module layout (`disc/`, `metadata/`, `riplex_cli/commands/`, all GUI screens)
- Architecture doc: replaced outdated "Plan mode" and "Rip guide mode" with single "Lookup mode" data flow
- Architecture doc: added archive step to organize mode data flow
- Installation guide: fixed GUI entry point from `riplex-gui` to `riplex-ui`
- Installation guide: added pre-built executable download instructions (Option A) for Windows and macOS
- Copilot instructions: fixed GUI entry point from `riplex-gui` to `riplex-ui`
- Changelog entry for 2026-05-01: corrected `riplex-gui` reference

### Added

- New modules documented in project structure: `title.py`, `lookup.py`, `manifest.py`, `formatting.py`, `folder_picker.py`, `organize_preview.py`, `organize_done.py`
- CLI commands directory (`riplex_cli/commands/`) documented with all five command modules
- GitHub Actions workflow for building standalone executables (`release.yml`): Windows `.exe` and macOS `.app` via PyInstaller, auto-published on tagged releases

## 2026-05-01

### Changed

- Architecture doc updated to reflect monorepo structure with three source packages (riplex, riplex_cli, riplex_app)
- Project structure listing now includes orchestrate.py, riplex_cli/, and riplex_app/ with all GUI screens
- Installation guide updated with GUI install instructions (`pip install -e ".[dev,gui]"`) and `riplex-ui` entry point

### Added

- New module `orchestrate.py` documented in project structure (shared pipeline logic)
- `riplex_cli` package documented as the CLI thin wrapper
- `riplex_app` package documented as the optional GUI thin wrapper with screen descriptions
- Installation methods table (pip install riplex vs riplex[gui])

## 2026-04-30

### Added

- Orchestrate guide (`docs/guide/orchestrate.md`): full documentation for the new primary workflow command
- `orchestrate` subcommand in CLI Reference with complete options table
- `rip` subcommand added to README (features block, usage examples, CLI reference table)
- `orchestrate` subcommand added to README (features block, usage examples, CLI reference table)
- New config keys documented: `rip_output` and `archive_root` (README, configuration.md, CLI reference)
- Orchestrate and Rip data flow diagrams in architecture.md
- MakeMKV/makemkvcon added to Requirements section
- New source files documented in project structure: `ui.py`, `disc_analysis.py`, `makemkv.py`
- Orchestrate entry in mkdocs.yml navigation

### Changed

- README Features section reordered: orchestrate and rip are now listed first as the primary commands
- `plan` marked as deprecated (alias for `rip-guide`) throughout README and CLI reference
- Organize output examples updated to new grouped format (subfolder headings, `<-` arrow notation)
- Rip-guide output examples updated to use configurable rip output path instead of hardcoded `_MakeMKV`
- Architecture section updated from 4 modes to 6 modes (added orchestrate, rip)
- Project structure listings updated to include all current source and test files
- `docs/guide/workflow.md` updated to recommend orchestrate as the primary workflow
- `docs/architecture.md` updated with orchestrate and rip modes and data flows
- `PLANNED_FEATURES.md` orchestrate section moved to "Recently Implemented"
- CLI reference tables for organize (added `--snapshot`, `--auto`) and rip-guide (added `--drive`) updated

## 2025-04-20

### Changed

- Replaced all personal/machine-specific paths with generic placeholders across all docs and README
- CLI examples now use `path/to/rips/Title` for user-supplied input paths
- Tool output examples (rip-guide folder structure) use `<output_root>/_MakeMKV/` to clarify the staging directory
- Output destination examples use relative paths (e.g. `Movies/...`, `TV Shows/...`)
- Config examples use `/path/to/media` placeholder
- Debug log references changed to "OS temp directory" instead of platform-specific paths
- Removed personal Python install path from `.github/copilot-instructions.md`

### Added

- Initial documentation structure in `docs/` folder
- Home page with feature overview and quick start (`index.md`)
- Getting Started section: Installation, Configuration
- User Guide section: Typical Workflow, Rip Guide, Organizing Files, Planning, Snapshots
- CLI Reference page with all subcommands and options
- Architecture overview with data flow diagrams
- Plex Naming Rules reference
- `mkdocs.yml` configuration (ready for MkDocs Material when published)
- This changelog
