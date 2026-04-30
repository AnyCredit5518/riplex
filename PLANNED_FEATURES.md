# Planned Features

## Recently Implemented

### Orchestrate Mode

The `plex-planner orchestrate` command is now fully implemented. It handles
the complete multi-disc rip-then-organize workflow in a single session:
insert a disc, auto-detect the title, look up dvdcompare for disc contents,
select which discs to rip, rip each one with disc-swap prompts, then
organize all files into Plex folder structure.

See the orchestrate guide in the docs for full usage details.


## Multi-Resolution Support (4K + Standard Blu-ray)

Many 4K boxsets include standard Blu-ray discs with the same content at 1080p.
Some users may want to rip both so Plex can serve the lower-resolution version
to mobile devices without transcoding.

### Plex support status

**Movies**: Fully supported via "Multi-Version Movies." Multiple files in the
same folder with different suffixes are collapsed into one library item. Plex
auto-selects the best version per device, and many apps let the user choose
manually. Naming convention:

```
/Movies/MovieName (Year)/
   MovieName (Year) - 4K.mkv
   MovieName (Year) - 1080p.mkv
```

**TV Shows**: NOT officially supported. Plex's TV naming documentation does not
mention multi-version episodes. There is no documented way to have 4K and 1080p
versions of the same episode collapse into a single item. Community workarounds
exist (separate libraries, or relying on Plex's automatic version detection
which sometimes works for TV but is undocumented and unreliable).

### Plan

- **Movies**: Support ripping both 4K and standard Blu-ray discs. During
  organize, name them with resolution suffixes so Plex collapses them.
- **TV Shows**: Since Plex does not officially support multi-version TV
  episodes, we should:
  1. Warn the user during rip if they attempt to rip a standard Blu-ray disc
     for a TV show that already has 4K rips.
  2. Offer to skip it with an explanation of why.
  3. If Plex adds official TV multi-version support in the future, revisit.
  4. Optionally allow it anyway for users who use separate libraries or
     other workarounds, but make the limitation clear.


## Other Ideas

(Add future feature ideas here as they come up.)
