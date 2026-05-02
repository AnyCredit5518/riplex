# Monorepo Refactor Plan

## Project Context

riplex automates disc ripping and file organization for Plex. It reads physical discs via MakeMKV, identifies what's on them using TMDb and dvdcompare.net metadata, rips the right titles, then deduplicates, matches, renames, and moves files into the exact folder structure Plex expects.

There are currently two repos:
- **riplex** (`C:\Users\asher\Projects\anycredit5518\riplex`): the library and CLI, published to PyPI
- **riplex-app** (`C:\Users\asher\Projects\anycredit5518\riplex-app`): a Flet-based GUI that depends on riplex as a pip package

## Problem

The current two-repo setup has issues:

1. **Shared logic is trapped in `cli.py`**: Functions like disc format detection, release scoring, disc number inference, and title extraction are private helpers in the CLI module. The GUI needs the same logic but can't access it, so it duplicates it.

2. **Circular development friction**: Changing a shared algorithm means updating both repos, keeping them in sync, and dealing with version pinning.

3. **Distribution complexity**: Users who want the GUI must install two packages. Building the GUI .exe requires a working riplex install.

## Goal

Consolidate into a single repo with a clean separation of concerns:

- **Library layer**: all business logic, reusable by any frontend
- **CLI layer**: thin wrapper that handles argument parsing, terminal formatting, and interactive prompts
- **GUI layer**: thin wrapper that handles Flet screens and user interaction

Both the CLI and GUI should be thin consumers of the library. Neither should contain business logic.

## Requirements

1. **Single repo**: all code lives in one place, one set of tests, one CI pipeline
2. **Clean library API**: shared orchestration logic must be importable as a public module (not private `_functions` buried in a CLI file)
3. **Independent installability**: `pip install riplex` gets you library + CLI (no GUI dependencies). GUI is optional via `pip install riplex[gui]` or standalone binary.
4. **Zero CLI regression**: the `riplex` command must behave identically after the refactor. All existing tests must pass at every step.
5. **Standalone GUI binary**: the GUI can be packaged as a .exe/.app for users who don't have Python
6. **Atomic commits**: each commit should be a self-contained logical change that doesn't break the build

## Target Architecture

```
riplex/
  src/
    riplex/              # Shared library (all business logic)
    riplex_cli/          # CLI thin wrapper (argparse, terminal formatting, prompts)
    riplex_app/          # GUI thin wrapper (Flet screens, no business logic)
  tests/
  docs/
  pyproject.toml
```

### Distribution

| Install method | What you get |
|---|---|
| `pip install riplex` | Library + CLI |
| `pip install riplex[gui]` | Library + CLI + GUI (flet dependency) |
| GitHub Release .exe/.app | Standalone GUI binary |

## Scope of Work

The core of this refactor is extracting shared logic out of `cli.py` so both frontends can use it, then bringing the GUI source into this repo.

Key areas to address:
- `cli.py` is ~2800 lines mixing business logic with CLI presentation. The reusable pipeline logic (disc detection, format inference, release selection/scoring, disc number detection, title inference, folder creation, manifest handling) needs to become a proper public module.
- The GUI currently duplicates some of this logic (release scoring, format detection). After extraction, remove the duplicates.
- `pyproject.toml` needs to declare multiple packages, entry points for both CLI and GUI, and an optional `[gui]` dependency group.
- CI needs a new workflow to build GUI binaries on tagged releases.
- The standalone `riplex-app` repo should be archived with a pointer to the monorepo.

## Implementation Recommendations

These are suggested approaches, not prescriptive steps. Use judgment on the exact module boundaries and function signatures.

### Extracting shared logic

Create a module (e.g. `riplex.orchestrate` or similar) to house the pipeline functions currently private in `cli.py`. Candidates include:
- Disc format detection from resolution metadata
- Title inference from volume labels and MKV title tags
- Media type inference (movie vs TV)
- Release scoring by duration matching
- Disc number auto-detection
- Rip folder creation and manifest handling

### Splitting the CLI

Move argparse setup, command dispatch, terminal-specific formatting (progress bars, dry-run banners, rip guide printing), and the interactive setup wizard into `src/riplex_cli/`. The CLI imports from `riplex.*` for all logic.

### Bringing in the GUI

The GUI source at `riplex-app/src/riplex_app/` already imports from `riplex.*` so it should mostly work after copying. Replace any duplicated logic with imports from the new shared module.

### Suggested work order

1. Extract the shared module from `cli.py` first (independently testable, doesn't break anything)
2. Create `riplex_cli/` and move CLI wrapper code
3. Verify all tests pass and CLI behaves identically
4. Copy GUI source in, remove duplicates, update imports
5. Update `pyproject.toml`
6. Add GUI build workflow
7. Merge to main when stable

## Constraints

- Work on the `monorepo` branch until stable
- All existing tests must pass at every step
- The GUI does not need its own test suite yet (manual testing is fine)
- Do not change CLI behavior unless explicitly intended

## GUI Feedback (to address post-merge)

- Done screen: should auto-update when ripping finishes (currently requires a click)
- Done screen: add "Organize" button as a next step after ripping
- Multi-disc flow: prompt to insert next disc instead of showing the final "done" screen
