# dvdcompare Zero-Runtime Film Entries

## Problem

Many dvdcompare listings have `is_film` entries (marked with `*`) that show 0s runtime. When these are on a disc separate from the primary film disc, no target is generated for the file. This causes the main feature file on that disc to go unmatched.

## Examples

Waterworld (Arrow 4K box set, "america" release):
- Disc 1: `* The Film - Theatrical Cut (2160p)` (0s)
- Disc 2: `* The Film - Theatrical Cut` (0s)
- Disc 3: `*The Film - Theatrical Cut` (8107s) -- only disc with runtime
- Disc 4: `*The Film - US TV Cut` (0s)
- Disc 5: `*The Film - "Ulysses" Cut` (0s)

Only Disc 3 has a usable runtime. Discs 1, 2, 4, 5 have 0s, so their film entries produce no match target.

## Impact

- When all disc files are combined (single-folder rip), the matcher has only one movie target and matches the closest file. Other versions of the film go unmatched.
- When discs are in separate subfolders, the matcher cannot generate a movie target for discs with 0s film entries.

## Possible Approaches

1. For 0s film entries, fall back to TMDb runtime as the target duration
2. Use a duration-proximity heuristic: if an unmatched file is within 20% of the movie target duration, treat it as an alternate cut
3. Cross-reference with the longest unmatched file on each `is_film` disc
