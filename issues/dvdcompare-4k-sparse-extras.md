# dvdcompare 4K Sparse Extras Issue

## Problem

When auto-detect picks "Blu-ray 4K" as the format, the dvdcompare page for the 4K release often has sparse or missing bonus feature data compared to the DVD/Blu-ray page. This causes most bonus features to go unmatched.

## Example: Batman Begins

The 4K release page (fid=44975) lists 3 discs:
- Disc 1 (Blu-ray 4K): "The Film (2160p)" only, no duration
- Disc 2 (Blu-ray): "The Film (1080p)" only, no duration
- Disc 3 (Blu-ray bonus): 4 entries, only 2 with durations
  - The Dark Knight IMAX Prologue (397s)
  - "Behind the Story" (0s, group header, no children)
  - "Additional Footage" (0s, group header, no children)
  - Theatrical Trailer (73s)

The DVD release page (fid=8205) lists 2 discs with full data:
- Disc 1: Movie + Tankman Begins (312s) + trailers
- Disc 2: 8 featurettes with exact durations (856s, 769s, 768s, 498s, 819s, 853s, 781s, 893s)

These durations match the ripped bonus files almost exactly.

## Repro Steps

1. Run snapshot dry run:
   ```
   riplex organize \"path/to/rips/Batman Begins\" ^
     --snapshot "tests\snapshots\Batman Begins.snapshot.json" --year 2005
   ```
2. Observe: auto-detects "Blu-ray 4K", fetches sparse 4K page, only 3 matches out of 13 files.
3. Compare with DVD lookup:
   ```python
   import asyncio
   from riplex.disc_provider import lookup_discs
   # 4K (sparse): 3 discs, Disc 3 has 2 extras with durations
   discs_4k = asyncio.run(lookup_discs("Batman Begins", disc_format="Blu-ray 4K", release="america"))
   # No filter (DVD, complete): 2 discs, Disc 2 has 8 featurettes with durations
   discs_dvd = asyncio.run(lookup_discs("Batman Begins", disc_format=None, release="america"))
   ```

## Root Cause

- The dvdcompare 4K page genuinely has less detail (not a parser bug).
- "Behind the Story" and "Additional Footage" are group headers with no child features listed.
- The 8 individual featurettes only appear on the DVD page.
- `disc_format` auto-detection picks "Blu-ray 4K" because the main movie is hevc:3840x2160.

## Proposed Fix

When we have unmatched files after the initial match, redo the lookup without a format filter and use those extras as supplemental matching targets. The bonus discs in 4K rips contain standard Blu-ray content (mpeg2 480p or vc1 1080p), so the DVD/Blu-ray page's extras data is the correct reference.

Alternative: detect per-disc-group resolution and use different dvdcompare releases for different disc groups. More complex but more precise.

## Affected Rips

Any 4K rip with a bonus disc where the 4K dvdcompare page is sparse. Expected to be common since dvdcompare 4K pages tend to reference standard Blu-ray extras without full breakdowns.
