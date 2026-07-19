# riplex v1.0.0

**The first stable release.** v1.0.0 consolidates riplex's box-set and TV-series
support, hardens episode matching, adds a comprehensive automated test suite so
the flows that matter stay working as the project grows, and makes upgrades
painless with one-click in-place updates on Windows.

Until now every disc was treated as a standalone rip, and updating meant
re-downloading the app each release. This release lets riplex understand a whole
box set at once — detecting the *works* inside a release, grouping the discs that
belong to each, and routing every work to its correct Plex destination in a
single guided session — and then keeps itself up to date automatically.

## Headline features

### Multi-work box sets

A release that contains several distinct works — several films, or films plus a
TV series — is detected as *multiple works* instead of one. Each work gets its
own title selection, its own rip grouping, and its own Plex target, so a mixed
box set is ripped and filed correctly in one pass:

• Disc grouping splits on dvdcompare's per-film hyperlinks (`pointer_fid`) rather than a coarse "is this a film" guess, so a bonus-films disc forms its own group and the main features stay separate.
• The Select Titles screen shows each work's rip output separately, so you can see exactly which files belong to which movie or show.
• Full CLI parity: `riplex orchestrate` and `riplex organize` route multi-work releases the same way the GUI does, through the shared flow logic.

### Multi-season TV series

Complete-series sets that span several seasons are ripped season by season:

• A **Season Select** screen (GUI) and season prompt (CLI) assign each disc to its season.
• TV rips nest automatically under `Season NN/`, and specials land in `Season 00`.
• Season labels and chips appear throughout the Disc Overview, so a 12-disc set is easy to keep track of.

### Guided resume across a whole set

Every session writes a `_riplex_session.json` marker capturing the full plan, so
you can rip a few discs, come back later, and pick up exactly where you left off:

• Resume from *any* disc of a multi-work or multi-season set — not just the next in sequence.
• `riplex orchestrate` (CLI) resumes from the marker with GUI parity, via a shared `resume.py` adapter.
• `riplex organize` discovers the marker and fans out across every work in the set.

### Metadata persisted per rip

Rip manifests record the exact TMDb and dvdcompare ids you confirmed at rip time.
When you organize (or resume) a ripped disc, riplex reuses those ids and skips
the metadata pickers entirely — no re-searching, no risk of picking a different
release the second time.

### Smarter, more resilient TV episode matching

Matching ripped titles to episodes used to be a runtime guessing game that falls
apart when episodes run within seconds of each other — or when a metadata
listing is simply wrong. Now:

• dvdcompare's episode listing is cross-referenced against the TMDb episode list.
• When a disc's episode-length titles line up 1:1 with the episode list, they're assigned by **disc position** rather than by runtime, so a single wrong dvdcompare runtime can't orphan an episode or let a same-runtime neighbour steal its slot.
• Organize honors the rip-time season/episode classification and no longer collides identically-named files across different discs.
• Over-length titles are labeled **Unmatched content** and stay visible instead of being forced into the wrong slot.

### Seamless in-place updates (Windows)

When a new version is available, the update screen offers **Update & Restart**:
riplex downloads the new build, **verifies its SHA-256 checksum**, swaps the
running `.exe` in place, and relaunches — no re-downloading and no repeated
SmartScreen approval. It only runs from a writable install folder (otherwise it
falls back to the browser download), and every release now publishes `.sha256`
checksums for its assets.

> Note: this applies going forward. Upgrading *to* v1.0.0 from an older build
> still uses the browser download (the old build doesn't know how to self-update);
> from v1.0.0 onward, updates are one click.

### Auto-eject after ripping

The disc ejects automatically once a rip finishes, so you can swap discs — or
just know it's done — without reaching for the drive. On by default; set
`auto_eject = false` in the config to disable.

## Reliability & testing

v1.0.0 adds a substantial automated safety net so future changes don't quietly
break the flows you rely on:

• **Headless GUI integration tests** drive the full desktop wizard through mocked disc / TMDb / dvdcompare scenarios, asserting every screen renders and hands off correctly without touching a real drive or the network.
• **CLI integration tests** run the real argument parser and command dispatch for `organize` and `lookup`.
• **Real-world fixtures** are generated from archived rips and classified by media type (movie, mini-series, series), so new rips can grow the protected-scenario set over time.
• Cancelling a rip now returns to the **current** disc's Insert Disc screen (retry / skip / eject) instead of skipping ahead, and doesn't mark the disc as ripped.
• Duplicate-title extras no longer clobber their episode's destination during organize.

## Minor improvements

• "Currently loaded" disc dropdown on the Disc Overview for quickly switching context.
• "Organize into Library" shortcut appears once every disc in the set has been ripped.
• Hidden-discs banner explains any discs the plan intentionally skips, and the primary-work slot shows its runtime.
• "View on dvdcompare.net" link shown once a release has been matched.
• Interactive title-selection editor at the CLI Proceed prompt, so you can adjust picks before the rip starts.
• Every `orchestrate` disc routes through an Insert Disc scan-confirm step for consistent behavior.
• Ctrl-C exits cleanly (exit code 130, no traceback, no orphaned `makemkvcon` process).

## Bug fixes

• Duplicate **Quit** buttons on the rip-complete summary and Insert Disc screens.
• False "multiple films" alert on Select Titles, with a confirmed movie title and clearer section headers.
• Ctrl-C at a prompt no longer behaves like pressing Enter.
• Movie picks filter to just the movie disc(s), on both fresh and resumed sessions.
• Organize fuzzy-matches dvdcompare episode titles against TMDb, and reads title/season from the rip manifest for season-nested output.
• Organize no longer crashes after a resumed rip.
• Organize Rips scan-results footer anchors to the bottom, and its Back button walks up the flow instead of dropping to Welcome.
• `detect_disc_format` recognizes standard-definition DVDs.
• Linked-film autofill strips dvdcompare format markers, and the main feature is no longer misclassified as a play-all title.
• The dvdcompare cache auto-invalidates when the scraper version changes, and auto-lookup no longer picks the wrong franchise.

## ⚠️ Breaking change

Disc-group ids changed from the old `main_1` / `film_31` scheme to
`disc_1` / `discs_1_4` / `disc_31`. A session saved by an earlier version will
not resume — **start a fresh session after upgrading**.

## Full changelog

See [docs/changelog.md](https://github.com/AnyCredit5518/riplex/blob/v1.0.0/docs/changelog.md)
for the per-section breakdown, and the auto-generated commit list below for
every commit since v0.9.8.
