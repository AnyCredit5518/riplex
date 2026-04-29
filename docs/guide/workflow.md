# Typical Workflow

This page walks through the recommended end-to-end workflow for ripping a disc set and organizing it into Plex.

## 1. Look up the disc set

Before inserting any disc, run `rip-guide` to see what is on the release:

```bash
plex-planner rip-guide "Planet Earth II"
```

This shows every disc in the set, what episodes and extras are on each disc, and how long each item is. It also gives tips about play-all titles you can rip instead of individual episodes.

If a disc is already in the drive, add `--drive` to include live disc analysis:

```bash
plex-planner rip-guide "Planet Earth II" --drive 0
```

This reads the disc's title list and cross-references it against dvdcompare metadata, showing which titles to rip and which to skip (play-all compilations, lower-resolution duplicates, etc.).

## 2. Create the rip folder structure (optional)

Add `--create-folders` to pre-create the rip subfolders under your output root:

```bash
plex-planner rip-guide "Planet Earth II" --create-folders
```

This creates folders like:

```
<output_root>/_MakeMKV/Planet Earth II (2016)/Disc 1/
<output_root>/_MakeMKV/Planet Earth II (2016)/Disc 2/
<output_root>/_MakeMKV/Planet Earth II (2016)/Disc 3/
```

This step is optional when using `plex-planner rip`, which creates output folders automatically.

## 3. Rip the disc

Use the `rip` subcommand to read the disc, auto-select the right titles, and rip them:

```bash
plex-planner rip "Planet Earth II" --drive 0
```

This will:
1. Read the disc via makemkvcon
2. Confirm the auto-detected title (you can correct it at the prompt)
3. Look up metadata on TMDb (with disambiguation if multiple matches exist)
4. Look up disc metadata on dvdcompare (with release selection if multiple regions)
5. Show a disc analysis table with rip recommendations
6. Prompt for confirmation, then rip the selected titles

Add `--yes` to skip the final rip confirmation prompt. Use `--auto` to also skip all interactive selection prompts (title, TMDb, release). Use `--titles 1,2,3` to override the auto-selection, or `--all` to rip everything. Add `--organize` to automatically run the organize step after ripping.

Repeat for each disc in the set, swapping discs between runs.

> **Fallback**: You can also rip manually with MakeMKV. Point the output folder at the appropriate `Disc N/` subfolder and rip all titles, or follow the play-all tips from the rip guide to rip fewer, larger files.

## 4. Preview the organize plan

Once all discs are ripped, run `organize` in dry-run mode (the default):

```bash
plex-planner organize "path/to/rips/Planet Earth II"
```

This scans the MKV files, deduplicates, looks up metadata, matches files to episodes and extras, and prints a preview of where each file will be moved.

## 5. Execute

If the preview looks correct, add `--execute`:

```bash
plex-planner organize "path/to/rips/Planet Earth II" --execute
```

Files are moved (and split if needed) into Plex folder structure. Each file gets tagged so re-runs skip it automatically.

## 6. Handle edge cases

- **Unmatched files**: Use `--unmatched extras` to route remaining files to the `Other/` extras folder
- **Wrong release region**: Use `--release uk` or `--release 2` to pick a different dvdcompare release
- **Re-organize**: Use `--force` to re-process files that were already tagged
- **Debug**: Check `%TEMP%\plex-planner\plex-planner.log` or add `--verbose` for stderr output
