# Documentation Changelog

All notable changes to the riplex documentation are recorded here.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## Unreleased

Summary: multi-work and multi-season box-set support. riplex can now rip and
organize a box set that bundles several films, or a complete multi-season TV
series, in a single guided session — with each work routed to its correct Plex
destination.

### Highlights

- **Multi-work box sets.** A single release containing several distinct films (or films plus a TV series) is now detected as multiple works. Each work gets its own title selection, rip grouping, and Plex target, so a mixed box set no longer has to be ripped one disc at a time and sorted by hand.
- **Multi-season TV.** Complete-series sets spanning multiple seasons are ripped season by season. A new Season Select screen (GUI) and season prompt (CLI) assign each disc to a season, and rips nest under `Season NN/` automatically.
- **Guided resume.** A session marker (`_riplex_session.json`) records the whole plan, so you can stop after any disc and resume later — from any disc of the set — without re-picking metadata.
- **Metadata persisted per rip.** Rip manifests now store the chosen TMDb and dvdcompare ids, so organizing (or resuming) a ripped disc skips the pickers and reuses the exact match you confirmed at rip time.
- **Smarter TV matching.** dvdcompare episode listings are cross-referenced against the TMDb episode list, and episodes are assigned deterministically from their rip-time classification instead of guessing between near-identical runtimes.

### ⚠️ Breaking

- **Disc-group ids changed** from the old `main_1` / `film_31` scheme to `disc_1` / `discs_1_4` / `disc_31`. A session saved by an earlier version will not resume — start a fresh session after upgrading.

### Added

