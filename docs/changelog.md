# Documentation Changelog

All notable changes to the riplex documentation are recorded here.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## Unreleased

### Changed

- **Disc grouping now splits on dvdcompare hyperlinks, not `is_film`.** The previous rule split a release into groups wherever the `is_film` flag changed between contiguous discs. That misclassified releases where dvdcompare treats a bonus platter as `is_film=True` (e.g. Independence Day 4K disc 3, a supplements-only Blu-ray), fragmenting the movie into two groups and producing an amber "unassigned" warning that blocked Start Ripping until the user manually merged them. Grouping now uses the frozen set of `pointer_fid` values across each disc's extras as the split key: a disc with no hyperlinked extras (`frozenset()`) merges with its neighbors, and only discs whose extras hyperlink to *distinct* film pages break out into their own group. The Independence Day case now stays as a single "Discs 1-3" group with the movie match auto-applied; the Psych Complete Series case still splits disc 31 out because its three linked TV-movies each point to a different fid.
- **`DiscGroup.kind` dropped.** The `Literal["main", "film"]` discriminator that flowed through `models.py`, `lookup.py`, `disc_overview.py`, `organize_by_group.py`, and `selection.py` is gone. Groups are now differentiated only by whether `films` is populated: empty means "single work spanning these discs" (the group's `tmdb_match` is the target), non-empty means "N linked works on this disc" (each `FilmSlot.tmdb_match` is a target). This removes ~30 kind-branch sites and eliminates a class of bugs where a group's `kind` and its `films` array disagreed.
- **Group labels and ids simplified.** The old `"Main content (discs 1-4)"` / `"Feature film (disc 1)"` / `"3 feature films (disc 31)"` labels are replaced by `"Discs 1-4"` / `"Disc 1"` / `"Disc 31: 3 linked works"` (or `"Disc 31: {title}"` when a group has a single film slot). Group ids move from `main_1` / `film_31` to `disc_1` / `discs_1_4` / `disc_31`, so a resumed session referring to an old id will not match — start a fresh session after upgrading.

### Fixed

- **Main feature no longer mis-classified as a play-all when a disc has many small extras.** On Independence Day 4K disc 1 (2:24:48 theatrical + 14 short extras that happen to sum to 2:23:30), `is_skip_title` ran `detect_play_all` on the main feature and matched — the extras summed to within 78 seconds of the feature runtime, well inside the loose sum-tolerance the detector uses (~210s for 14 parts). The Select Titles screen then hid the theatrical version behind a `SKIP` badge, so a resumed rip only picked the extended cut. `is_skip_title` now short-circuits the play-all checks when the candidate's runtime is at or above the main-feature runtime (and within a plausible extended-cut range), matching the ordering that `classify_title` already used to produce the correct human-readable label.
- **dvdcompare cache auto-invalidates on scraper version change.** The disk cache under `<cache>/dvdcompare/` stores serialized `FilmComparison` payloads. When `dvdcompare-scraper` gains a new field on its models (e.g. `Feature.pointer_fid`), older cached entries were served with the new field missing — so bug fixes shipped in a scraper upgrade appeared not to work until users manually ran `riplex cache clear`. A version marker (`_version.txt`) is now written inside the `dvdcompare` cache namespace on the first `DiscProvider` construction; when the installed `dvdcompare-scraper` version changes, the namespace is wiped and re-seeded automatically. Any pre-existing cache without a marker is treated as stale on the next launch (it predates this feature and was likely written by an older scraper) and is wiped once, so users upgrading to this build don't need to manually clear.
- **dvdcompare auto-lookup no longer picks alphabetically-first film of the wrong franchise.** Searching a short common title like "Psych" against dvdcompare returns 100+ results; the previous format-only ranker picked "American Psycho (Blu-ray)" (alphabetically first Blu-ray match) instead of "Psych: Season 1 (TV) (Blu-ray)". Auto-selection now filters results to those whose leading title (before the first colon) exactly matches the query, so an unrelated franchise sharing a substring can never win over an actual title match. The format check also falls back to scanning the result title text since dvdcompare's scraper sometimes leaves the `disc_format` field unset for Blu-ray entries.
- **Season label for the leading discs of a series release now falls back to the film title.** Pages like `Psych: Season 1 (TV) (Blu-ray)` (fid=66231) use `DISC ONE ... DISC FOUR` for the release's own discs (no explicit `Season 1:` header) and `DISCS FIVE - EIGHT: Season 2` for the pointer runs. The scraper faithfully returns empty titles for discs 1–4, which left the disc overview without a season chip on those rows even though the film title itself says Season 1. `build_season_labels` now parses `Season N` out of the film title and applies it to the leading untitled run; explicit later runs (Season 2, 3, …) still win, and trailing untitled discs (bonus platters) stay unlabeled.
- **Bonus-films disc on a season-entry Complete Series release is now split into its own group.** On the `Psych: Season 1` dvdcompare page (fid=66231), disc 31 lists three standalone TV-movies via `<a href="film.php?fid=…">` links but doesn't carry a `* The Film` marker — so the previous grouping treated disc 31 as another TV disc and each ~90-minute movie as an unlabeled episode. `dvdcompare-scraper` now captures the anchor's target fid on `Feature.pointer_fid`; riplex threads it through to `PlannedExtra.pointer_fid` and treats any disc with pointered extras as film-like. Each film becomes its own `FilmSlot` carrying the linked fid, and Disc Overview autofill hits that fid to read the canonical film title before searching TMDb — so the three Psych movies now auto-fill into their own Plex movie folders regardless of which physical disc the user inserted first.

### Added

- **"View on dvdcompare.net" link on the already-selected release view.** When the release screen shows the current selection (after navigating back to it), it now includes the same `fid=…` deep-link button already shown on the multi-release picker, so users can double-check the auto-pick was right before ripping.
- **Multi-work session marker for resume.** When orchestrate starts a rip session, riplex now writes a `_riplex_session.json` marker into every work-folder of the release. On resume, `find_existing_session` reads the marker from whichever folder the user's typed title lands in and aggregates every sibling work-folder's ripped discs into a unified queue. A Psych session (TV series + bonus films disc) resumed via either "Psych" or "Psych: The Movie" now correctly skips discs already ripped under the other work-folder instead of re-queueing them.
- **Multi-work release routing.** Releases that bundle multiple distinct works — a TV series plus standalone films on a bonus disc, for instance — now organize each work into its own Plex target. The disc overview groups discs into per-work slots (main content plus one slot per bonus film), auto-fills TMDb best guesses, and the organize preview routes each disc's MKVs to the folder for that work's assigned match.
- **CLI parity for multi-work releases.** `riplex organize` and `riplex orchestrate` now share the GUI's Disc Overview routing: when a release splits into multiple works, each group is planned separately (TV series → episode folders; bonus films → per-film Plex movie folders) and the merged plan is executed as one preview. Interactive prompts confirm auto-filled TMDb targets; non-interactive runs accept auto-fills and surface any unresolved slots as skipped groups in the summary.
- **Per-group rip output on the Select Titles screen.** In orchestrate mode the selection screen now looks up the current disc's DiscGroup and swaps in that group's TMDb match for the header title, the season/disc chip, and the rip output folder. Previously all discs in a multi-work release ripped under whichever match the user picked at the metadata screen, so a Psych release (TV series + bonus films disc) would send every disc under `Psych - The Movie (2017)/` regardless of what was actually on the platter.
- **Season labels in the disc overview.** When dvdcompare's release page groups discs by season (e.g. `DISCS ONE - FOUR: Season 1`), each row now shows a light-blue `Season N, Disc M` info chip so users of long TV boxsets can cross-reference against the physical case.

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
