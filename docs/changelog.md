# Documentation Changelog

All notable changes to the riplex documentation are recorded here.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## Unreleased

### Added

- **CLI `rip` and `orchestrate` now offer an interactive title-selection editor at the final confirmation prompt.** Previously the CLI printed a static `Will rip N title(s) [...]` line and only offered `y/n` at `Proceed?` — if the auto-recommendation was wrong you had to abort and re-run with `--titles 1,3,5`, which meant remembering the indices from the previous output. The prompt now reads `Proceed? [Y/n/e(dit)]`; pressing `e` opens a table that lists every title on the disc with an `[x]`/`[ ]` prefix reflecting the current selection, the makemkvcon index, duration, size, and the analyzer's classification label (`MAIN FILM`, `EPISODE S01E02`, `SKIP: junk`, etc.). Accepted commands per line: comma-separated indices or ranges (`1,3-5,7`) toggle each listed index, `all` / `none` reset the whole set, `default` restores the analyzer's recommendation, `done` (or a blank line) accepts, and `cancel` aborts the edit and returns to `Proceed?`. The prompt loops so you can peek at the picker, cancel back out to `Proceed?` without changing anything, or accept an empty selection to skip the disc entirely (in orchestrate) or bail out (in single-disc `rip`). Non-interactive runs (`--yes`, `--auto`, piped stdin) short-circuit the entire flow — the existing behavior for scripted use is unchanged, and `--titles` / `--all` still work as pre-flight overrides. Two new helpers in `riplex/ui.py` (`prompt_proceed_or_edit`, `prompt_rip_selection`) plus a small `_parse_index_spec` parser back the picker; both `riplex_cli/commands/rip.py` and `riplex_cli/commands/orchestrate.py` were updated to use them. Tests: 29 new cases in `tests/test_ui.py` covering the range parser (10 cases including reversed ranges, missing-index skips inside a range, and unknown-index errors), the `Y/n/e` prompt (6 cases covering all three outcomes plus EOF), and the picker itself (13 cases covering the non-interactive fast path, empty-titles fast path, `done`/Enter/`cancel`, single-index and range toggles, `all`/`none`/`default`, invalid-input re-prompting, EOF, and classification labels rendering into stdout). 903 total pass.

- **GUI now has a Season Select screen between the TMDb match and the release picker for multi-season TV shows.** Mirrors the CLI's new season prompt: on a bare volume label like ``PSYCH`` (no ``_S2_D1`` tokens) the app used to send the plain title ``Psych`` straight to dvdcompare and match the top-level *Psych* film page instead of ``Psych: Season 2 (TV) (DVD)``, then hand the user a release picker whose regions all belonged to the wrong film. The metadata screen now navigates to a new ``season_select`` screen after the user confirms a TV match; the screen reads ``state["show_detail"]`` (already fetched by the metadata screen in a background thread) and shows a radio list of non-special seasons. On confirm, ``state["season_number"]`` is set and any stale dvdcompare state is cleared — the release screen then queries with ``"<title>: Season N"`` (via its existing ``_current_search_title`` bias) and lands on the right film. The screen auto-skips (navigates immediately to ``release`` with no user interaction) in three cases: (1) ``state["season_number"]`` is already set — from a labelled disc like ``PSYCH_S2_D1``, from the folder picker parsing ``.../Psych (2006)/Season 02/``, or from a session marker resume; (2) the TMDb match is a movie; (3) the show has one or fewer non-special seasons (mini-series like *Planet Earth II*: TMDb models it as Season 0 ``Specials`` + Season 1 ``Miniseries``, and its dvdcompare page is a single film covering all discs, so no season bias is desired). If the user reaches the screen before ``show_detail`` is done loading, a spinner is shown and the screen re-renders every 200 ms until the data arrives. The prefill fast-path (organize re-visit of an existing rip folder with a saved ``tmdb_source_id``) also routes through ``season_select`` — which auto-skips since the season is either encoded in the folder structure or the source is a mini-series. Tests: 10 new cases in ``tests/test_season_select_screen.py`` covering all three auto-skip paths, the picker path (only non-special seasons rendered, ``Volume One``-style names shown, redundant ``(Season N)`` suffixes suppressed), the ``_on_next`` write and stale-dvdcompare-cleanup, the defensive no-selection no-op, back navigation, and the loading state. The existing ``test_metadata_screen.py`` case that asserted a TV pick navigates to ``release`` was updated to assert ``season_select``. 874 total pass.

