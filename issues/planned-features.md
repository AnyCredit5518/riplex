# Planned Features


## Multi-Resolution Support (4K + Standard Blu-ray)

Many 4K boxsets include standard Blu-ray discs with the same content at 1080p.
Some users may want to rip both so Plex can serve the lower-resolution version
to mobile devices without transcoding.

**Movies**: Supported via Plex "Multi-Version Movies" — multiple files with
different resolution suffixes in the same folder collapse into one item.

**TV Shows**: NOT officially supported by Plex. No documented multi-version
episode collapsing.

### Plan

- Support ripping both 4K and standard Blu-ray discs for movies, naming with
  resolution suffixes during organize.
- For TV shows, warn users and offer to skip (explain limitation), allow
  override for users with separate libraries.


## Orchestrate Flow (GUI)

The GUI has rip and organize flows. The orchestrate flow (multi-disc pipeline
with disc-swap prompts) is not yet implemented.

### Key pieces needed

- Disc swap prompt screen
- Session state tracking across disc swaps (accumulated rip results, metadata)
- Disc number auto-detection after each swap
- Error recovery (retry/skip failed disc)
- Cancel mid-flow and organize what's been ripped so far


## Bug Report Submission

### Problem

Snapshot files for debugging are mixed in with media files and have
inconsistent formats. Users must hunt for debug artifacts across multiple
locations when filing bug reports.

### Plan

1. Move all debug artifacts into a `_riplex/` subfolder (Plex-ignored).
2. Consistent v2 snapshot envelope format with type discriminator.
3. GUI writes same snapshots as CLI.
4. "Report a Bug" button in GUI: opens pre-filled GitHub issue, copies
   debug folder path to clipboard.
5. `.github/ISSUE_TEMPLATE/bug_report.yml` for structured reports.


## Interactive Lookup Command

`riplex lookup` currently auto-picks the first TMDb match and default
dvdcompare release without confirmation. Add interactive selection (reuse
existing `_pick_best` prompt from planner). Keep `--auto` flag for scripting.


## Multi-Language Track Selection

Users in multilingual households want to keep multiple audio and subtitle
tracks when ripping, not just the default/English track.

### Plan

- Add config options for preferred audio and subtitle languages (e.g.
  `audio_languages = ["en", "es"]`, `subtitle_languages = ["en", "es", "fr"]`)
- During rip, pass language preferences to MakeMKV/mkvmerge so all selected
  tracks are retained
- During organize, preserve all selected tracks when remuxing
- GUI: add language selection to setup/config screen
- Default behavior: keep all tracks (current MakeMKV default) — only filter
  if the user explicitly configures preferred languages
