# Unmatched Files Containing Missing Targets as Chapters

## Problem

When a ripped file is a compilation (play-all) that combines multiple segments, and those segments are listed individually as targets on dvdcompare, the compilation file goes unmatched while the individual segments show as "missing content". The chapter-to-missing split logic only runs on files that already have a match, so it never considers these unmatched compilations.

## Example: The Dark Knight (2008)

Two unmatched files on the bonus disc:
- `The Dark Knight Bonus Disc_t00.mkv` (2762s, 6 chapters: 86s, 640s, 625s, 572s, 769s, 71s)
- `The Dark Knight Bonus Disc_t01.mkv` (2759s, 6 chapters: 64s, 597s, 704s, 436s, 891s, 68s)

17 missing dvdcompare targets from Disc 2 ("Focus Points" from "Gotham Uncovered"):
- The Prologue (528s), The New Bat-Suit (287s), Joker Theme (378s), Hong Kong Jump (186s), etc.
- These are individual scene breakdowns that were combined into the two play-all files.

The chapter durations in t00/t01 correspond to subsets of the missing Focus Points segments, but the matcher never tries to split them because they have no initial match.

## Root Cause

The chapter-to-missing split detection (`_try_chapter_splits` in organizer.py) only examines files that are already in the move plan. Unmatched files are excluded from split consideration entirely.

## Proposed Fix

After the initial match pass, check unmatched files with chapters against the missing targets list. If an unmatched file's chapter durations match a subset of missing targets, add it as a split candidate. This is the same logic as `_try_chapter_splits` but applied to unmatched files instead of matched ones.

## Affected Rips

Any disc with "play all" compilation tracks alongside individual segment tracks, where MakeMKV rips both the compilation and individual versions. The individual versions get matched (and the compilation is correctly flagged as a duplicate), but when the individual versions are NOT ripped, only the compilation remains and it goes unmatched.