- **CLI now prompts for a season on multi-season TV shows and uses it to bias the dvdcompare query.** Previously ``riplex rip`` / ``riplex orchestrate`` would take the auto-detected volume-label title (e.g. bare ``PSYCH`` from a *Psych* Season 2 disc — no season/disc tokens on the label), send it straight to TMDb, and then send it straight to dvdcompare — which would happily match the top-level *Psych* page instead of ``Psych: Season 2 (TV) (DVD)``. When the show is TV and no ``--season`` was passed and the run is interactive, ``lookup_metadata`` now fetches ``ShowDetail`` between ``pick_match`` and ``_plan_show`` and shows a season picker built from ``ShowDetail.seasons``. The picker filters out Season 0 (Specials — never a rippable disc primary content) but the plan itself still keeps Season 0 so extras on the disc that match a curated Special can be routed to ``Season 00/S00Exx`` at organize time. Mini-series (one non-special season on TMDb — Planet Earth II is the canonical example: Season 0 = "Specials", Season 1 = "Miniseries") are handled implicitly with no prompt and no ``season_number`` set, because their dvdcompare films are not listed per-season. The chosen season propagates to the existing ``request.season_number is not None`` branch in ``lookup_metadata`` which appends ``: Season N`` to the dvdcompare query, so film-page selection becomes deterministic on shows with per-season dvdcompare pages. The prompt is silently skipped when non-interactive (CI/pipes) so scripted runs are unaffected. ``SeasonMetadata`` gained a ``name: str`` field (populated from TMDb's per-season ``name`` such as ``Miniseries`` or ``Specials``) so the picker can show ``Season 1 (Miniseries) — 6 episodes`` when TMDb's season name differs from the default ``Season N`` label. Tests: 3 new cases in ``tests/test_lookup.py`` (multi-season prompt path, mini-series skip path, non-interactive skip path) plus one new ``test_plan_tv_show_with_season_number_keeps_specials`` in ``tests/test_planner.py`` verifying Season 0 survives the season filter.

### Changed

- **``_plan_show`` keeps Season 0 (Specials) in the plan even when ``request.season_number`` is set.** Previously the season-filter in ``metadata/planner.py`` line 155 dropped every season except the requested one, including Season 0. That meant ``riplex rip --season 2`` for *Psych* built a plan with no Season 0 metadata, so the organizer's Season 00 title-match path in ``organizer.py`` line 622 always missed and every extra fell through to ``Featurettes/``. The filter now keeps ``sm.season_number == 0`` unconditionally alongside the requested season — extras on the disc that title-match a curated TMDb special land in ``Season 00/S00Exx - Title.mkv`` as intended, while extras with no match still fall through to ``Featurettes/`` (unchanged). All 864 tests pass; the pre-existing ``test_plan_tv_show_filters_to_requested_season`` still asserts ``[6]`` because its fixture doesn't include Season 0. This change is a prerequisite for the season prompt above: without it, prompting the user for a season would silently downgrade extras routing.

### Changed

- **Release picker now shows the matched dvdcompare film above the choices.** The `select_dvdcompare_release` prompt used to say only ``Select a dvdcompare release:`` followed by region names, giving no visibility into which dvdcompare film page produced them. A first pass on the *Psych* Season 2 disc surfaced the ambiguity: the on-disc volume label was just ``PSYCH``, so the lookup could plausibly land on the top-level *Psych* page, on ``Psych: Season 1 (TV) (DVD)``, on the season 2 page, or on the complete-series box — and the picker gave the user no way to tell before committing to a region. The function now emits ``Matched dvdcompare film: <title> (<year>) [film #<fid>]`` to stderr before it decides anything else (works for both the interactive picker path and the auto-pick / single-release paths so logs also carry the info), and the picker header itself now reads ``Select a dvdcompare release for <title>:`` so the film context is repeated at the choose-a-region step. The organize CLI walkthrough (`docs/cli-guide/organize.md`) was updated to show the new two-line prompt.

### Added

- **Rip manifests now record the TMDb and dvdcompare identifiers used at rip time so the organize flow can skip both pickers.** When the GUI writes a `_rip_manifest.json` after a successful rip, three new optional fields are appended: `tmdb_source_id` (the ``"tv:1447"`` / ``"movie:12345"`` form that ``TmdbProvider.get_movie_detail`` / ``get_show_detail`` accept directly), `dvdcompare_film_id` (the numeric ``fid`` used by ``DiscProvider.fetch_film_by_id``), and `dvdcompare_release_name` (the human-readable name that pairs a specific release to its film). On organize, the folder-picker now runs `read_prefill_ids_from_manifests` on the picked folder and stashes those three under `_prefill_tmdb_source_id` / `_prefill_dvdcompare_film_id` / `_prefill_dvdcompare_release_name` in state; the metadata screen consumes the TMDb id (fetching movie/show details straight from the API and synthesising a ``MetadataSearchResult`` without going through the search picker), and the release screen consumes the film-id + release-name pair (fetching the film by id and matching one release by name before jumping straight to organize-preview). Both screens show a brief "Restoring the saved match…" spinner during the background fetch instead of the picker. On any failure (network error, TMDb id merged away, dvdcompare release renamed) each screen flips a one-shot ``_prefill_*_failed`` flag, drops the corresponding prefill state, and falls back to the normal picker with an amber warning banner explaining that the saved match no longer resolves. The CLI ``riplex rip`` and ``riplex orchestrate`` commands write the same three fields (``lookup_metadata`` now returns ``dvdcompare_film_id`` on ``LookupResult`` by splitting the previous ``fetch_and_select_release`` call into an explicit ``DiscProvider.fetch_film`` + ``select_dvdcompare_release`` so the film's ``film_id`` propagates through). Older manifests written before this change simply omit the fields and fall through to the current picker flow. Tests: `TestBuildRipManifestIdentityFields`, `TestBuildSnapshotManifestIdentityFields`, `TestReadPrefillIdsFromManifests` (10 cases in a new `tests/test_manifest_prefill_ids.py`) cover both writing and reading including string-typed and malformed `dvdcompare_film_id` values, plus a new `test_lookup_metadata_captures_dvdcompare_film_id` in `tests/test_lookup.py`.

### Changed

- **Organize's title/season block is now clearer about where its values came from.** The season input's label went from ``Season override (TV only, optional)`` to just ``Season number`` with an inline ``Leave blank for movies.`` helper — "override" implied there was a value to replace, which was misleading when the field was empty or auto-filled from the manifest. A small badge above the title field now says either ``From rip manifest`` (green check icon) when the values were read from a riplex-produced ``_rip_manifest.json``, or ``Guessed from folder name — please verify`` (amber pencil icon) otherwise, so the user knows at a glance whether the pre-filled values are trustworthy or best-guess. The disc-summary line ("Scanned 4 discs, 32 files (DVD)") now appends the media type when known — ``(DVD, TV)`` or ``(Blu-ray, Movie)`` — again only for manifest-backed sources; non-riplex sources omit the type because TMDb hasn't decided yet. Finally, the season field is now hidden entirely when the manifest says the media type is ``movie`` — there's nothing to enter — while non-manifest sources keep the field visible because we don't yet know the type. The helper ``_read_title_and_season_from_manifests`` returns a 3-tuple ``(title, season, media_type)``; the five existing tests were updated to assert the new media-type field.

### Fixed

- **Organize's "Detected title" now reads from the rip manifest instead of the folder name.** When the user pointed the organize picker at a season-nested work-folder (``Psych (2006)/Season 01/``), the title-inference step tried MKV tags (empty on DVD-sourced rips), then the folder name (``Season 01`` — doesn't match ``^(.+?)\s*\(\d{4}\)$``), then fell back to the folder name verbatim — leaving ``Season 01`` in the Title field, which would then hit TMDb and dead-end. Both the title and season are already recorded in every disc's ``_rip_manifest.json`` (at ``title`` and via the enclosing ``Season NN/`` folder-name respectively), so a new ``_read_title_and_season_from_manifests`` helper now runs first for riplex-produced sources and returns the canonical values verbatim. When no manifest is found (organize sources produced outside riplex), the fallback is smarter too: if the picked folder's name matches ``^Season\s+\d+$`` we walk up one level for the title, and the season override falls back to parsing the parent's name in addition to the picked folder's — so pointing at ``Psych (2006)/Season 01/`` fills in both ``Psych`` and ``1`` cleanly. Tests: `TestReadTitleAndSeasonFromManifests` (5 cases in a new `tests/test_folder_picker.py`) covers the season-nested happy path, movie flat-layout, folders without manifests, malformed manifests, and TV folders under the legacy flat layout.

### Fixed

- **Season-nested rip layout now kicks in when only the dvdcompare film title (not the disc's own volume label) carries the season number.** The `<title> (<year>)/Season NN/Disc N/` layout was already implemented in `build_rip_path`, and the disc-overview marker-writer already keyed off `state["season_number"]` — but that state slot was only populated in two spots: the disc-detection screen's volume-label parser (`PSYCH_S1_D1` → 1) and the folder-picker's folder-name parser. A physical DVD whose volume label is just `PSYCH` (as *Psych* Season 1 D1 is) parsed to `season_number=None`, so the rip went to the flat `Psych (2006)/Disc 1/` layout and would collide with a subsequent *Psych* Season 2 rip. The release screen now runs a `_backfill_season_number_from_film_title` helper right after the dvdcompare film is resolved (which already stashes `dvdcompare_film_title = "Psych: Season 1 (TV) (DVD)"` into state) — it parses the season with the existing `parse_season_number` and populates `state["season_number"]` when the top-level match is TV and no season is already set. The disc-detection resume path mirrors the same call so a mid-session resume from a bare-label disc still lands in `Season NN/`. Complete-series film titles (no `Season N` token) and movies short-circuit to no-op, preserving the flat layout for genuinely single-folder cases. Existing rips written before this fix stay where they are — the resume path still finds their marker via `find_existing_session`, which already walks both flat and nested layers.

### Fixed

- **Organize now honors the S/E number the analysis step already resolved at rip time.** When `enrich_dvd_entries_with_tmdb` matched a dvdcompare feature to a TMDb episode, it stamped the classification with `S01E03 - Spellingg Bee (1080p)` — but `_classify_and_strip` in `manifest.py` then walked the string, found `" - "`, and truncated everything after the last occurrence via `rindex`, leaving `"S01E03"` in the manifest. Since no code path in `classify_title` actually appends a trailing action suffix, the strip was phantom logic that only harmed enriched labels. Two coordinated changes: (1) `_classify_and_strip` now returns `classify_title`'s output verbatim, so the enriched label reaches the manifest intact; (2) `_compute_destination` in `organizer.py` gained an SE-first branch — when the candidate's classification carries an `SxxEyy - ` prefix, the season and episode are read directly and looked up by number in the plan, bypassing the fuzzy dvdcompare↔TMDb title match entirely. This makes the SE-known-at-rip-time case fully deterministic (immune to later TMDb metadata drift, and no longer dependent on the fuzzy matcher's 0.75 threshold) while staying backwards-compatible with legacy manifests (a missing or stale SE prefix falls through to the existing `_find_episode_by_title` path). The matcher's Pass 0 (`_classification_title_key`) also strips the SE prefix before key comparison so enriched classifications still key on the episode title and match the un-enriched `Disc N: Title` targets. Tests: `TestBuildOrganizePlanShow::test_tv_episode_se_prefix_in_classification_routes_directly`, `test_tv_episode_se_prefix_missing_season_falls_back_to_title`, and `TestEnrichedClassificationTitleKey` (2 new tests) cover the happy path, the stale-SE fallback, and the matcher key parity.

### Fixed

- **Organize now fuzzy-matches dvdcompare episode titles against TMDb instead of requiring an exact string match.** The previous fix taught the matcher to honor rip-time classifications, but `_compute_destination` still bailed out for 6 of Psych S1's 15 episodes because dvdcompare's episode titles don't always match TMDb's letter-for-letter: dvdcompare says `Domestic Pilot` where TMDb has `Pilot`, `Spellingg Bee` where TMDb has `Spelling Bee`, `From the Earth to the Starbucks` where TMDb drops the second `the`, etc. Every mismatched label logged `no TMDb match for title 'X', returning None` and dumped the file into the "Unmatched files (will be skipped)" list — a preview that looked fine at the match-report level but organized only 9 of 15 episodes to their real destinations. `_find_episode_by_title` now tries case-insensitive exact match first (unchanged) and falls back to the existing `_episode_name_similarity` fuzzy matcher used by TMDb enrichment (normalized substring @ 0.95, else difflib) with a threshold of 0.75. Genuinely unknown titles still return None and are still treated as unmatched.

- **Organize now honors the rip-time classifications and doesn't collide same-basename files across discs.** Ripping *Psych* Season 1 (4 discs, 15 episodes with all runtimes within ~10 seconds of each other) then hitting Organize produced garbage: only 9 of 15 files matched, the same MKV basename (`C2_t01.mkv`, `C3_t02.mkv`) appeared multiple times in the "Matched" list all pointing at wrong episodes, and 6 files landed in "Unmatched" despite each being a valid ~43-minute episode. Two bugs stacked. **(1)** The organizer's file-lookup maps in `build_organize_plan`, `build_multi_group_plan`, `organize_preview.py`, and `riplex_cli/commands/organize.py` were keyed by basename (`{f.name: f.path}`) — makemkv assigns output names from disc metadata so every Psych disc yielded a `C2_t01.mkv`, and the four sibling paths silently overwrote each other in the dict. Every `path_map.get(candidate.file_name)` returned the same wrong source path. Now these maps key on absolute path, and `MatchCandidate` gained a `file_path` field populated at match time — `build_organize_plan` prefers `candidate.file_path` over any name-based lookup, with an inline `scanned_by_path` remap so older callers still resolve correctly. **(2)** The runtime-greedy matcher in `match_discs` sees fifteen ~2588-second episode targets and fifteen ~2587-second files; near-tied runtimes let pairings shuffle essentially at random even with the disc constraint. But the rip-time classifier already tagged each file with the actual dvdcompare episode title (`classification="Weekend Warriors (1080p)"`) — that information was thrown away at organize time. `match_discs` now runs a new Pass 0 first: for every file whose classification names a target on the same disc, claim the pairing directly. Pass 0 skips classifications that don't identify a specific dvdcompare entry (`MAIN FILM`, `Play-all`, `Duplicate of`, `Unmatched content`, movie editions like `Theatrical Cut` — those still route through the existing runtime/edition passes). Legacy rip manifests without classifications still fall through to the greedy pass unchanged.

### Changed

- **Disc Overview offers "Organize into Library" when every disc in the release is already ripped.** Resuming a completed session used to dead-end on Disc Overview: every disc showed a `RIPPED` badge, every checkbox was disabled, so Start Ripping stayed greyed out and the user had to close the app, click Organize from the welcome screen, browse to the folder, re-pick metadata, and manually re-do the routing. The screen now detects the all-ripped state, swaps the Start Ripping button for an Organize button, and shows a green banner ("Every disc in this release has already been ripped. Click Organize into Library to sort the ripped files into your Plex folder structure.") The Organize button reuses the same session-marker fan-out logic the orchestrate-done screen uses, so multi-work releases route every sibling work-folder into the organize plan without re-picking anything. Extracted to a shared `launch_organize_from_session` helper.

### Fixed

- **Organize after a resumed rip no longer crashes with `not enough values to unpack (expected 2, got 1)`.** When a session was resumed via disc detection (user closes the app mid-rip, reopens, inserts a disc that matches an in-progress session), `_resume_session` reconstructed a `MetadataSearchResult` with an empty `source_id` because the session marker didn't carry the TMDb id. That worked fine for the rip flow (nothing there needs `source_id`) but blew up as soon as the user clicked Organize on the done screen: `TmdbProvider.get_show_detail` split the empty string on `":"` expecting a `tv:<id>` payload and hit `ValueError`. The session marker (`_riplex_session.json`) now persists `source_id` for every work in the release; both the CLI (`riplex orchestrate`) and the GUI's disc overview populate it from the resolved `MetadataSearchResult` at session start, and `_resume_session` feeds it back into the reconstructed match. Legacy markers written before this build lack the field — those fall back to a `best_guess` search once on resume so the user isn't stuck.

### Changed

- **TV rips now cross-reference dvdcompare features against the TMDb episode list.** dvdcompare is authoritative about "what's on this specific physical disc" (with accurately-measured runtimes) but its per-title `feature_type` is inconsistent and its episode names are sometimes truncated or missing S/E numbers. TMDb is authoritative about "what an episode of this show actually is" (with canonical S/E and full names). `enrich_dvd_entries_with_tmdb` now runs after `build_dvd_entries` on TV discs: each dvdcompare feature is fuzzy-matched (normalized substring, then `difflib` at 0.85) against the season's TMDb episodes, and any match promotes the entry to `episode` (guarded by a 900-second floor so Psych S1 D3's 52-second deleted-scene copy of "Shawn vs. the Red Phantom" can't steal the real episode's slot) and prepends a canonical `S01E08 - ` prefix to the label the Select Titles screen shows. Each TMDb episode is consumed at most once so duplicated dvdcompare entries can't double-claim. The GUI's metadata screen fetches `ShowDetail` (with specials) in a background thread as soon as a TV match is picked and stashes it in `state["show_detail"]`; the selection and progress screens pull it back out via `collect_tmdb_episodes_for_disc`, which season-filters using each disc's own `Season N, Disc M` label (with all-seasons fallback when the label doesn't resolve). Movies, resume from disc-detection (no `source_id` on the reconstructed match), and the CLI paths are all unaffected — enrichment is opt-in via the new `tmdb_episodes=` parameter on `analyze_disc`.

- **Disc Overview now shows a "Currently loaded" dropdown that overrides auto-detection, and every disc in an orchestrate queue routes through the Insert Disc screen for a Scan-confirm step.** Auto-detection is inherently unreliable for TV boxsets whose discs share near-identical episode runtimes (the score frequently falls below the 0.50 confidence threshold and returns `None`, or worse, matches the wrong disc). Two coupled changes: (1) the dropdown at the top of Disc Overview lets the user pick which disc is loaded — the auto-detected value pre-fills it, but the user has the last word and the `INSERTED` badge on the disc list follows the dropdown; (2) `_begin_disc` and the post-rip advance in the progress screen no longer short-circuit to the selection screen when the queue's next disc happens to equal `_inserted_disc`. Every disc — including the first — passes through the Insert Disc screen, where the Scan button verifies the drive really contains the expected disc and warns on mismatch. The Insert Disc screen also gains a Quit button (returns to Welcome; ripped discs remain on disk and are resumable) and, when nothing has been ripped yet in this session, a "Back to Overview" button so the user can change their pick before rip #1. Screen title changed from "Insert Next Disc" to just "Insert Disc". The CLI's `orchestrate` flow is untouched — its `detect_disc_number` use is a headless-mode correctness dependency and its interactive path already prints "Insert Disc N" for every non-current disc.
- **TV rips now nest under a `Season NN` subfolder.** Previously every rip landed directly under `<rip_output>/<title> (<year>)/Disc N/`, which meant that ripping *Psych* Season 2 discs 1-4 after already ripping Season 1 discs 1-4 would collide on the `Disc N` folder names (Season 2 Disc 1 would overwrite Season 1 Disc 1, corrupting the earlier manifest and marker). For TV works with a known season number the rip root is now `<rip_output>/<title> (<year>)/Season NN/Disc N/`, so different seasons of the same show live in separate subtrees and can be ripped independently. Movies and TV works without a resolved season keep the flat layout. `_riplex_session.json` markers now carry the nested `folder` value so resume/fan-out across sibling works continues to work, and `find_existing_session` walks both the flat and the season-nested layers so pre-existing rips are still discovered without any migration.
- **Disc grouping now splits on dvdcompare hyperlinks, not `is_film`.** The previous rule split a release into groups wherever the `is_film` flag changed between contiguous discs. That misclassified releases where dvdcompare treats a bonus platter as `is_film=True` (e.g. Independence Day 4K disc 3, a supplements-only Blu-ray), fragmenting the movie into two groups and producing an amber "unassigned" warning that blocked Start Ripping until the user manually merged them. Grouping now uses the frozen set of `pointer_fid` values across each disc's extras as the split key: a disc with no hyperlinked extras (`frozenset()`) merges with its neighbors, and only discs whose extras hyperlink to *distinct* film pages break out into their own group. The Independence Day case now stays as a single "Discs 1-3" group with the movie match auto-applied; the Psych Complete Series case still splits disc 31 out because its three linked TV-movies each point to a different fid.
- **`DiscGroup.kind` dropped.** The `Literal["main", "film"]` discriminator that flowed through `models.py`, `lookup.py`, `disc_overview.py`, `organize_by_group.py`, and `selection.py` is gone. Groups are now differentiated only by whether `films` is populated: empty means "single work spanning these discs" (the group's `tmdb_match` is the target), non-empty means "N linked works on this disc" (each `FilmSlot.tmdb_match` is a target). This removes ~30 kind-branch sites and eliminates a class of bugs where a group's `kind` and its `films` array disagreed.
- **Group labels and ids simplified.** The old `"Main content (discs 1-4)"` / `"Feature film (disc 1)"` / `"3 feature films (disc 31)"` labels are replaced by `"Discs 1-4"` / `"Disc 1"` / `"Disc 31: 3 linked works"` (or `"Disc 31: {title}"` when a group has a single film slot). Group ids move from `main_1` / `film_31` to `disc_1` / `discs_1_4` / `disc_31`, so a resumed session referring to an old id will not match — start a fresh session after upgrading.

### Fixed

- **TV episodes are now assigned to dvdcompare entries via a sequential first-fit walk instead of nearest-duration matching.** On the *Psych* Season 1 DVD disc 2, five near-identical episode runtimes (all within seconds of each other) were assigned by pure duration match, which returned whichever entry happened to be nearest by seconds — so "Spellingg Bee" got dropped as the first episode, "Weekend Warriors" was assigned twice (to titles 0 and 6), and the actual disc-order labeling was lost. A new helper `_assign_episodes_sequentially` walks the disc titles in index order and, for each one, first-fits it against the earliest still-unconsumed dvdcompare episode whose runtime is within 60s. This guarantees one-to-one assignment (each dvdcompare entry lands on at most one disc title) and prefers dvdcompare's own ordering as the tie-break when runtimes are ambiguous, which matches how commercial TV discs are almost always authored. Non-episode entries (featurettes, play-alls) are unaffected. A `_get_effective_match` wrapper routes both `classify_title` and `is_skip_title` through the walker so a title that failed to claim an episode slot cannot silently re-match one via duration alone — it falls through to the "Unmatched content" / play-all / duplicate paths instead. The walker also handles the rarer case where dvdcompare lists episodes in a different physical order than the disc (Chernobyl S1 D1) by skipping past out-of-tolerance entries and letting a later disc title claim them.
- **TV titles longer than any known episode are now labeled "Unmatched content" instead of "Episode".** On the *Psych* Season 1 DVD disc 2, dvdcompare lists 5 individual episodes plus an untimed "Episodes (with Play All option)" entry — but MakeMKV also surfaces 2 partial play-alls (each concatenates episodes 1+2 or 3+4, ~85 min). With no per-play-all runtime to match against, these fell past every play-all detector and hit the "Episode" fallback in `classify_title` / `is_skip_title`, so they landed pre-checked on the Select Titles screen and got ripped as ~2.9 GB duplicates of the individual-episode titles. `classify_title` now labels any unmatched title longer than `1.5 × max_known_episode_runtime` as *Unmatched content*, and `is_skip_title` skips it by default (the user can still re-tick it manually). The 1.5× multiplier is loose enough that an extended-finale variant dvdcompare hasn't listed accurately still counts as an episode; tight enough that any 2-episode concatenation trips the guard.
- **Disc Release screen now shows the dvdcompare film title as its heading.** Every release on the page is a variant of one dvdcompare film (region A / region B / etc.), but the header just said "Disc Release" with the fid hidden inside a small text-button link — so it wasn't obvious *which* film's releases these were. The screen now shows a small "Disc Release" label above the film title (e.g. `Psych: Season 1 (TV) (Blu-ray)`) as the h1, on the loading, picker, no-results, and already-selected views. Falls back to the plain "Disc Release" heading when no film is loaded yet.
- **`detect_disc_format` now recognises SD DVDs.** The function only ever returned `"Blu-ray 4K"` or `"Blu-ray"`, so ripping the *DVD* edition of a show whose *Blu-ray* Complete Series page also exists on dvdcompare auto-picked the Blu-ray page and every disc got the wrong episode layout (Psych Complete Series DVD disc 1: Blu-ray page lists Pilot + Spellingg Bee + International Pilot; the actual DVD carries only Pilot + International Pilot, so Spellingg Bee showed as a "missing" episode). Detection now mirrors the width/height thresholds already used by `riplex.detect.detect_format`: >= 3840w -> Blu-ray 4K, >= 1280w -> Blu-ray, anything smaller with a resolution -> DVD. Titles without a resolution string are ignored, and if no title advertises a resolution the function still returns `None`.
- **Season chip on the leading discs of a resumed session.** The season-label backfill (`build_season_labels` inferring `Season N` from the film title for the leading untitled run) worked on the initial disc-overview render but silently failed on **resume**: `_fetch_dvdcompare_for_resume` in the disc-detection screen fetched the dvdcompare `film` object to look up the matching release, then dropped it — the non-resume path (`release.py`) writes `dvdcompare_film_title`, `dvdcompare_film_id`, and `_dvdcompare_film` into state after picking a release, but the resume path wrote none of them. On the next launch the disc overview passed `film_title=None` to `build_season_labels` and the leading Season-1 discs came back unlabeled. Resume now mirrors the state that the picker sets, so `Psych: Season 1 (TV) (Blu-ray)` (fid=66231) resumed from any disc shows the `Season 1, Disc N` chip on discs 1-4 again.
- **`riplex organize` now discovers `_riplex_session.json` and fans out across every work-folder in the release.** A multi-work resume (Psych: Complete Series → TV series in `Psych (2006)/` + linked film in `Psych - The Movie (2017)/`) now organizes every work in one pass regardless of which folder the user points at. The marker names every sibling, and each work is organized sequentially with its own title/year/media_type; missing sibling folders are logged and skipped so a partial rip still lands what's present. Orchestrate no longer needs its own manifest-optimization branch or duplicate archive block — `run_organize` picks up the marker automatically, and `organize_with_scanned` already archives each work-folder via `source_folder`. The GUI's "Organize into Library" button on the orchestrate-done screen concatenates manifests from every work-folder in the marker so the organize preview sees the whole release at once.
- **Resume from any disc of a multi-work release.** `find_existing_session` previously required a `_rip_manifest.json` whose `title` matched the requested title, so a Psych session that started with the movie disc (which wrote `_riplex_session.json` into both the movie and TV work-folders) couldn't be resumed by inserting a TV disc next — the TV folder had a marker but no manifest yet, and the marker was never consulted for title matching. Resume now falls back to a second pass that scans every `_riplex_session.json` for a matching `works[*].title`, so inserting any disc from any work in the release resolves to the same session. `disc_format` is borrowed from any sibling manifest; the requested work's own `ripped_discs` is empty if that folder has no rips yet, but `all_ripped_discs` still aggregates every sibling.
- **Linked-film autofill on multi-work discs now strips dvdcompare format markers before searching TMDb.** On the Psych *Complete Series* boxset (disc 31 links to three standalone TV-movies), the auto-fill worker followed each `pointer_fid` to its dvdcompare film page and pulled back `"Psych: The Movie (TV)"`, `"Psych 2: Lassie Come Home (TV)"`, `"Psych 3: This Is Gus (TV)"` — but the trailing `(TV)` marker (dvdcompare's format annotation, like `(Blu-ray)`) is not part of any TMDb title, so every query returned zero results and the three film slots stayed unassigned with amber "No match set" warnings. A new `strip_dvdcompare_annotations` helper trims the trailing `(TV)` / `(Blu-ray)` / `(4K)` / year markers while preserving case; the autofill worker now runs the resolved film title through it before calling TMDb, so the three Psych movies auto-fill without user intervention.
- **Main feature no longer mis-classified as a play-all when a disc has many small extras.** On Independence Day 4K disc 1 (2:24:48 theatrical + 14 short extras that happen to sum to 2:23:30), `is_skip_title` ran `detect_play_all` on the main feature and matched — the extras summed to within 78 seconds of the feature runtime, well inside the loose sum-tolerance the detector uses (~210s for 14 parts). The Select Titles screen then hid the theatrical version behind a `SKIP` badge, so a resumed rip only picked the extended cut. `is_skip_title` now short-circuits the play-all checks when the candidate's runtime is at or above the main-feature runtime (and within a plausible extended-cut range), matching the ordering that `classify_title` already used to produce the correct human-readable label.
- **dvdcompare cache auto-invalidates on scraper version change.** The disk cache under `<cache>/dvdcompare/` stores serialized `FilmComparison` payloads. When `dvdcompare-scraper` gains a new field on its models (e.g. `Feature.pointer_fid`), older cached entries were served with the new field missing — so bug fixes shipped in a scraper upgrade appeared not to work until users manually ran `riplex cache clear`. A version marker (`_version.txt`) is now written inside the `dvdcompare` cache namespace on the first `DiscProvider` construction; when the installed `dvdcompare-scraper` version changes, the namespace is wiped and re-seeded automatically. Any pre-existing cache without a marker is treated as stale on the next launch (it predates this feature and was likely written by an older scraper) and is wiped once, so users upgrading to this build don't need to manually clear.
- **dvdcompare auto-lookup no longer picks alphabetically-first film of the wrong franchise.** Searching a short common title like "Psych" against dvdcompare returns 100+ results; the previous format-only ranker picked "American Psycho (Blu-ray)" (alphabetically first Blu-ray match) instead of "Psych: Season 1 (TV) (Blu-ray)". Auto-selection now filters results to those whose leading title (before the first colon) exactly matches the query, so an unrelated franchise sharing a substring can never win over an actual title match. The format check also falls back to scanning the result title text since dvdcompare's scraper sometimes leaves the `disc_format` field unset for Blu-ray entries.
- **Season label for the leading discs of a series release now falls back to the film title.** Pages like `Psych: Season 1 (TV) (Blu-ray)` (fid=66231) use `DISC ONE ... DISC FOUR` for the release's own discs (no explicit `Season 1:` header) and `DISCS FIVE - EIGHT: Season 2` for the pointer runs. The scraper faithfully returns empty titles for discs 1–4, which left the disc overview without a season chip on those rows even though the film title itself says Season 1. `build_season_labels` now parses `Season N` out of the film title and applies it to the leading untitled run; explicit later runs (Season 2, 3, …) still win, and trailing untitled discs (bonus platters) stay unlabeled.
- **Bonus-films disc on a season-entry Complete Series release is now split into its own group.** On the `Psych: Season 1` dvdcompare page (fid=66231), disc 31 lists three standalone TV-movies via `<a href="film.php?fid=…">` links but doesn't carry a `* The Film` marker — so the previous grouping treated disc 31 as another TV disc and each ~90-minute movie as an unlabeled episode. `dvdcompare-scraper` now captures the anchor's target fid on `Feature.pointer_fid`; riplex threads it through to `PlannedExtra.pointer_fid` and treats any disc with pointered extras as film-like. Each film becomes its own `FilmSlot` carrying the linked fid, and Disc Overview autofill hits that fid to read the canonical film title before searching TMDb — so the three Psych movies now auto-fill into their own Plex movie folders regardless of which physical disc the user inserted first.

### Added

- **"View on dvdcompare.net" link on the already-selected release view.** When the release screen shows the current selection (after navigating back to it), it now includes the same `fid=…` deep-link button already shown on the multi-release picker, so users can double-check the auto-pick was right before ripping.
- **Multi-work session marker for resume.** When orchestrate starts a rip session, riplex now writes a `_riplex_session.json` marker into every work-folder of the release. On resume, `find_existing_session` reads the marker from whichever folder the user's typed title lands in and aggregates every sibling work-folder's ripped discs into a unified queue. A Psych session (TV series + bonus films disc) resumed via either "Psych" or "Psych: The Movie" now correctly skips discs already ripped under the other work-folder instead of re-queueing them.
- **Multi-work release routing.** Releases that bundle multiple distinct works — a TV series plus standalone films on a bonus disc, for instance — now organize each work into its own Plex target. The disc overview groups discs into per-work slots (main content plus one slot per bonus film), auto-fills TMDb best guesses, and the organize preview routes each disc's MKVs to the folder for that work's assigned match.
- **CLI parity for multi-work releases.** `riplex organize` and `riplex orchestrate` now share the GUI's Disc Overview routing: when a release splits into multiple works, each group is planned separately (TV series → episode folders; bonus films → per-film Plex movie folders) and the merged plan is executed as one preview. Interactive prompts confirm auto-filled TMDb targets; non-interactive runs accept auto-fills and surface any unresolved slots as skipped groups in the summary.
- **Per-group rip output on the Select Titles screen.** In orchestrate mode the selection screen now looks up the current disc's DiscGroup and swaps in that group's TMDb match for the header title, the season/disc chip, and the rip output folder. Previously all discs in a multi-work release ripped under whichever match the user picked at the metadata screen, so a Psych release (TV series + bonus films disc) would send every disc under `Psych - The Movie (2017)/` regardless of what was actually on the platter.
- **Season labels in the disc overview.** When dvdcompare's release page groups discs by season (e.g. `DISCS ONE - FOUR: Season 1`), each row now shows a light-blue `Season N, Disc M` info chip so users of long TV boxsets can cross-reference against the physical case.

## v0.9.2 — 2026-06-24

### Fixed

- **TMDb credentials: accept both the API Key and the Read Access Token.** TMDb's settings page offers a v3 API Key (query parameter auth) and a v4 API Read Access Token (bearer header auth). riplex now auto-detects which credential was provided and uses the matching auth scheme, so pasting the Read Access Token no longer fails with `401 Unauthorized`. The setup wizard, GUI welcome screen, and docs now note that either credential works.

## v0.9.0 — 2026-06-13

Summary: Plex-aligned movie version and edition support for combo-disc releases, with better organize preview matching for 4K, Blu-ray, and 3D movie rips.

### Added

- **Plex movie versions and editions.** Movie organization now distinguishes Plex versions, such as `4k` and `1080p`, from Plex editions, such as `{edition-3D}`. Multiple 2D resolutions are organized together in the base movie folder, while 3D rips are organized as a separate Plex edition folder.
- **3D movie edition output.** 3D movie rips now use Plex's edition naming convention in both folder and file names, for example `Movie Title (Year) {edition-3D}/Movie Title (Year) - 1080p {edition-3D}.mkv`.
- **Combo-pack movie matching.** Multi-disc releases with separate 4K, Blu-ray, and 3D film discs now match each main feature independently so the 4K movie, standard 1080p movie, and 3D edition can all be organized from the same release.

### Changed

- **2D is treated as the base movie, not an edition.** dvdcompare labels such as `2D` are still useful for matching disc targets, but the organized Plex output keeps 2D files in the normal `Movie Title (Year)` folder instead of creating `{edition-2D}` folders.
- **Resolution suffixes are inferred from scanned video dimensions.** Standard Blu-ray movie rips now receive a `- 1080p` suffix when ffprobe reports 1920x1080 video, matching the existing `- 4k` behavior for 2160p content.
- **Duplicate bonus features no longer clutter the missing list.** If the same bonus feature appears on multiple discs and one copy is matched, equivalent duplicate targets from other present discs are suppressed from the organize preview's missing section.

### Fixed

- **4K main feature skipped in 4K + 3D combo releases.** Multi-edition film entries on a separate 3D/2D Blu-ray disc no longer suppress the generic movie target needed to match a separate 4K film disc.
- **Matched extras still shown as missing.** Duplicate extras such as `Behind The Scenes` and `Humpback Whales` no longer appear under missing after one copy has already been matched and planned for organization.

## v0.8.0 — 2026-06-12

### Added

- **GUI: editable settings after first-run setup.** The welcome screen now exposes an **Edit Settings** button after configuration is complete, so users can update the TMDb API key, media library root, MakeMKV rip output folder, and optional archive folder without re-running setup from the command line.

### Changed

- **GUI: less Plex-specific library wording.** User-facing destination copy now refers to a general media library while retaining **Plex-compatible naming** where the current folder/file convention is being described.

## v0.7.4 — 2026-06-10

### Fixed

- **GUI: empty Disc Overview after continuing without dvdcompare data.** When dvdcompare had no matching release, the orchestrate flow still navigated to the multi-disc overview, which only renders dvdcompare-provided disc rows. The no-dvdcompare fallback now treats the inserted disc as a single-disc rip and jumps directly to title selection, where TMDb runtime heuristics can pick the main feature.

## v0.7.3 — 2026-06-10

### Fixed

- **GUI: silent "No optical drives detected" when MakeMKV is expired or unregistered.** When `makemkvcon` rejects requests with a fatal MSG (codes `5021` too-old, `5022` key-expired, `5023` key-invalid) it exits cleanly with zero `DRV:` lines, so riplex previously rendered an empty drive list. The shared library now parses these fatal MSGs and raises `MakeMKVError`; the Disc Detection screen surfaces the verbatim `makemkvcon` message along with **Download MakeMKV ↗** and **Get beta key ↗** buttons so users can resolve the lockout in one click.

## v0.7.2 — 2026-05-17

### Fixed

- **Auto-detected disc labels with compact season/disc suffixes.** Volume labels such as `Hannibal St01bd1` and `HANNIBAL_S1_BD1` now strip the trailing season/disc marker before TMDb and dvdcompare lookup, so both the GUI and CLI start from the correct base title instead of searching for the raw disc label.

## 2026-05-16

### Added

- New GUI walkthrough guide with screenshots for the main desktop flow: welcome, disc detection, metadata lookup, release picker, title selection, and multi-disc overview.

### Changed

- Split the user guides into `docs/gui-guide/` and `docs/cli-guide/` so the desktop flow and terminal flow are documented separately.
- Linked the new GUI walkthrough from the README, installation guide, CLI workflow guide, and docs index so beginners can discover the desktop flow more easily.

## v0.7.1 — 2026-05-16

### Fixed

- **GUI: empty drive list on fresh installs** ([#12](https://github.com/AnyCredit5518/riplex/issues/12)). Flet 0.85 removed the lowercase `ft.border` module and the `page.open()` method. The Disc Detection screen used both, which made it crash silently mid-render on fresh installs (which pulled Flet 0.85+ via the open-ended `flet>=0.84` pin), leaving users staring at the status line with no drive rows beneath it. Replaced every affected call site with the cross-version forms (`ft.Border.all`, `page.show_dialog`). Reported by @JelloEmperor, also confirmed by @abbrechen who provided the diagnosis and patch.

### Changed

- **Flet version pin tightened** to `>=0.84,<0.86` so a future Flet release can't break `pip install riplex[gui]` the moment it lands on PyPI. The upper bound will be bumped after each new Flet minor is smoke-tested.

## v0.7.0 — 2026-05-16

Summary: organize-time match quality fixes, faster post-rip organize, and a release-picker affordance for verifying the dvdcompare film page.

### Added

- **GUI: "View on dvdcompare.net" link** on the disc-release screen. Shows the auto-selected film page so users can verify region/edition before committing to a long rip.
- **GUI: manual film-id override** on the disc-release screen. Paste either a bare fid (e.g. `55540`) or a full URL (`https://www.dvdcompare.net/comparisons/film.php?fid=55540`) and riplex fetches and uses that film page instead. The chosen fid is persisted per `(title, disc_format)` so swapping discs in the same box set keeps the override, with a "Clear saved override" affordance.
- **`riplex organize --rescan`** flag. By default `organize` now reads `_rip_manifest.json` from each disc subfolder when present (instant load, preserves rip-time classification). Pass `--rescan` to force a fresh ffprobe scan instead.
- **GUI organize folder picker**: when every disc subfolder has a `_rip_manifest.json`, the folder loads instantly without running ffprobe. A green banner indicates the manifest load with a "Rescan with ffprobe" button to force a fresh probe.
- **GUI organize preview**: every matched row now shows a confidence chip with the actual delta in seconds (e.g. `HIGH ±18s`, `MEDIUM ±104s`) so weak matches are easy to spot before executing.

### Changed

- **Tighter match tolerance for extras and episodes.** The global `_MAX_MATCH_DELTA` of 300 s is now reserved for the main-movie target; episodes and extras use a 120 s cap. This prevents short featurettes from being claimed by unrelated short clips when no good candidate exists.
- **Classification-aware matching.** Files whose rip-time classification is `Unmatched content`, `Unknown content`, or `Very short` are no longer paired with a named extra target unless the duration delta is within ±30 s. Ambiguous shorts stay unmatched (and visible) instead of being silently assigned to the closest dvdcompare entry within the loose 300 s window.
- **Release workflow**: GitHub Releases now include both the manually composed release notes and the auto-generated commit list, so tag annotations authored ahead of the tag push aren't lost.

### Fixed

- **4K disc extras classification**: 1080p extras on a 4K disc are now only skipped when a 4K counterpart actually exists on the same disc. Previously, the duplicate-detection pass could flag legitimate standalone 1080p extras as duplicates of unrelated 4K titles.

## 2026-05-13

### Changed

- Bumped `dvdcompare-scraper` pin to `>=0.1.15`, which adds quoted-title disc-header parsing.

## 2026-05-12

### Added

- Troubleshooting guide: new "GUI: disc not being detected" section covering the redesigned drive-list panel, manual drive selection, the `makemkvcon` status line, and the bundled bug-report flow.

## 2026-05-09

### Changed

- Installation guide: complete restructure for clarity. Install riplex first, then setup, then manual tool installation as a fallback. Each install option now covers all platforms (Windows, macOS, Linux, immutable Linux distros).
- Installation guide: Windows executable instructions rewritten with step-by-step PATH setup, SmartScreen guidance, and separate GUI vs CLI paths.
- Installation guide: macOS CLI now installs to `/usr/local/bin/riplex` with proper rename.
- Installation guide: Option C (from source) split into numbered steps with separate Windows and macOS/Linux commands.
- Installation guide: tkinter/folder picker note now covers both macOS and Linux.

### Added

- Installation guide: Linux (Bazzite, Fedora Silverblue, immutable distros) sections for pipx install and manual tool installation, including Flatpak wrapper script for MKVToolNix.
- Installation guide: MakeMKV registration pulled into its own subsection.

## 2026-05-08

### Added

- Disc fixture testing pattern for end-to-end classification tests using captured disc data.
- `tests/test_disc_fixtures.py`: new test file for classification testing against real disc layouts.

## 2026-05-04

### Added

- Troubleshooting guide: macOS-specific sections for tkinter/browse button, SSL certificate errors, Gatekeeper blocking, and tools not found despite being installed.
- Installation guide: new "Install with pipx" section as the recommended install method for end users â€” provides globally available `riplex` and `riplex-ui` commands without venv activation.

### Changed

- Installation guide: dropped pre-built Intel macOS binary; macOS downloads are now Apple Silicon only. Intel Mac users directed to install with pipx.
- Installation guide: "Installing from source" section now clearly scoped to developers, with a note pointing users to pipx for global installs.
- Installation guide: clearer Gatekeeper instructions as a dedicated step with right-click method.
- Installation guide: added tip for macOS users recommending install from source.

## 2026-05-03

### Changed

- Installation guide: macOS pre-built executables now ship as `arm64` (Apple Silicon) only; added instructions to remove the Gatekeeper quarantine flag.
- Installation guide: "Installing from source" section now includes venv setup steps and a macOS SSL fix for Homebrew Python users (`SSL_CERT_FILE` via certifi).
- Installation guide: added macOS tkinter section for folder picker support.

### Added

- New troubleshooting guide (`docs/troubleshooting.md`) covering: makemkvcon not on PATH (Flatpak issue), drive not detected, invalid config file, TMDb API key signup, and dvdcompare lookup failures
- `find_ffprobe()` helper: all ffprobe consumers now check `~/.riplex/bin/`, `/usr/local/bin/`, and `/opt/homebrew/bin/` in addition to PATH.
- macOS auto-download: "Install Missing Tools" on macOS < 14 auto-downloads ffprobe from evermeet.cx to `~/.riplex/bin/`; opens download pages for MakeMKV and MKVToolNix.
- macOS .app bundle detection: `find_makemkvcon()` checks `/Applications/MakeMKV.app/`; `find_mkvmerge()` and `find_mkvpropedit()` check `/Applications/MKVToolNix.app/`.
- Dual-arch macOS CI builds (`macos-13`/x86_64 and `macos-14`/arm64) in release workflow.
- Arch-aware macOS update checker in GUI updater.
- Install progress bar and streaming output for Homebrew installs on macOS 14+.
- Graceful tkinter fallback in folder picker and welcome screen browse buttons.
- Linux apt support in GUI tool installer.

## 2026-05-02

### Changed

- Architecture doc: complete rewrite of project structure to reflect current module layout (`disc/`, `metadata/`, `riplex_cli/commands/`, all GUI screens)
- Architecture doc: replaced outdated "Plan mode" and "Rip guide mode" with single "Lookup mode" data flow
- Architecture doc: added archive step to organize mode data flow
- Installation guide: fixed GUI entry point from `riplex-gui` to `riplex-ui`
- Installation guide: added pre-built executable download instructions (Option A) for Windows and macOS
- Copilot instructions: fixed GUI entry point from `riplex-gui` to `riplex-ui`
- Changelog entry for 2026-05-01: corrected `riplex-gui` reference

### Added

- New modules documented in project structure: `title.py`, `lookup.py`, `manifest.py`, `formatting.py`, `folder_picker.py`, `organize_preview.py`, `organize_done.py`
- CLI commands directory (`riplex_cli/commands/`) documented with all five command modules
- GitHub Actions workflow for building standalone executables (`release.yml`): Windows `.exe` and macOS `.app` via PyInstaller, auto-published on tagged releases

## 2026-05-01

### Changed

- Architecture doc updated to reflect monorepo structure with three source packages (riplex, riplex_cli, riplex_app)
- Project structure listing now includes orchestrate.py, riplex_cli/, and riplex_app/ with all GUI screens
- Installation guide updated with GUI install instructions (`pip install -e ".[dev,gui]"`) and `riplex-ui` entry point

### Added

- New module `orchestrate.py` documented in project structure (shared pipeline logic)
- `riplex_cli` package documented as the CLI thin wrapper
- `riplex_app` package documented as the optional GUI thin wrapper with screen descriptions
- Installation methods table (pip install riplex vs riplex[gui])

## 2026-04-30

### Added

- Orchestrate guide (`docs/cli-guide/orchestrate.md`): full documentation for the new primary workflow command
- `orchestrate` subcommand in CLI Reference with complete options table
- `rip` subcommand added to README (features block, usage examples, CLI reference table)
- `orchestrate` subcommand added to README (features block, usage examples, CLI reference table)
- New config keys documented: `rip_output` and `archive_root` (README, configuration.md, CLI reference)
- Orchestrate and Rip data flow diagrams in architecture.md
- MakeMKV/makemkvcon added to Requirements section
- New source files documented in project structure: `ui.py`, `disc_analysis.py`, `makemkv.py`
- Orchestrate entry in mkdocs.yml navigation

### Changed

- README Features section reordered: orchestrate and rip are now listed first as the primary commands
- `plan` marked as deprecated (alias for `rip-guide`) throughout README and CLI reference
- Organize output examples updated to new grouped format (subfolder headings, `<-` arrow notation)
- Rip-guide output examples updated to use configurable rip output path instead of hardcoded `_MakeMKV`
- Architecture section updated from 4 modes to 6 modes (added orchestrate, rip)
- Project structure listings updated to include all current source and test files
- `docs/cli-guide/workflow.md` updated to recommend orchestrate as the primary workflow
- `docs/architecture.md` updated with orchestrate and rip modes and data flows
- `PLANNED_FEATURES.md` orchestrate section moved to "Recently Implemented"
- CLI reference tables for organize (added `--snapshot`, `--auto`) and rip-guide (added `--drive`) updated

## 2025-04-20

### Changed

- Replaced all personal/machine-specific paths with generic placeholders across all docs and README
- CLI examples now use `path/to/rips/Title` for user-supplied input paths
- Tool output examples (rip-guide folder structure) use `<output_root>/_MakeMKV/` to clarify the staging directory
- Output destination examples use relative paths (e.g. `Movies/...`, `TV Shows/...`)
- Config examples use `/path/to/media` placeholder
- Debug log references changed to "OS temp directory" instead of platform-specific paths
- Removed personal Python install path from `.github/copilot-instructions.md`

### Added

- Initial documentation structure in `docs/` folder
- Home page with feature overview and quick start (`index.md`)
- Getting Started section: Installation, Configuration
- User Guide section: Typical Workflow, Rip Guide, Organizing Files, Planning, Snapshots
- CLI Reference page with all subcommands and options
- Architecture overview with data flow diagrams
- Plex Naming Rules reference
- `mkdocs.yml` configuration (ready for MkDocs Material when published)
- This changelog
