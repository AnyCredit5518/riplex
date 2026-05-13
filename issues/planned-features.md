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


## Automated Contributors List Updater

`CONTRIBUTORS.md` lists community members who have helped riplex by reporting
bugs (and eventually other contribution categories). Today it's hand-edited,
which means it goes stale fast and we forget to credit people.

### Plan

1. **Script** — `scripts/update_contributors.py` that:
   - Uses the GitHub REST API (via `requests` or `PyGithub`) to enumerate
     closed issues in `AnyCredit5518/riplex` labeled `bug`.
   - For each issue, checks whether it was referenced by a merged commit
     on the default branch (search commit messages for `#N`, `fixes #N`,
     `closes #N`, etc.) — only counts issues that led to an actual fix.
   - Tallies issues per opener, excluding `AnyCredit5518` and any account
     ending in `[bot]`.
   - Maps tally to rank: 🐛 4+, 🔍 8+, 🛡️ 15+, 💎 25+ (matches existing
     thresholds in `CONTRIBUTORS.md`).
   - Renders the "Bug Bashers" table between two HTML comment markers
     (`<!-- BUG_BASHERS:START -->` / `<!-- BUG_BASHERS:END -->`) so the
     surrounding prose stays hand-editable.
   - Sorts by issue count (desc), then username (asc) for stable diffs.
   - Reads token from `GITHUB_TOKEN` env var; falls back to unauthenticated
     requests (lower rate limit) for local runs without a token.
   - Has unit tests covering the rank-mapping, exclusion list, marker
     replacement, and the "referenced by merged commit" detection (with
     mocked API responses).

2. **Workflow** — `.github/workflows/update-contributors.yml`:
   - Triggers: `schedule: cron '0 12 * * 1'` (every Monday 12:00 UTC) +
     `workflow_dispatch` for on-demand runs.
   - Runs `python scripts/update_contributors.py`, then uses
     `peter-evans/create-pull-request` to open a PR titled
     `chore: refresh CONTRIBUTORS.md` if there's a diff.
   - Uses the built-in `GITHUB_TOKEN` — no extra secrets needed.
   - PR is opened against `main` so the maintainer can review additions
     and rank promotions before merging.

3. **Future contribution categories** (out of scope for v1, but design with
   them in mind):
   - Code contributors (PRs merged) — once external PRs start landing.
   - Documentation contributors — `docs/` PRs merged.
   - Each category gets its own marker block so the script touches only
     what it owns; everything else in `CONTRIBUTORS.md` stays hand-editable.


## SKIP Reason Column on Selection Screen

The Selection screen currently shows a `RIP` / `SKIP` badge next to each
title, but doesn't tell the user *why* a title was marked SKIP. Users have
to check `_riplex` snapshots or the GUI log to understand the heuristic's
reasoning, which makes it hard to spot bad recommendations (e.g. a
soundtrack Play-All being mistakenly skipped, or an unmatched short title
that's actually a legitimate menu loop).

### Plan

1. **Refactor `is_skip_title()`** in `src/riplex/disc/analysis.py` to return
   a structured result (e.g. a small dataclass `SkipDecision(skip: bool,
   reason: str | None)`) instead of just `bool`. Each branch returns a
   short, user-facing reason string:
   - `"Too short (<2 min)"`
   - `"Duplicate of #N"`
   - `"Lower-res copy of 4K title"`
   - `"Play-All wrapper (covered by individual entries)"`
   - `"Lower-res featurette (4K version exists)"`
   - `"Disc-internal play-all"`
   - `"Cross-resolution play-all"`
   - `"Unmatched short clip (likely junk)"`
   - `"Unmatched, well below movie runtime"`
2. **Backward-compat wrapper**: keep a thin `is_skip_title() -> bool` that
   calls the new function and returns `.skip`, so existing callers
   (`select_rippable_titles`, tests) keep working.
3. **Plumb the reason through to the Selection screen**: store reason on
   the title row state (or pass via a parallel dict keyed by title index)
   and render it as a new column or as a tooltip on the SKIP badge.
4. **Frontend treatment**:
   - **GUI**: small grey text after the existing badge, e.g.
     `SKIP — Play-All wrapper`, or hover-tooltip on the badge for users
     who don't want extra visual clutter. Decide based on screenshot
     review.
   - **CLI**: include the reason in the `[SKIP] # N` log lines (already
     have the structure; just append the reason).
5. **Tests**: add unit tests asserting the reason string for each branch
   so future refactors don't silently break the user-facing message.
6. **Future**: once reasons are surfaced, consider an "override SKIP"
   action that lets users force-rip a skipped title and optionally
   record feedback ("this skip was wrong because…") for tuning the
   heuristics.


## Boxset / Multi-Film Collection Support

Multi-film boxsets (Godfather Trilogy 50th Anniversary, LOTR Extended,
Star Wars Original Trilogy, John Wick Collection, etc.) are currently
broken end-to-end:

- **Rip phase:** the boxset's primary TMDb match (e.g. "The Godfather"
  1972, runtime ~175 min) is used as the `(is_movie, movie_runtime)`
  context for *every* disc. When ripping Disc 4 (Godfather Part III,
  ~170 min Theatrical + ~170 min Coda), neither title matches the
  expected runtime closely enough to win "main film", so the heuristic
  falls through and labels both as `Episode (4K)`.
