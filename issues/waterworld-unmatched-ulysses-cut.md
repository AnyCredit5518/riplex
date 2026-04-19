# Waterworld Unmatched "Ulysses" Cut

## Problem

`Waterworld_t05.mkv` (10561s, 1080p) is the extended "Ulysses" cut of Waterworld from Disc 5 of the Arrow 4K box set. It goes unmatched because dvdcompare lists the "Ulysses" cut with 0s runtime, so no target is generated for it.

## Details

dvdcompare lists:
- Disc 5: `*The Film - "Ulysses" Cut` (0s)

The asterisk correctly sets `is_film=True` on Disc 5, and the "The Film" prefix causes it to be skipped as a target (since it represents the film itself). However, no movie target is generated for this alternate cut because the single synthetic movie target (`Waterworld (movie)`) only covers the theatrical cut.

The file is 10561s (~176 min) vs the theatrical cut at 8109s (~135 min), so it cannot match the movie target either.

## Possible Approaches

1. Generate additional movie targets for discs with `is_film=True` that have different cut names (e.g., "Waterworld - Ulysses Cut")
2. Support an `--extras` or `--cuts` flag that treats alternate cuts as separate output files
3. Accept that alternate cuts require manual handling or a `--title` override

## Affected Rips

Any multi-cut box set where dvdcompare lists alternate cuts with 0s runtime (common for extended/director's cuts on separate discs).
