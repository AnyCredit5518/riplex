# Metadata source: thediscdb.com (per-disc file/extra data)

Tracking: GitHub issue #19.

## Problem

dvdcompare.net is riplex's only structured disc source. It lists a disc's
episodes and extras with runtimes, but it does **not** map those to the disc's
actual title files, and its extra typing is coarse. In practice that means:

- Extras frequently all collapse into `Featurettes/`, and some extras aren't
  detected at all (reported in #19).
- Matching relies on runtime heuristics, which is fragile when several
  features run within seconds of each other.

[thediscdb.com](https://thediscdb.com) publishes, per physical release, the
**exact source file names** on each disc mapped to their content **titles** and
a proper **type** (episode, deleted scene, featurette, trailer, commentary,
etc.). Example: the Fight Club 2026 4K steelbook Blu-ray
(<https://thediscdb.com/movie/fight-club-1999/releases/2026-steelbook-4k/discs/blu-ray>).

Crucially, the data is open on GitHub — <https://github.com/TheDiscDb/data> —
as structured files, so it can be consumed without scraping HTML.

## Why this is a good fit

riplex already has a clean provider seam: dvdcompare is wrapped behind
`src/riplex/disc/provider.py` producing `PlannedDisc` / `PlannedEpisode` /
`PlannedExtra` objects, and the organizer/matcher consume those. A second
source that yields the same shapes can slot in behind the same seam.

If TheDiscDb maps titles to *source file names*, it can also make matching
**deterministic** (map ripped MKVs by playlist / file identity) instead of
runtime-based, and give each extra a correct Plex folder from its declared
type — directly addressing the "everything becomes Featurettes" complaint.

## Proposed approach

1. **Data access.** Prefer the GitHub `TheDiscDb/data` repo over live HTML.
   Options: (a) fetch the specific release file on demand via the GitHub raw
   API and cache it (mirrors the existing dvdcompare cache in `cache.py`), or
   (b) let the user point at a local clone. Start with on-demand + cache.
2. **New provider.** Add `src/riplex/disc/thediscdb.py` exposing the same
   lookup surface as the dvdcompare provider, returning `PlannedDisc`/
   `PlannedEpisode`/`PlannedExtra` (extend `PlannedExtra.feature_type` mapping
   so TheDiscDb's types resolve to Plex extras folders via
   `organizer._EXTRAS_FOLDER_MAP`).
3. **Selection / precedence.** When both sources match a release, prefer
   TheDiscDb for extras typing + file mapping, fall back to dvdcompare for
   runtimes it lacks. Needs a release-matching step (title + year + edition).
4. **Deterministic matching (stretch).** When TheDiscDb provides source file
   names, match ripped files by name/playlist identity in the matcher before
   the runtime pass.

## Scope / decisions to settle

- **Release identification.** dvdcompare and TheDiscDb slug releases
  differently; we need a mapping/search step (title+year, then edition). How to
  disambiguate multiple releases of the same film is the main design question.
- **Coverage.** TheDiscDb is community-maintained and sparser than dvdcompare
  for TV. Treat it as an *augmenting* source, not a replacement — keep
  dvdcompare as the default and layer TheDiscDb when a release is found.
- **Data schema.** Pin to the `TheDiscDb/data` file format; add a small parser
  + fixtures. Version/format drift should degrade gracefully (fall back to
  dvdcompare), mirroring how the dvdcompare cache invalidates on scraper
  version change.
- **Config.** A `thediscdb_enabled` (or source-priority) config key, off or
  best-effort by default until coverage is proven.
- **Testing.** Unit-test the parser against committed TheDiscDb fixtures;
  extend the matcher/organizer tests to cover file-name-based matching and
  richer extra typing.

## Related

- Provider seam: `src/riplex/disc/provider.py`, `cache.py` (caching pattern).
- Extras typing: `organizer._EXTRAS_FOLDER_MAP` / `_extras_folder`.
- The "everything → Featurettes" symptom this would improve is the core of #19.
