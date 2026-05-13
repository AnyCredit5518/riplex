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

10. **Follow per-film page links for linked discs in a boxset release.**

    *Discovered while ripping BTTF 40th Anniversary Trilogy after the
    quoted-title disc-header parser landed (dvdcompare-scraper 0.1.15).*

    ### Symptom

    On the boxset's release page (e.g. *Back to the Future / Blu-ray 4K
    / 40th Anniversary Trilogy*), only the **primary film's** discs list
    their extras inline. The discs belonging to the other films in the
    boxset appear as bare headers with **no extras listed**, e.g.:

    ```
    DISC 1 "Back to the Future" (Blu-ray 4K)   ← inline extras (32 items)
    DISC 2 "Back to the Future" (Blu-ray)      ← inline extras (38 items)
    DISC 3 "Back to the Future Part II" (Blu-ray 4K)   ← (no content listed)
    DISC 4 "Back to the Future Part II" (Blu-ray)      ← (no content listed)
    DISC 5 "Back to the Future Part III" (Blu-ray 4K)  ← (no content listed)
    DISC 6 "Back to the Future Part III" (Blu-ray)     ← (no content listed)
    DISC 7 (Blu-ray)                            ← inline extras (26 items)
    DISC 8 (Blu-ray)                            ← inline extras (5 items)
    ```

    This is visible in the current disc-overview screen: discs 3-6 show
    `(no content listed)`. Without per-disc content riplex falls back
    to duration-only heuristics for those discs and can't classify
    featurettes vs. main film, can't match titles to specific extras,
    and can't surface what the user should expect to be on each disc.

    ### Root cause in dvdcompare HTML

    On the boxset release page, each non-primary disc header is wrapped
    in an `<a href="film.php?fid=NNNN">` linking to **that film's own
    dvdcompare comparison page**:

    ```html
    <b>DISC ONE "Back to the Future" (Blu-ray 4K)</b>
    <br>* The Film
    <br>Q&amp;A Commentary by Director Robert Zemeckis ... (2002)
    ... 30 more rows of inline extras ...

    <a href="film.php?fid=16875"><b>DISC TWO "Back to the Future" (Blu-ray)</b></a>
    <br>* The Film
    <br>Q&amp;A Commentary by Director Robert Zemeckis ... (2002)
    ... 36 more rows of inline extras ...

    <a href="film.php?fid=55540"><b>DISC THREE "Back to the Future Part II" (Blu-ray 4K)</b></a>
    <br>                                          ← no rows follow
    <a href="film.php?fid=16876"><b>DISC FOUR "Back to the Future Part II" (Blu-ray)</b></a>
    <br>
    <a href="film.php?fid=55541"><b>DISC FIVE "Back to the Future Part III" (Blu-ray 4K)</b></a>
    <br>
    <a href="film.php?fid=16877"><b>DISC SIX "Back to the Future Part III" (Blu-ray)</b></a>
    <br>
    <b>DISC SEVEN (Blu-ray)</b>
    <br>"The Hollywood Museum Goes Back to the Future" ...
    ```

    Two distinct patterns are present in this single release:

    - **Linked-and-listed** (e.g. DISC TWO `fid=16875`): the header is
      a link, but extras are *also* listed inline. Following the link
      is optional — the inline data is authoritative for this release.
    - **Linked-and-empty** (e.g. DISCs 3-6): the header is a link with
      no inline extras at all. The link is the *only* way to get the
      disc's contents.

    Bonus discs (7, 8) and the primary film's discs (1, 2) are
    **inline-only** with no link.

    ### Scope

    This affects **any multi-film boxset** on dvdcompare where the
    individual films also have standalone pages. Confirmed patterns:

    - BTTF 40th Anniversary Trilogy (6 feature discs + 2 bonus).
    - 35th Anniversary Ultimate Trilogy (3 feature discs + 1 bonus) —
      same structure, fewer discs.
    - Same structure expected for Godfather Trilogy 50th Anniversary,
      LOTR Extended, Star Wars Original Trilogy 4K, Indiana Jones,
      Mission: Impossible Collections, etc.

    Single-film boxsets (Inception, The Thing) do **not** have this
    problem — they have only one film page, so all discs are
    inline-only with no cross-links.

    ### Plan

    1. **Scraper: surface the per-disc link.**

       Add two optional fields to `dvdcompare.models.Disc`:

       ```python
       linked_film_id: int | None = None    # 16875 in href="film.php?fid=16875"
       linked_film_url: str | None = None   # absolute URL of the linked page
       ```

       Update `parse_extras` to detect when the surrounding `<a href>`
       of a `<b>DISC ...</b>` header points at `film.php?fid=NNNN` and
       record those values on the `Disc`. Leave both `None` when no
       link is present.

       This is a parser-only change, similar to the quoted-title work.
       No new HTTP calls in the scraper itself.

    2. **Scraper: optional enrichment API.**

       Add a new method (or `find_film` flag) that, given a
       `FilmComparison` whose discs have linked-but-empty extras,
       resolves each link to the corresponding `FilmComparison`/release
       and **back-fills** the empty `Disc.features` list from the
       linked page.

       Resolution rule when fetching a linked film page: find the
       release whose name matches the *originating* boxset release name
       (e.g. *"40th Anniversary Trilogy"*), then find the disc within
       it whose `(number, format, title)` matches the linked header,
       and copy its features.

       This is opt-in because it's expensive (1 extra HTTP request per
       linked disc — up to 4 for BTTF) and most callers only want the
       single-page view. The throttle layer in riplex already serializes
       these.

    3. **Riplex: invoke enrichment when a boxset is detected.**

       When `_convert_release` sees any `Disc` with no features but a
       `linked_film_id`, call the enrichment API once (after the user
       has confirmed the release) to back-fill all linked discs, then
       proceed with normal classification. The cache key for the parent
       boxset should incorporate the enrichment state so we don't keep
       re-fetching when re-opening the same release.

       This integrates with item 9 (one dvdcompare lookup per boxset):
       enrichment runs once up front and the result is cached.

    4. **Disc-overview UX.**

       Replace `(no content listed)` for linked-and-empty discs with
       `(loading from linked page…)` while enrichment runs, then refresh
       the disc summary once back-filled. If enrichment fails (HTTP
       error, link broken, release name not found on linked page), fall
       back to `(no content listed — see <linked_film_url>)` and keep
       the disc rip-able with duration-only heuristics.

    5. **Negative cache / failure modes.**

       - Linked page returns 404 / non-2xx → negative-cache like any
         dvdcompare failure (existing infrastructure).
       - Linked page doesn't contain a release with the matching name →
         log warning, leave features empty, don't crash. This will
         happen for re-released boxsets where the per-film page has a
         narrower release list than the boxset page.
       - Linked page's matching release has a disc with same number but
         different `(format, title)` → keep both candidates' features as
         a best-effort merge.

    6. **Tests.**

       - Parser: verify `linked_film_id` and `linked_film_url` are
         populated from `<a href="film.php?fid=NNNN"><b>DISC ...</b></a>`
         wrappers, and remain `None` for plain `<b>DISC ...</b>`
         headers.
       - Parser: linked-and-listed (DISC TWO style) still produces the
         inline features alongside the link.
       - Scraper enrichment: given a parent release and a synthetic
         second `FilmComparison` containing the matching release, the
         enrichment back-fills features into the placeholder disc.
       - Riplex `_convert_release`: a disc with `linked_film_id` set and
         empty features triggers the enrichment hook (mocked) and then
         classifies normally.

    7. **Out of scope / future.**

       Cross-boxset deduplication (the *same* per-film page is referenced
       by multiple boxset releases, e.g. both 35th and 40th Anniversary
       link to `fid=16875` for BTTF 1 Blu-ray): the existing positive
       cache already covers this once the linked page has been fetched
       once. No special handling needed.





