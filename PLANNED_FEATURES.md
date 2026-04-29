# Planned Features

## Orchestrate Mode (Rip + Organize Pipeline)

A new `plex-planner orchestrate` command (or `rip --orchestrate`) that handles
the full multi-disc rip-then-organize workflow in a single session.

### How it would work

1. User inserts Disc 1 and runs orchestrate.
2. plex-planner identifies the title, looks up dvdcompare, and sees how many
   discs the release has (e.g. "4 discs" for The Green Planet UK release).
3. Rips the current disc.
4. After each disc, prompts: "Rip next disc (Disc 2: Desert Worlds, Human
   Worlds, On Location), or finish and organize now?"
   - The prompt should describe what content is on the next disc so the user
     knows which physical disc to insert, especially useful for boxsets where
     disc numbering may not be printed clearly.
   - Users often skip standard Blu-ray copies (Discs 3-4 in a 4K set) or
     bonus discs, so ending early is a first-class option.
5. When the user chooses to finish, runs organize on the complete rip folder.

### Key details

- dvdcompare already provides per-disc content listings, so we know what
  episodes/features are on each disc.
- The disc number in the volume label (e.g. "The Green Planet - Disc 2") can
  be cross-referenced against the dvdcompare disc listing to confirm the right
  disc is inserted.
- If the user inserts the wrong disc, warn them and ask again.
- Support resuming: if the rip folder already has Disc 1, detect that and
  start from Disc 2.
- Support skipping individual discs, not just stopping early. For example, a
  UHD Blu-ray set might have Disc 1 (4K), Disc 2 (standard Blu-ray), and
  Disc 3 (bonus features). A user might want to rip 1, skip 2, rip 3. Or
  skip 1, rip 2, skip 3. The prompt after each disc should offer "rip next
  disc," "skip next disc," or "finish and organize."


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
