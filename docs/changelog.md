# Documentation Changelog

All notable changes to the riplex documentation are recorded here.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## v0.7.4 — 2026-06-10

### Fixed

- **GUI: empty Disc Overview after continuing without dvdcompare data.** When dvdcompare had no matching release, the orchestrate flow still navigated to the multi-disc overview, which only renders dvdcompare-provided disc rows. The no-dvdcompare fallback now treats the inserted disc as a single-disc rip and jumps directly to title selection, where TMDb runtime heuristics can pick the main feature.

## v0.7.3 — 2026-06-10

### Fixed

- **GUI: silent "No optical drives detected" when MakeMKV is expired or unregistered.** When `makemkvcon` rejects requests with a fatal MSG (codes `5021` too-old, `5022` key-expired, `5023` key-invalid) it exits cleanly with zero `DRV:` lines, so riplex previously rendered an empty drive list. The shared library now parses these fatal MSGs and raises `MakeMKVError`; the Disc Detection screen surfaces the verbatim `makemkvcon` message along with **Download MakeMKV ↗** and **Get beta key ↗** buttons so users can resolve the lockout in one click.

## v0.7.2 — 2026-05-17

### Fixed

- **Auto-detected disc labels with compact season/disc suffixes.** Volume labels such as `Hannibal St01bd1` and `HANNIBAL_S1_BD1` now strip the trailing season/disc marker before TMDb and dvdcompare lookup, so both the GUI and CLI start from the correct base title instead of searching for the raw disc label.

## 2026-05-16

### Added

- New GUI walkthrough guide with screenshots for the main desktop flow: welcome, disc detection, metadata lookup, release picker, title selection, and multi-disc overview.

### Changed

- Split the user guides into `docs/gui-guide/` and `docs/cli-guide/` so the desktop flow and terminal flow are documented separately.
- Linked the new GUI walkthrough from the README, installation guide, CLI workflow guide, and docs index so beginners can discover the desktop flow more easily.

## v0.7.1 — 2026-05-16

### Fixed

- **GUI: empty drive list on fresh installs** ([#12](https://github.com/AnyCredit5518/riplex/issues/12)). Flet 0.85 removed the lowercase `ft.border` module and the `page.open()` method. The Disc Detection screen used both, which made it crash silently mid-render on fresh installs (which pulled Flet 0.85+ via the open-ended `flet>=0.84` pin), leaving users staring at the status line with no drive rows beneath it. Replaced every affected call site with the cross-version forms (`ft.Border.all`, `page.show_dialog`). Reported by @JelloEmperor, also confirmed by @abbrechen who provided the diagnosis and patch.

### Changed

- **Flet version pin tightened** to `>=0.84,<0.86` so a future Flet release can't break `pip install riplex[gui]` the moment it lands on PyPI. The upper bound will be bumped after each new Flet minor is smoke-tested.

## v0.7.0 — 2026-05-16

Summary: organize-time match quality fixes, faster post-rip organize, and a release-picker affordance for verifying the dvdcompare film page.

### Added

- **GUI: "View on dvdcompare.net" link** on the disc-release screen. Shows the auto-selected film page so users can verify region/edition before committing to a long rip.
- **GUI: manual film-id override** on the disc-release screen. Paste either a bare fid (e.g. `55540`) or a full URL (`https://www.dvdcompare.net/comparisons/film.php?fid=55540`) and riplex fetches and uses that film page instead. The chosen fid is persisted per `(title, disc_format)` so swapping discs in the same box set keeps the override, with a "Clear saved override" affordance.
- **`riplex organize --rescan`** flag. By default `organize` now reads `_rip_manifest.json` from each disc subfolder when present (instant load, preserves rip-time classification). Pass `--rescan` to force a fresh ffprobe scan instead.
- **GUI organize folder picker**: when every disc subfolder has a `_rip_manifest.json`, the folder loads instantly without running ffprobe. A green banner indicates the manifest load with a "Rescan with ffprobe" button to force a fresh probe.
- **GUI organize preview**: every matched row now shows a confidence chip with the actual delta in seconds (e.g. `HIGH ±18s`, `MEDIUM ±104s`) so weak matches are easy to spot before executing.

### Changed

- **Tighter match tolerance for extras and episodes.** The global `_MAX_MATCH_DELTA` of 300 s is now reserved for the main-movie target; episodes and extras use a 120 s cap. This prevents short featurettes from being claimed by unrelated short clips when no good candidate exists.
- **Classification-aware matching.** Files whose rip-time classification is `Unmatched content`, `Unknown content`, or `Very short` are no longer paired with a named extra target unless the duration delta is within ±30 s. Ambiguous shorts stay unmatched (and visible) instead of being silently assigned to the closest dvdcompare entry within the loose 300 s window.
- **Release workflow**: GitHub Releases now include both the manually composed release notes and the auto-generated commit list, so tag annotations authored ahead of the tag push aren't lost.

### Fixed

- **4K disc extras classification**: 1080p extras on a 4K disc are now only skipped when a 4K counterpart actually exists on the same disc. Previously, the duplicate-detection pass could flag legitimate standalone 1080p extras as duplicates of unrelated 4K titles.

## 2026-05-13

### Changed

- Bumped `dvdcompare-scraper` pin to `>=0.1.15`, which adds quoted-title disc-header parsing.

## 2026-05-12

### Added

- Troubleshooting guide: new "GUI: disc not being detected" section covering the redesigned drive-list panel, manual drive selection, the `makemkvcon` status line, and the bundled bug-report flow.

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
- Installation guide: new "Install with pipx" section as the recommended install method for end users â€” provides globally available `riplex` and `riplex-ui` commands without venv activation.

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

- Orchestrate guide (`docs/cli-guide/orchestrate.md`): full documentation for the new primary workflow command
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
- `docs/cli-guide/workflow.md` updated to recommend orchestrate as the primary workflow
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
