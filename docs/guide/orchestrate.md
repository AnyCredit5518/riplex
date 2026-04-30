# Orchestrate

The `orchestrate` command is the primary workflow for ripping and organizing disc sets. It handles the full multi-disc pipeline in a single session: detect the disc, look up metadata, select which discs to rip, rip each one with disc-swap prompts, then organize all files into Plex folder structure.

## Basic usage

Insert a disc and run:

```bash
plex-planner orchestrate --execute
```

This will:
1. Scan optical drives and detect the inserted disc
2. Auto-detect the title from the disc volume label
3. Look up TMDb for canonical metadata
4. Look up dvdcompare for full disc breakdown (contents per disc)
5. Show which discs are in the release and let you select which to rip
6. For each disc: show a live analysis table, rip recommended titles
7. Prompt to swap discs between each disc in the set
8. After all discs are ripped, run the organize pipeline to move files into Plex layout
9. Optionally archive the rip folder

Without `--execute`, orchestrate runs in dry-run mode: it shows what would be ripped and organized without making changes.

## Interactive mode (default)

In interactive mode, orchestrate presents prompts at each decision point:

- **Title confirmation**: auto-detected title shown for confirmation or correction
- **TMDb disambiguation**: if multiple matches, pick the correct one
- **dvdcompare release selection**: choose the regional release (default: America)
- **Disc selection**: pick which discs to rip (skip standard Blu-ray copies, bonus discs, etc.)
- **Disc swap**: after each disc, prompted to insert the next one
- **Archive**: after organize, prompted to archive the rip folder (if `archive_root` is configured)

## Auto mode

Skip all prompts for scripted or scheduled use:

```bash
plex-planner orchestrate --execute --auto
```

Uses best-guess defaults: first TMDb match, first American dvdcompare release, all discs, auto title selection per disc.

## Disc selection

Select specific discs upfront instead of being prompted:

```bash
plex-planner orchestrate --execute --discs 1,3
```

This is useful for 4K sets where you want to skip the standard Blu-ray copies (e.g. rip Disc 1 (4K) and Disc 3 (bonus), skip Disc 2 (1080p duplicate)).

## Resume support

Orchestrate detects previously ripped discs. If the rip folder already has Disc 1, that disc is marked as `[RIPPED]` in the disc listing and excluded from the default selection. You can still explicitly include it with `--discs`.

## Snapshot mode

Scan a disc and write its manifest without ripping:

```bash
plex-planner orchestrate --snapshot
```

Useful to regenerate manifests for files already ripped manually with MakeMKV. The manifest enables the organize phase to use disc metadata for matching without needing ffprobe.

## Live disc analysis

When a disc is inserted, orchestrate shows a table of all titles on the disc with recommendations:

```
Live disc analysis: 300

    #   Duration      Size        Res   Ch  Recommendation
  ---  ---------  --------  ---------  ---  ----------------------------------------
    0    1:56:38   58.3 GB  3840x2160   30  MAIN FILM (4K) - rip this
    1       2:20    0.8 GB  3840x2160    3  Episode (4K) - rip this
    2       5:40    0.2 GB  3840x2160   34  Episode (4K) - rip this
    3    1:56:38   58.3 GB  3840x2160   30  Duplicate of #0 (4K) - skip
```

Title classifications:
- **MAIN FILM**: the longest title, likely the feature film
- **Episode**: mid-length titles (extras, featurettes, episodes)
- **Duplicate of #N**: same duration as another title (lower-resolution copy)
- **Play-all**: concatenation of other titles (skip, organize splits individually)
- **Very short**: under 1 minute (menus, logos, etc.)

## Archive after organize

If `archive_root` is configured in your config file, orchestrate moves the rip folder there after a successful organize:

```toml
archive_root = "/path/to/media/Rips/_archive"
```

In interactive mode, you are prompted before archiving. In `--auto` mode, it archives automatically.

## Full options

See the [CLI Reference](../reference/cli.md#orchestrate) for all available options.