- **Organize phase:** with one TMDb identity but files spanning multiple
  films, files whose runtime doesn't match Part I are bucketed as
  Unmatched, and folder names are wrong.
- **Disc-overview UX:** discs are shown as "Disc 1, Disc 2 …" with no
  indication of which film(s) live on each disc.

### Reframe

"Rip each disc as its own movie" isn't the right rule — sometimes one
film spans multiple discs (long restorations, dual-format releases),
sometimes one disc has multiple short films (anthologies, double
features). The right model is:

> **A boxset = N films + shared extras. Each film needs its own TMDb
> identity. The mapping from films to discs is many-to-many.**

### Plan

1. **Detect multi-film releases** during metadata/release lookup:
   - Heuristics on the boxset name (`Trilogy`, `Collection`, `Anthology`,
     `Saga`, `Quadrilogy`, `Complete …`) and on the dvdcompare release
     name.
   - Or detect when the dvdcompare release has multiple distinct "main
     film" headers across discs (vs. a single-film boxset that's just
     loaded with extras like Inception or The Thing).

2. **New data model** — `BoxsetRelease` in `riplex/metadata/`:
   ```
   BoxsetRelease(
     boxset_name: str,
     films: list[BoxsetFilm],
     shared_extras_disc_indices: list[int],
   )
   BoxsetFilm(
     tmdb_match: TmdbMatch,
     dvdcompare_disc_indices: list[int],   # discs this film appears on
     runtime_seconds: int,
     variants: list[str],                  # Theatrical, Extended, Coda, etc.
   )
   ```

3. **New "Boxset Films" screen / lookup step** — after release selection,
   if a boxset is detected, prompt the user to confirm:
   - List of films auto-suggested from disc headers.
   - For each film: TMDb auto-match with manual override (reuse
     metadata-screen UI).
   - Disc assignment matrix: which disc(s) contain this film, which discs
     are shared-extras-only.
   - Save the resolved `BoxsetRelease` into state so rip + organize use it.

4. **Per-disc film context during rip:**
   - When ripping disc N, look up which `BoxsetFilm`(s) live on it.
   - If exactly one: use *that* film's TMDb match + runtime as the
     `(is_movie, movie_runtime)` context for skip/keep heuristics and
     output folder naming. (This alone would fix the Godfather Part III
     bug.)
   - If multiple: pass a list of expected runtimes; main-film detection
     accepts a match against any of them.
   - If shared-extras only: skip main-film logic entirely, treat all
     long titles as featurettes.

5. **Per-disc context during organize:**
   - Files from a disc map to that disc's film(s) by runtime.
   - Each film organizes into its own `Movies/<Title (Year)>/` folder.
   - Variants (Theatrical, Coda, Extended) become separate files within
     the film's folder using existing edition naming.
   - Shared-extras discs route to a configurable destination: per-film
     folder of the most-related film, a shared `Boxset Extras/` folder,
     or the first film's folder. Default TBD — most likely first film
     since Plex collections handle the boxset grouping at the library
     level.

6. **Disc-overview UX:** show film name(s) per disc, e.g.
   - `Disc 1: The Godfather (1972) — 4K`
   - `Disc 2: The Godfather Part II (1974) — 4K`
   - `Disc 3: The Godfather Part III (1990) — 4K (Theatrical + Coda)`
   - `Disc 4: Bonus Features — Blu-ray`

7. **Tactical mitigation while the full feature is being built:**
   - When a disc's titles match the expected `movie_runtime` poorly
     (e.g. all candidates are >10 min off) AND there are 1–2 long
     titles, *don't* fall through to episode classification. Instead,
     pick the longest title as a probable main film and classify the
     rest as extras. This stops the Godfather Part III "everything is
     an episode" failure mode for any boxset, even before per-film
     TMDb is wired up.
   - Add a console/log warning when this fallback fires so users know
     the metadata didn't fully match.

8. **Test fixtures:**
   - Godfather Trilogy 50th Anniversary (3 films, multiple variants on
     Disc 4, shared bonus disc).
   - LOTR Extended Trilogy (3 films, each spans 2 discs theatrical/extras).
   - Star Wars Original Trilogy 4K (3 films, mostly disc-per-film).
   - John Wick 1–4 Collection (4 films, simple disc-per-film).

9. **Share one dvdcompare lookup across all discs in a boxset:**
   - Today each disc in a boxset workflow currently re-runs dvdcompare
     for the same FilmComparison. With the disc cache (30-day TTL) this
     hits cache after the first disc, but the orchestrate flow should
     fetch once per *boxset* up front and re-use that
     `FilmComparison`/`PlannedDisc` set for every subsequent disc swap,
     bypassing the cache layer entirely.
   - Implementation lands naturally with the `BoxsetRelease` data model
     (item 2 above): one fetch produces the full disc map.