- Multi-work release routing: per-work title selection, rip groups, and Plex destinations, with full CLI parity for `organize` and `orchestrate`.
- Season Select screen (GUI) and season prompt (CLI) for assigning discs to seasons in multi-season sets.
- Interactive title-selection editor at the CLI Proceed prompt, so picks can be adjusted before the rip starts.
- Per-group rip output on the Select Titles screen, showing each work's files separately.
- Multi-work session marker (`_riplex_session.json`) enabling resume from any disc of a set.
- Rip manifests now record the confirmed TMDb and dvdcompare ids to skip the pickers on organize and resume.
- Season labels and chips on the Disc Overview, plus a "Currently loaded" disc dropdown.
- "Organize into Library" shortcut on the Disc Overview once every disc has been ripped.
- Hidden-discs banner explaining discs the plan intentionally skips.
- "View on dvdcompare.net" link when a release has already been matched.
- **Development > Testing guide** (`development/testing.md`) documenting the headless GUI and CLI integration test suites, the `tests/support/` harness, the `gui` fixture, media-type-targeted flows, and how to generate scenario fixtures from archived rips with `scripts/gen_gui_fixtures.py`.
- **GUI auto-eject.** The disc is ejected automatically after a rip finishes so you can swap discs (or know it's done) without reaching for the drive. On by default; set `auto_eject = false` in the config to disable.
- **GUI in-place update (Windows).** The update screen now offers **Update & Restart**: riplex downloads the new build, verifies its SHA-256 checksum, swaps the running `.exe` in place, and relaunches — no manual re-download or repeated SmartScreen approval. Requires a writable install folder; falls back to the browser download otherwise. Releases now publish `.sha256` checksums for every asset.

### Changed

- CLI `orchestrate` now resumes from the session marker (GUI parity) via the shared `resume.py` adapter.
- Disc grouping splits on dvdcompare hyperlinks (`pointer_fid`) rather than `is_film`, so a bonus-films disc forms its own group.
- `DiscGroup.kind` removed; group labels and ids simplified.
- TV rips nest under `Season NN/` and cross-reference dvdcompare features against the TMDb episode list.
- Ctrl-C now exits cleanly (exit code 130, no traceback, no orphaned `makemkvcon` process).
- Softer disc-mismatch wording, and the release picker shows the matched dvdcompare film.
- `_plan_show` keeps Season 0 (Specials); the Organize preview shows a title/season source badge.
- Every `orchestrate` disc now routes through an Insert Disc scan-confirm step.
- **Architecture** file tree now lists `tests/integration/`, `tests/support/`, and `tests/fixtures/gui/scenarios/`.

### Fixed

- **TV: a single wrong dvdcompare episode runtime no longer mislabels two episodes.** When a disc's episode-length titles line up 1:1 with the dvdcompare episode list, riplex now assigns them by disc position instead of purely by runtime. Previously a bad listed runtime (e.g. Psych S6 D3 listing "Heeeeere's Lassie" at 43:10 when the disc title is 49:41) orphaned that episode to a generic "Episode" label and let a same-runtime neighbour steal its slot. Positional alignment fixes both; it only applies on an exact 1:1 count match with at most one runtime outlier, and defers to runtime matching on ragged or reordered discs.
- **GUI: cancelling a rip returns to the current disc, not the next one.** In an orchestrate session, stopping a rip mid-disc took you to the *next* disc's Insert Disc screen. It now returns to the current disc's Insert Disc screen so you can retry, skip, or eject — and the cancelled disc is no longer marked as ripped (no manifest written) or auto-ejected.
- **GUI: Organize Rips scan-results footer now anchors to the bottom** like every other wizard screen. The results form now scrolls internally while the Back/Next buttons stay pinned at the window edge.
- **GUI: Organize Rips Back button walks up the flow** instead of dropping to the Welcome screen. On the scan-results view it restores the multi-group picker (when the folder held several seasons or works) or otherwise returns to the folder input; the multi-group picker's Back button now returns to the folder input as well.
- **Organize: duplicate-title extras no longer clobber their episode's destination.** dvdcompare sometimes lists the same episode name twice (real broadcast episode + a shorter bonus re-edit). The rip-time enrichment already demotes the shorter entry to ``[extra]``, but the organizer was ignoring that tag and fuzzy-routing both files to the same ``s0Xe0Y - Title.mkv`` destination — so the second file silently overwrote the first when organize actually executed. The organizer now respects the ``[extra]`` classification and routes the duplicate to an extras folder instead.
- Duplicate Quit buttons on the rip-complete summary and Insert Disc screens.
- False "multiple films" alert on Select Titles, with a confirmed movie title and clearer section headers.
- Ctrl-C at a prompt no longer behaves like pressing Enter.
- Movie picks now filter to just the movie disc(s), on both fresh and resumed sessions.
- The primary-work film slot shows its runtime, and hidden discs are explained.
- Organize honors the rip-time season/episode classification and no longer collides same-basename files across discs.
- Organize fuzzy-matches dvdcompare episode titles against TMDb, and reads title/season from the rip manifest for season-nested output.
- Organize no longer crashes after a resumed rip.
- TV episodes are assigned sequentially (first-fit); over-length titles are labeled "Unmatched content".
- The Disc Release screen shows the dvdcompare film title as its heading.
- `detect_disc_format` recognizes standard-definition DVDs.
- `riplex organize` discovers the session marker and fans out across all works.
- Resume works from any disc of a multi-work release, and season chips show on leading discs on resume.
- Linked-film autofill strips dvdcompare format markers, and the main feature is no longer misclassified as a play-all title.
- The dvdcompare cache auto-invalidates when the scraper version changes, and auto-lookup no longer picks the wrong franchise.

## v0.9.2 — 2026-06-24

### Fixed

- **TMDb credentials: accept both the API Key and the Read Access Token.** TMDb's settings page offers a v3 API Key (query parameter auth) and a v4 API Read Access Token (bearer header auth). riplex now auto-detects which credential was provided and uses the matching auth scheme, so pasting the Read Access Token no longer fails with `401 Unauthorized`. The setup wizard, GUI welcome screen, and docs now note that either credential works.

## v0.9.0 — 2026-06-13

Summary: Plex-aligned movie version and edition support for combo-disc releases, with better organize preview matching for 4K, Blu-ray, and 3D movie rips.

### Added

- **Plex movie versions and editions.** Movie organization now distinguishes Plex versions, such as `4k` and `1080p`, from Plex editions, such as `{edition-3D}`. Multiple 2D resolutions are organized together in the base movie folder, while 3D rips are organized as a separate Plex edition folder.
- **3D movie edition output.** 3D movie rips now use Plex's edition naming convention in both folder and file names, for example `Movie Title (Year) {edition-3D}/Movie Title (Year) - 1080p {edition-3D}.mkv`.
- **Combo-pack movie matching.** Multi-disc releases with separate 4K, Blu-ray, and 3D film discs now match each main feature independently so the 4K movie, standard 1080p movie, and 3D edition can all be organized from the same release.

### Changed

- **2D is treated as the base movie, not an edition.** dvdcompare labels such as `2D` are still useful for matching disc targets, but the organized Plex output keeps 2D files in the normal `Movie Title (Year)` folder instead of creating `{edition-2D}` folders.
- **Resolution suffixes are inferred from scanned video dimensions.** Standard Blu-ray movie rips now receive a `- 1080p` suffix when ffprobe reports 1920x1080 video, matching the existing `- 4k` behavior for 2160p content.
- **Duplicate bonus features no longer clutter the missing list.** If the same bonus feature appears on multiple discs and one copy is matched, equivalent duplicate targets from other present discs are suppressed from the organize preview's missing section.

### Fixed

- **4K main feature skipped in 4K + 3D combo releases.** Multi-edition film entries on a separate 3D/2D Blu-ray disc no longer suppress the generic movie target needed to match a separate 4K film disc.
- **Matched extras still shown as missing.** Duplicate extras such as `Behind The Scenes` and `Humpback Whales` no longer appear under missing after one copy has already been matched and planned for organization.

## v0.8.0 — 2026-06-12

### Added

- **GUI: editable settings after first-run setup.** The welcome screen now exposes an **Edit Settings** button after configuration is complete, so users can update the TMDb API key, media library root, MakeMKV rip output folder, and optional archive folder without re-running setup from the command line.

### Changed

- **GUI: less Plex-specific library wording.** User-facing destination copy now refers to a general media library while retaining **Plex-compatible naming** where the current folder/file convention is being described.

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
