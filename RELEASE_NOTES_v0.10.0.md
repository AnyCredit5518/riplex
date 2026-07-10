# riplex v0.10.0

This release makes riplex understand a whole box set at once. Until now every
disc was treated as a standalone rip: a set that bundles several films, or a
complete multi-season TV series, had to be ripped one disc at a time and sorted
out by hand afterward. v0.10.0 detects the *works* inside a release, groups the
discs that belong to each one, and routes every work to its correct Plex
destination in a single guided session — in both the GUI and the CLI.

It also remembers everything: the plan, your metadata picks, and where each rip
came from, so you can stop after any disc and resume the set later without
re-picking anything.

## Headline features

### Multi-work box sets

A release that contains several distinct works — several films, or films plus a
TV series — is now detected as *multiple works* instead of one. Each work gets
its own title selection, its own rip grouping, and its own Plex target, so a
mixed box set is ripped and filed correctly in one pass:

• Disc grouping now splits on dvdcompare's per-film hyperlinks (`pointer_fid`) rather than a coarse "is this a film" guess, so a bonus-films disc forms its own group and the main features stay separate.
• The Select Titles screen shows each work's rip output separately, so you can see exactly which files belong to which movie or show.
• Full CLI parity: `riplex orchestrate` and `riplex organize` route multi-work releases the same way the GUI does, through the shared flow logic.

### Multi-season TV series

Complete-series sets that span several seasons are now ripped season by season:

• A new **Season Select** screen (GUI) and season prompt (CLI) assign each disc to its season.
• TV rips nest automatically under `Season NN/`, and specials land in `Season 00`.
• Season labels and chips appear throughout the Disc Overview, including on the leading discs of each season, so a 12-disc set is easy to keep track of.

### Guided resume across a whole set

Every session now writes a `_riplex_session.json` marker that captures the full
plan for the release. That means you can rip a few discs, come back later, and
pick up exactly where you left off:

• Resume from *any* disc of a multi-work or multi-season set — not just the next one in sequence.
• `riplex orchestrate` (CLI) resumes from the session marker with GUI parity, via a single shared `resume.py` adapter.
• `riplex organize` discovers the session marker and fans out across every work in the set.

### Metadata persisted per rip

Rip manifests now record the exact TMDb and dvdcompare ids you confirmed at rip
time. When you organize (or resume) a ripped disc, riplex reuses those ids and
skips the metadata pickers entirely — no re-searching, no risk of picking a
different release the second time around.

### Smarter TV episode matching

Matching ripped titles to episodes used to be a runtime guessing game, which
falls apart when 15 episodes all run within seconds of each other. Now:

• dvdcompare's episode listing is cross-referenced against the TMDb episode list.
• Episodes are assigned deterministically from their rip-time classification (first-fit) instead of nearest-runtime.
• Organize honors the rip-time season/episode classification and no longer collides identically-named files (`C2_t01.mkv`) across different discs.
• Over-length titles are labeled **Unmatched content** and stay visible instead of being forced into the wrong slot.

## Minor improvements

• "Currently loaded" disc dropdown on the Disc Overview for quickly switching context.
• "Organize into Library" shortcut appears once every disc in the set has been ripped.
• Hidden-discs banner explains any discs the plan intentionally skips, and the primary-work slot now shows its runtime.
• "View on dvdcompare.net" link shown once a release has been matched.
• Interactive title-selection editor at the CLI Proceed prompt, so you can adjust picks before the rip starts.
• Every `orchestrate` disc now routes through an Insert Disc scan-confirm step for consistent behavior.
• Softer disc-mismatch wording, and the release picker shows the matched dvdcompare film.
• Ctrl-C now exits cleanly (exit code 130, no traceback, no orphaned `makemkvcon` process).

## Bug fixes

• Duplicate **Quit** buttons on the rip-complete summary and Insert Disc screens.
• False "multiple films" alert on Select Titles, with a confirmed movie title and clearer section headers.
• Ctrl-C at a prompt no longer behaves like pressing Enter.
• Movie picks now filter to just the movie disc(s), on both fresh and resumed sessions.
• Organize fuzzy-matches dvdcompare episode titles against TMDb, and reads title/season from the rip manifest for season-nested output.
• Organize no longer crashes after a resumed rip.
• `detect_disc_format` recognizes standard-definition DVDs.
• Linked-film autofill strips dvdcompare format markers, and the main feature is no longer misclassified as a play-all title.
• The dvdcompare cache auto-invalidates when the scraper version changes, and auto-lookup no longer picks the wrong franchise.

## ⚠️ Breaking change

Disc-group ids changed from the old `main_1` / `film_31` scheme to
`disc_1` / `discs_1_4` / `disc_31`. A session saved by an earlier version will
not resume — **start a fresh session after upgrading**.

## Full changelog

See [docs/changelog.md](https://github.com/AnyCredit5518/riplex/blob/v0.10.0/docs/changelog.md)
for the per-section breakdown, and the auto-generated commit list below for
every commit since v0.9.8.
