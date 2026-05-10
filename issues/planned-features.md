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


## Smarter Duplicate Detection (Audio/Subtitle Comparison)

Today, duplicate detection on the live disc compares only resolution,
duration, and file size. Two titles with identical specs are flagged as
duplicates even if their audio or subtitle tracks differ.

In most cases (e.g. 2001: A Space Odyssey 4K, where playlist `00089.mpls`
and raw segment `00058.m2ts` point to the same underlying content), this is
correct. But some discs ship multiple "main movie" titles that differ in
ways the current heuristic misses:

- **Different audio mixes** — one title has Dolby Atmos / DTS:X, the other
  is DTS-HD MA only
- **Different language sets** — one title has the international audio bundle,
  another has region-specific tracks
- **Different commentary tracks** — one title includes director commentary,
  another doesn't
- **Different subtitle bundles** — forced-only vs. full subtitle packs

We already parse `audio_tracks` and `subtitle_tracks` from makemkvcon's
SINFO output (codec, channel layout, language). The data is sitting unused
in `DiscTitle`.

### Brainstorm: how to handle non-identical "duplicates"

If two titles have matching size/duration/resolution but their audio or
subtitle tracks differ, we should:

1. **Surface the difference clearly** — show the user what changes between
   the candidate titles (e.g. "Title #3 has Dolby Atmos; Title #1 does not").
2. **Recommend ONE by default** based on a sensible heuristic (e.g. prefer
   lossless > lossy; prefer the title containing the user's preferred
   languages from config; prefer the title with more tracks overall).
3. **Allow the user to override** the recommendation and rip multiple
   variants if they want.

### Open questions

- How do we name files when the user rips multiple "duplicate" titles? Some
  ideas: `Movie (2001) - Atmos.mkv`, `Movie (2001) - DTS-HD.mkv`. Plex
  doesn't have an official "audio version" concept like Multi-Version Movies.
- Should the recommendation logic tie into the upcoming
  Multi-Language Track Selection feature so the user's language preferences
  drive duplicate selection too?
- For "almost-duplicate" detection, what's the diff threshold? Same audio
  codec count? Same channel layouts? Same language set?

### Plan (rough)

1. Extend duplicate-detection in `disc/analysis.py` to compare normalized
   audio/subtitle signatures (codec + channel layout + language list) in
   addition to size/duration/resolution.
2. Introduce a "near-duplicate" classification: same video specs but
   different audio/subtitle layout. Distinct from "true duplicate".
3. For near-duplicates, generate a diff string ("adds: Atmos English; drops:
   DTS-HD MA Spanish") and surface it in the recommendation label.
4. Default recommendation: rip the variant scoring highest on user
   preferences (lossless > lossy, preferred language present, more tracks).
5. Expose to all three frontends:
   - **CLI auto mode**: rip the recommended variant; log the alternatives
     and the diff so users see what was skipped.
   - **CLI interactive mode**: prompt user with the diff and let them pick
     one or multiple.
   - **GUI selection screen**: show near-duplicates as a grouped row with
     an expandable diff view; let users check/uncheck individually.
6. When multiple variants are ripped, organize them with audio-version
   suffixes (naming convention TBD).



