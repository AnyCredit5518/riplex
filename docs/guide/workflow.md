# Typical Workflow

This page walks through the recommended end-to-end workflow for ripping a disc set and organizing it into Plex.

## 1. Look up the disc set

Before inserting any disc, run `rip-guide` to see what is on the release:

```bash
plex-planner rip-guide "Planet Earth II"
```

This shows every disc in the set, what episodes and extras are on each disc, and how long each item is. It also gives tips about play-all titles you can rip instead of individual episodes.

## 2. Create the rip folder structure

Add `--create-folders` to pre-create the `_MakeMKV/` subfolders:

```bash
plex-planner rip-guide "Planet Earth II" --create-folders
```

This creates folders like:

```
_MakeMKV/Planet Earth II (2016)/Disc 1/
_MakeMKV/Planet Earth II (2016)/Disc 2/
_MakeMKV/Planet Earth II (2016)/Disc 3/
```

## 3. Rip with MakeMKV

Open MakeMKV and point the output folder at the appropriate `Disc N/` subfolder for each disc. Rip all titles, or follow the play-all tips from the rip guide to rip fewer, larger files.

## 4. Preview the organize plan

Once all discs are ripped, run `organize` in dry-run mode (the default):

```bash
plex-planner organize "_MakeMKV/Planet Earth II"
```

This scans the MKV files, deduplicates, looks up metadata, matches files to episodes and extras, and prints a preview of where each file will be moved.

## 5. Execute

If the preview looks correct, add `--execute`:

```bash
plex-planner organize "_MakeMKV/Planet Earth II" --execute
```

Files are moved (and split if needed) into Plex folder structure. Each file gets tagged so re-runs skip it automatically.

## 6. Handle edge cases

- **Unmatched files**: Use `--unmatched extras` to route remaining files to the `Other/` extras folder
- **Wrong release region**: Use `--release uk` or `--release 2` to pick a different dvdcompare release
- **Re-organize**: Use `--force` to re-process files that were already tagged
- **Debug**: Check `%TEMP%\plex-planner\plex-planner.log` or add `--verbose` for stderr output
