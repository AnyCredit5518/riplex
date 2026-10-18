"""Release selection screen - dvdcompare release picker."""

import asyncio
import logging
import time
import webbrowser

import flet as ft

from riplex import cache as _cache
from riplex.disc.provider import DiscProvider, _convert_release
from riplex.disc.provider import detect_disc_format, film_url, parse_film_id, score_releases
from riplex_app.background import (
    ScreenLease,
    capture_screen_lease,
    screen_lease_is_current,
    screen_operation_key,
    start_background_once,
)


log = logging.getLogger(__name__)
_OVERRIDE_CACHE_NS = "dvdcompare_film_id_override"


def _backfill_season_number_from_film_title(state: dict, film) -> None:
    """Set ``state["season_number"]`` from the dvdcompare film title.

    dvdcompare's per-season TV pages carry the season number in the film
    title (``"Psych: Season 1 (TV) (Blu-ray)"``). When the app arrives
    here without a season already resolved — the common case for a rip
    started via a physical disc whose volume label is just ``PSYCH`` —
    that title is our only reliable source. Without this, the rip step
    falls back to the flat ``<title> (<year>)/Disc N/`` layout and
    ripping a second season of the same show later collides on the
    disc-folder names.

    No-op when the season is already set (e.g. the disc label already
    parsed as ``PSYCH_S1_D1``, or the user picked a folder whose name
    included the season), when the top-level match isn't a TV work, or
    when the film title doesn't advertise a season (Complete Series
    boxsets, movies, etc.).
    """
    if state.get("season_number") is not None:
        return
    tmdb_match = state.get("tmdb_match")
    if getattr(tmdb_match, "media_type", None) != "tv":
        return
    title = getattr(film, "title", "") or ""
    if not title:
        return
    from riplex.title import parse_season_number

    parsed = parse_season_number(title)
    if parsed is not None:
        state["season_number"] = parsed
        log.info("release season inferred: season=%s film=%r", parsed, title)


def _apply_season_filter(state: dict, discs: list, film) -> list:
    """Return *discs* filtered to what the user actually picked.

    Enforces the "one pick at a time" invariant at the boundary where
    the release picker hands off to the disc overview / rip flow. For
    TV picks we drop cross-season discs (see
    :func:`riplex.disc.analysis.filter_discs_to_season`). For movie
    picks against a multi-work boxset (e.g. *Psych: The Complete
    Series*, whose 31 discs bundle 30 TV discs with one standalone
    movies disc) we drop the empty-pointer primary-work discs so only
    the movie disc(s) survive (see
    :func:`riplex.disc.analysis.filter_discs_to_picked_movie`).
    Anything else (no picked media type, no discs) passes through
    unchanged.
    """
    tmdb_match = state.get("tmdb_match")
    media_type = getattr(tmdb_match, "media_type", None)
    # Default to False / cleared on every call so a subsequent pick
    # doesn't inherit an earlier one's flag (state persists across
    # navigations).
    state["primary_movie_needs_slot"] = False
    state["hidden_disc_numbers"] = []
    if not discs:
        return discs

    def _record_hidden(kept: list) -> None:
        kept_numbers = {getattr(d, "number", None) for d in kept}
        state["hidden_disc_numbers"] = [
            n for d in discs
            if (n := getattr(d, "number", None)) is not None
            and n not in kept_numbers
        ]

    if media_type == "tv":
        season = state.get("season_number")
        if season is None:
            return discs
        from riplex.disc.analysis import filter_discs_to_season
        filtered = filter_discs_to_season(
            discs, season, film_title=getattr(film, "title", None),
        )
        if filtered:
            _record_hidden(filtered)
        return filtered or discs
    if media_type == "movie":
        from riplex.disc.analysis import filter_discs_to_picked_movie
        filtered = filter_discs_to_picked_movie(discs)
        if filtered and len(filtered) < len(discs):
            state["primary_movie_needs_slot"] = True
            _record_hidden(filtered)
        return filtered or discs
    return discs


class ReleaseScreen:
    def __init__(self, app):
        self.app = app
        self.film_comparison = None
        self._search_field: ft.TextField | None = None
        self._fid_field: ft.TextField | None = None
        self._fid_error: ft.Text | None = None

    @property
    def _next_screen(self) -> str:
        workflow = self.app.state.get("workflow")
        if workflow == "organize":
            return "organize_preview"
        if workflow == "orchestrate":
            return "disc_overview"
        return "selection"

    def _skip_next_screen(self) -> str:
        """Screen to use when continuing without dvdcompare data."""
        workflow = self.app.state.get("workflow")
        if workflow == "orchestrate":
            self.app.state["_orchestrate_disc_number"] = 1
            self.app.state["disc_queue"] = [1]
            self.app.state["current_disc_idx"] = 0
            self.app.state["all_rip_results"] = {}
            return "selection"
        return self._next_screen

    def _current_search_title(self) -> str:
        """Title to use for dvdcompare lookup (user override > TMDb > raw title)."""
        override = self.app.state.get("dvdcompare_title_override")
        if override:
            return override
        season_number = self.app.state.get("season_number")
        tmdb_match = self.app.state.get("tmdb_match")
        if tmdb_match:
            if tmdb_match.media_type == "tv" and season_number is not None:
                return f"{tmdb_match.title}: Season {season_number}"
            return tmdb_match.title
        return self.app.state["title"]

    # -- manual film-id override (cache-backed) ---------------------------

    def _override_cache_key(self) -> str:
        """Stable key for caching the user's manual film-id pick.

        Keyed by ``(title, disc_format)`` so that swapping discs within the
        same physical box set still picks up the override, but ripping a
        different format edition (DVD vs 4K) of the same film does not.
        """
        title = self._current_search_title()
        fmt = self._detect_disc_format() or ""
        return _cache.hash_key(f"{title}|{fmt}")

    def _load_persisted_override(self) -> int | None:
        entry = _cache.cache_get(_OVERRIDE_CACHE_NS, self._override_cache_key(), ttl_days=365)
        if isinstance(entry, dict):
            fid = entry.get("film_id")
            if isinstance(fid, int):
                return fid
        return None

    def _save_persisted_override(
        self,
        film_id: int,
        cache_key: str | None = None,
    ) -> None:
        _cache.cache_set(
            _OVERRIDE_CACHE_NS,
            cache_key or self._override_cache_key(),
            {"film_id": film_id},
        )

    def _clear_persisted_override(self) -> None:
        # cache module has no delete; write a sentinel that won't pass the
        # int check in _load_persisted_override.
        _cache.cache_set(_OVERRIDE_CACHE_NS, self._override_cache_key(), {"film_id": None})

    def _build_search_bar(self, title: str, *, searching: bool) -> ft.Control:
        """Editable dvdcompare search field."""
        self._search_field = ft.TextField(
            label="dvdcompare search title",
            value=title,
            expand=True,
            on_submit=self._on_search_click,
            disabled=searching,
            hint_text="Edit and press Enter to look up a different title",
        )
        return ft.Row(
            [
                self._search_field,
                ft.ElevatedButton(
                    "Search",
                    icon=ft.Icons.SEARCH,
                    on_click=self._on_search_click,
                    disabled=searching,
                ),
            ],
            spacing=10,
        )

    def _on_search_click(self, _e):
        """Re-run dvdcompare lookup with an edited title."""
        if self._search_field is None:
            return
        new_title = (self._search_field.value or "").strip()
        if not new_title:
            return
        log.info("release action: search query=%r previous_fid=%s",
                 new_title, self.app.state.get("dvdcompare_film_id"))
        self.app.state["dvdcompare_title_override"] = new_title
        self._reset_release_selection()
        self.app.navigate("release")

    def _reset_release_selection(self, *, keep_film: bool = False) -> None:
        """Open an explicit picker, discarding obsolete lookup/prefill state."""
        self.app.state["release"] = None
        self.app.state["dvdcompare_discs"] = []
        self.app.state["_dvdcompare_force_picker"] = True
        for key in (
            "_dvdcompare_error", "_dvdcompare_film_id_override",
            "_prefill_dvdcompare_film_id", "_prefill_dvdcompare_release_name",
            "_prefill_dvdcompare_failed", "_prefill_dvdcompare_error",
        ):
            self.app.state.pop(key, None)
        if not keep_film:
            self.film_comparison = None
            for key in ("_dvdcompare_film", "dvdcompare_film_id", "dvdcompare_film_title"):
                self.app.state.pop(key, None)

    # -- film URL / manual fid override UI --------------------------------

    def _film_display_title(self, film=None) -> str | None:
        """Best-effort human title of the currently-loaded dvdcompare film.

        Prefers the in-memory ``FilmComparison`` (fresh lookup), falling
        back to the ``dvdcompare_film_title`` stashed in app state (used
        when we've navigated back to an already-selected release without
        re-fetching). Returns ``None`` when neither is available.
        """
        if film is None:
            film = self.film_comparison
        title = getattr(film, "title", None) if film is not None else None
        if not title:
            title = self.app.state.get("dvdcompare_film_title")
        return title or None

    def _build_film_heading(self, film=None) -> list[ft.Control]:
        """Header block for release-picker views: film title + 'Disc Release'.

        The film title is the visual anchor because every release on the
        page is a variant of that dvdcompare film; the small ``Disc
        Release`` line above it keeps the screen's role labeled.
        """
        display = self._film_display_title(film)
        if not display:
            return [ft.Text("Disc Release", size=24, weight=ft.FontWeight.BOLD)]
        return [
            ft.Text("Disc Release", size=13, color=ft.Colors.GREY_500),
            ft.Text(display, size=24, weight=ft.FontWeight.BOLD),
        ]

    def _build_film_link(self, film) -> ft.Control | None:
        """Build a "View on dvdcompare.net" button for the current film."""
        if film is None or not getattr(film, "film_id", None):
            return None
        url = film_url(film.film_id)

        def _open(_e, _url=url):
            webbrowser.open(_url)

        return ft.Row(
            [
                ft.Icon(ft.Icons.OPEN_IN_NEW, size=16, color=ft.Colors.BLUE),
                ft.TextButton(
                    f"View on dvdcompare.net (fid={film.film_id})",
                    on_click=_open,
                    tooltip=url,
                ),
            ],
            spacing=4,
        )

    def _build_film_link_from_id(self, film_id: int) -> ft.Control:
        """Build the "View on dvdcompare.net" button from just a fid.

        Used when ``self.film_comparison`` isn't in memory (e.g. after
        the user backs into the release screen and we're rendering the
        already-selected release without re-fetching).
        """
        url = film_url(film_id)

        def _open(_e, _url=url):
            webbrowser.open(_url)

        return ft.Row(
            [
                ft.Icon(ft.Icons.OPEN_IN_NEW, size=16, color=ft.Colors.BLUE),
                ft.TextButton(
                    f"View on dvdcompare.net (fid={film_id})",
                    on_click=_open,
                    tooltip=url,
                ),
            ],
            spacing=4,
        )

    def _build_fid_override_section(self) -> ft.Control:
        """Editable manual film-id / URL override input."""
        self._fid_field = ft.TextField(
            label="Manual override (paste dvdcompare URL or fid)",
            hint_text="e.g. 55540 or https://www.dvdcompare.net/comparisons/film.php?fid=55540",
            expand=True,
            on_submit=self._on_fid_override_submit,
        )
        self._fid_error = ft.Text("", size=12, color=ft.Colors.RED, visible=False)
        persisted = self._load_persisted_override()
        hint_controls = []
        if persisted is not None:
            hint_controls.append(
                ft.Row([
                    ft.Text(
                        f"Currently using saved override fid={persisted}.",
                        size=12,
                        color=ft.Colors.GREY_500,
                    ),
                    ft.TextButton(
                        "Clear saved override",
                        on_click=self._on_clear_override,
                    ),
                ], spacing=10),
            )
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Wrong film? Open dvdcompare.net, find the right page, "
                        "and paste its URL or fid here:",
                        size=12,
                        color=ft.Colors.GREY_500,
                    ),
                    ft.Row(
                        [
                            self._fid_field,
                            ft.ElevatedButton(
                                "Use this",
                                icon=ft.Icons.CHECK,
                                on_click=self._on_fid_override_submit,
                            ),
                        ],
                        spacing=10,
                    ),
                    self._fid_error,
                    *hint_controls,
                ],
                spacing=6,
            ),
            padding=ft.Padding(left=0, top=8, right=0, bottom=8),
        )

    def _on_fid_override_submit(self, _e):
        if self._fid_field is None:
            return
        raw = (self._fid_field.value or "").strip()
        fid = parse_film_id(raw)
        if fid is None:
            log.info("release action: manual-override rejected (invalid film id)")
            if self._fid_error is not None:
                self._fid_error.value = (
                    "Couldn't parse a film id from that input. "
                    "Expected a number like 55540 or a "
                    "dvdcompare.net/comparisons/film.php?fid=... URL."
                )
                self._fid_error.visible = True
                self.app.page.update()
            return
        # Stash for the next lookup pass and trigger a refresh.
        log.info("release action: manual-override fid=%s previous_fid=%s",
                 fid, self.app.state.get("dvdcompare_film_id"))
        self._reset_release_selection()
        self.app.state["_dvdcompare_film_id_override"] = fid
        self.app.navigate("release")

    def _on_clear_override(self, _e):
        log.info("release action: clear-saved-override query=%r", self._current_search_title())
        self._clear_persisted_override()
        self._reset_release_selection()
        self.app.navigate("release")


    def build(self) -> ft.Control:
        title = self._current_search_title()
        self.film_comparison = self.app.state.get("_dvdcompare_film")
        log.debug(
            "release build: query=%r workflow=%s season=%s fid=%s selected=%r "
            "film_loaded=%s force_picker=%s epoch=%s",
            title, self.app.state.get("workflow"), self.app.state.get("season_number"),
            self.app.state.get("dvdcompare_film_id"),
            getattr(self.app.state.get("release"), "name", None),
            self.film_comparison is not None,
            bool(self.app.state.get("_dvdcompare_force_picker")),
            getattr(self.app, "_navigation_epoch", None),
        )

        # Fast path: manifest recorded the dvdcompare film_id + release
        # name at rip time. Fetch the film directly, match the release by
        # name, and skip the picker. One-shot flag falls back to the
        # normal lookup on failure.
        prefill_fid = self.app.state.get("_prefill_dvdcompare_film_id")
        prefill_release_name = self.app.state.get("_prefill_dvdcompare_release_name")
        prefill_failed = self.app.state.pop("_prefill_dvdcompare_failed", False)
        if prefill_fid and prefill_release_name and not prefill_failed:
            lease = capture_screen_lease(self.app)
            start_background_once(
                self.app,
                screen_operation_key("dvdcompare-lookup", lease),
                self._resolve_prefill_dvdcompare,
                args=(
                    prefill_fid,
                    prefill_release_name,
                    lease,
                ),
            )
            return ft.Column(
                [
                    *self._build_film_heading(),
                    ft.Text(
                        "Restoring the dvdcompare release saved when this folder was ripped.",
                        size=13,
                        color=ft.Colors.GREY_500,
                    ),
                    ft.Divider(height=20),
                    ft.Row([
                        ft.ProgressRing(width=30, height=30),
                        ft.Text(
                            f"Fetching dvdcompare release for \"{prefill_release_name}\"...",
                            size=14,
                        ),
                    ], spacing=10),
                    ft.Container(expand=True),
                    ft.Row([
                        ft.TextButton("Back", on_click=lambda _: self.app.navigate("metadata")),
                    ]),
                ],
                spacing=10,
                expand=True,
            )

        # Error/skip state
        dvdc_error = self.app.state.pop("_dvdcompare_error", None)
        if dvdc_error:
            log.info("release view: lookup-error message=%r", dvdc_error)
            return self._build_no_releases_view(dvdc_error, title=title)

        # If we already have a release selected (e.g. user came back from a
        # later screen), avoid re-fetching. Show a summary with the option
        # to change.
        existing_release = self.app.state.get("release")
        existing_discs = self.app.state.get("dvdcompare_discs")
        if existing_release is not None and existing_discs:
            log.debug("release view: selected-summary name=%r", existing_release.name)
            return self._build_current_release_view(existing_release, existing_discs)

        # Keep the film available for repeated picker builds, season filtering,
        # and the overview. A correction must not auto-accept a sole release.
        if self.film_comparison is not None:
            releases = self.film_comparison.releases
            if not releases:
                return self._build_no_releases_view(title=title)
            if len(releases) == 1 and not self.app.state.get("_dvdcompare_force_picker"):
                log.info("release auto-select: fid=%s name=%r reason=only-release",
                         self.film_comparison.film_id, releases[0].name)
                self._use_release(releases[0])
                return ft.Column()  # will navigate away
            return self._build_releases_view(releases)

        # Loading state
        content = ft.Column(
            [
                *self._build_film_heading(),
                ft.Text(
                    "Looking up per-disc content breakdowns from dvdcompare.net "
                    "to help identify featurettes, extras, and duplicates.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                ft.Divider(height=20),
                self._build_search_bar(title, searching=True),
                ft.Row([
                    ft.ProgressRing(width=30, height=30),
                    ft.Text(f"Looking up disc structure for \"{title}\" on dvdcompare.net...", size=14),
                ], spacing=10),
                ft.Container(expand=True),
                ft.Row([
                    ft.TextButton("Back", on_click=lambda _: self.app.navigate("metadata")),
                    ft.TextButton("Skip", on_click=lambda _: self._skip(None)),
                ]),
            ],
            spacing=10,
            expand=True,
        )

        # Start lookup in background
        lease = capture_screen_lease(self.app)
        start_background_once(
            self.app,
            screen_operation_key("dvdcompare-lookup", lease),
            self._lookup_dvdcompare,
            args=(title, lease),
        )

        return content

    def _build_releases_view(self, releases) -> ft.Control:
        """Build view showing release options."""
        rec_idx = self._score_releases(releases)
        log.debug(
            "release view: picker fid=%s recommended_index=%s options=%s",
            getattr(self.film_comparison, "film_id", None), rec_idx,
            [(i, rel.name, len(rel.discs)) for i, rel in enumerate(releases)],
        )

        # Filter out releases with no discs (no useful data)
        indexed_releases = [(i, rel) for i, rel in enumerate(releases) if rel.discs]
        if not indexed_releases:
            return self._build_no_releases_view()

        # Sort: recommended first, then by disc count descending
        def sort_key(item):
            i, rel = item
            is_rec = (i == rec_idx)
            return (not is_rec, -len(rel.discs))

        indexed_releases.sort(key=sort_key)

        release_rows = []
        for i, rel in indexed_releases:
            disc_count = len(rel.discs)
            disc_word = "disc" if disc_count == 1 else "discs"
            label = f"{rel.name} [{disc_count} {disc_word}]"
            if i == rec_idx:
                label += "  (* recommended)"
            release_rows.append(ft.Radio(value=str(i), label=label))

        # Default selection: recommended release
        default_value = str(rec_idx) if any(i == rec_idx for i, _ in indexed_releases) else str(indexed_releases[0][0])

        self.release_radio_group = ft.RadioGroup(
            content=ft.Column(release_rows, spacing=2),
            value=default_value,
            on_change=self._on_release_change,
        )

        film_link = self._build_film_link(self.film_comparison)
        header_children = [
            *self._build_film_heading(),
            ft.Text(
                "Choose the release on dvdcompare.net "
                "that matches your physical disc (region, edition, distributor).",
                size=13,
                color=ft.Colors.GREY_500,
            ),
        ]
        if film_link is not None:
            header_children.append(film_link)

        # Amber banner when the fast-path (fetch-by-saved-fid) failed
        # and we fell back to the manual picker.
        prefill_error = self.app.state.pop("_prefill_dvdcompare_error", None)
        if prefill_error:
            header_children.append(
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.WARNING_AMBER, color=ft.Colors.AMBER_400, size=18),
                        ft.Text(
                            "The dvdcompare release saved when this folder was "
                            f"ripped no longer resolves ({prefill_error}). Please pick again.",
                            size=13,
                            color=ft.Colors.AMBER_400,
                            expand=True,
                        ),
                    ], spacing=8),
                    bgcolor=ft.Colors.with_opacity(0.1, ft.Colors.AMBER),
                    padding=12,
                    border_radius=8,
                )
            )
        header_children.append(ft.Divider(height=20))

        return ft.Column(
            [
                *header_children,
                self._build_search_bar(self._current_search_title(), searching=False),
                ft.Text("Select your disc release:", size=14),
                self.release_radio_group,
                ft.Divider(height=20),
                self._build_fid_override_section(),
                ft.Container(expand=True),
                ft.Row([
                    ft.TextButton("Back", on_click=lambda _: self.app.navigate("metadata")),
                    ft.ElevatedButton(
                        "Next",
                        icon=ft.Icons.ARROW_FORWARD,
                        on_click=self._next,
                        style=ft.ButtonStyle(padding=ft.Padding(left=30, top=15, right=30, bottom=15)),
                    ),
                ]),
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def _build_no_releases_view(self, message: str = None, *, title: str = "") -> ft.Control:
        """Build view when no releases found."""
        msg = message or "No dvdcompare releases found. Try a different search title, or continue without disc structure data."
        if not title:
            title = self._current_search_title()
        return ft.Column(
            [
                *self._build_film_heading(),
                ft.Text(
                    "dvdcompare.net provides per-disc content breakdowns that help "
                    "identify featurettes, extras, and play-all titles. Without it, "
                    "riplex will classify titles by duration heuristics only.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                ft.Divider(height=20),
                self._build_search_bar(title, searching=False),
                ft.Text(msg, size=14, color=ft.Colors.ORANGE),
                ft.Divider(height=20),
                self._build_fid_override_section(),
                ft.Container(expand=True),
                ft.Row([
                    ft.TextButton("Back", on_click=lambda _: self.app.navigate("metadata")),
                    ft.ElevatedButton(
                        "Continue without",
                        icon=ft.Icons.ARROW_FORWARD,
                        on_click=self._skip,
                        style=ft.ButtonStyle(padding=ft.Padding(left=30, top=15, right=30, bottom=15)),
                    ),
                ]),
            ],
            spacing=10,
            expand=True,
        )

    def _resolve_prefill_dvdcompare(
        self,
        film_id: int,
        release_name: str,
        lease: ScreenLease | None = None,
    ):
        """Resolve a prefilled dvdcompare film_id + release name straight
        to the ``PlannedDisc`` list.

        On success, populates ``release``/``dvdcompare_discs`` and
        navigates to the next screen. On failure (network, film gone,
        release name no longer matches), sets ``_prefill_dvdcompare_failed``
        and re-navigates to the release screen, which falls back to the
        normal title-based lookup and picker.
        """
        started_at = time.monotonic()
        log.info("dvdcompare prefill start: fid=%s release=%r epoch=%s",
             film_id, release_name, getattr(lease, "epoch", None))

        try:
            provider = DiscProvider()
            film = asyncio.run(provider.fetch_film_by_id(film_id))
            if not screen_lease_is_current(self.app, lease):
                return

            match = next(
                (r for r in film.releases if r.name == release_name),
                None,
            )
            if match is None:
                raise LookupError(
                    f"saved release {release_name!r} is no longer listed under "
                    f"dvdcompare film {film_id}"
                )
            discs = _convert_release(match)
            if not discs:
                raise LookupError(
                    f"saved release {release_name!r} contained no usable disc data"
                )
            _backfill_season_number_from_film_title(self.app.state, film)
            discs = _apply_season_filter(self.app.state, discs, film)

            self.film_comparison = film
            self.app.state["_dvdcompare_film"] = film
            self.app.state["dvdcompare_film_id"] = film.film_id
            self.app.state["dvdcompare_film_title"] = film.title
            self.app.state["release"] = match
            self.app.state["dvdcompare_discs"] = discs
            self.app.state.pop("_prefill_dvdcompare_film_id", None)
            self.app.state.pop("_prefill_dvdcompare_release_name", None)
            self.app.state.pop("_dvdcompare_force_picker", None)
            next_screen = self._next_screen
            log.info("dvdcompare prefill restored: fid=%s release=%r discs=%s elapsed=%.3fs",
                     film.film_id, match.name, [d.number for d in discs],
                     time.monotonic() - started_at)
        except Exception as exc:
            if not screen_lease_is_current(self.app, lease):
                return
            log.warning("dvdcompare prefill fetch failed: %s", exc, exc_info=True)
            self.film_comparison = None
            self.app.state["release"] = None
            self.app.state["dvdcompare_discs"] = []
            for key in ("_dvdcompare_film", "dvdcompare_film_id", "dvdcompare_film_title"):
                self.app.state.pop(key, None)
            # A rejected saved release must not restart after the fallback
            # title lookup finishes and rebuilds this screen.
            self.app.state.pop("_prefill_dvdcompare_film_id", None)
            self.app.state.pop("_prefill_dvdcompare_release_name", None)
            self.app.state["_prefill_dvdcompare_failed"] = True
            self.app.state["_prefill_dvdcompare_error"] = str(exc)
            next_screen = "release"

        async def _nav():
            if screen_lease_is_current(self.app, lease):
                self.app.navigate(next_screen)

        self.app.page.run_task(_nav)

    def _lookup_dvdcompare(
        self,
        title: str | None = None,
        lease: ScreenLease | None = None,
    ):
        """Fetch dvdcompare releases in background."""
        started_at = time.monotonic()
        title = title or self._current_search_title()
        tmdb_match = self.app.state.get("tmdb_match")

        try:
            disc_format = self._detect_disc_format()
            year = tmdb_match.year if tmdb_match else None
            provider = DiscProvider()

            # Per-session manual override (just submitted).
            session_fid = self.app.state.pop("_dvdcompare_film_id_override", None)
            override_cache_key = (
                self._override_cache_key() if session_fid is not None else None
            )
            # Persisted override (set on a previous run for this title/format).
            persisted_fid = self._load_persisted_override() if session_fid is None else None
            override_fid = session_fid if session_fid is not None else persisted_fid
            source = (
                "session" if session_fid is not None
                else "persisted" if persisted_fid is not None else "title"
            )
            log.info(
                "dvdcompare lookup start: query=%r format=%r year=%s fid=%s source=%s epoch=%s",
                title, disc_format, year, override_fid, source, getattr(lease, "epoch", None),
            )

            if override_fid is not None:
                film = asyncio.run(provider.fetch_film_by_id(override_fid))
            else:
                film = asyncio.run(provider.fetch_film(title, disc_format, year=year))

            if not screen_lease_is_current(self.app, lease):
                return
            if session_fid is not None:
                # Persist on success so subsequent navigations / disc swaps
                # auto-use the same fid. Use the key captured before I/O.
                self._save_persisted_override(
                    session_fid,
                    override_cache_key,
                )
            log.info("dvdcompare lookup: found %r (fid=%s, %d releases, elapsed=%.3fs)",
                     film.title if film else None,
                     film.film_id if film else None,
                     len(film.releases) if film else 0,
                     time.monotonic() - started_at)
            self.app.state["_dvdcompare_film"] = film
            # Keep the film identity available to restored/current-release views.
            if film and getattr(film, "film_id", None):
                self.app.state["dvdcompare_film_id"] = film.film_id
            if film and getattr(film, "title", None):
                self.app.state["dvdcompare_film_title"] = film.title
        except Exception as exc:
            if not screen_lease_is_current(self.app, lease):
                return
            log.warning("dvdcompare lookup failed after %.3fs: %s",
                        time.monotonic() - started_at, exc, exc_info=True)
            self.app.state["_dvdcompare_error"] = str(exc)

        # Schedule navigation on main event loop
        async def _nav():
            if screen_lease_is_current(self.app, lease):
                self.app.navigate("release")

        self.app.page.run_task(_nav)

    def _on_release_change(self, _e):
        """Record radio selection separately from committing it with Next."""
        idx = int(self.release_radio_group.value)
        release = self.film_comparison.releases[idx]
        log.debug("release action: highlight index=%s fid=%s name=%r",
                  idx, self.film_comparison.film_id, release.name)

    def _next(self, e):
        """Convert selected release and proceed."""
        idx = int(self.release_radio_group.value)
        release = self.film_comparison.releases[idx]
        log.info("release action: choose index=%s fid=%s name=%r",
                  idx, self.film_comparison.film_id, release.name)
        self._use_release(release)

    def _continue(self, _e):
        """Proceed to the next screen using the already-selected release."""
        log.info("release action: continue fid=%s name=%r -> %s",
                 self.app.state.get("dvdcompare_film_id"),
                 getattr(self.app.state.get("release"), "name", None), self._next_screen)
        self.app.navigate(self._next_screen)

    def _change_release(self, _e):
        """Open the editable release picker, including for a single release."""
        log.info("release action: change-release fid=%s name=%r",
                 self.app.state.get("dvdcompare_film_id"),
                 getattr(self.app.state.get("release"), "name", None))
        self._reset_release_selection(keep_film=True)
        self.app.navigate("release")

    def _build_current_release_view(self, release, discs) -> ft.Control:
        """Show the already-picked release without re-querying dvdcompare."""
        disc_count = len(discs)
        disc_word = "disc" if disc_count == 1 else "discs"
        film_link = self._build_film_link(self.film_comparison)
        if film_link is None:
            # Cross-render fallback: rebuild from the persisted film_id.
            persisted_fid = self.app.state.get("dvdcompare_film_id")
            if persisted_fid:
                film_link = self._build_film_link_from_id(persisted_fid)
        header_children = [
            *self._build_film_heading(),
            ft.Text(
                "You've already selected a dvdcompare release for this title. "
                "Continue, or pick a different release.",
                size=13,
                color=ft.Colors.GREY_500,
            ),
        ]
        if film_link is not None:
            header_children.append(film_link)
        header_children.append(ft.Divider(height=20))
        return ft.Column(
            [
                *header_children,
                ft.Row([
                    ft.Icon(ft.Icons.ALBUM, color=ft.Colors.BLUE, size=20),
                    ft.Text(
                        f"{release.name}  [{disc_count} {disc_word}]",
                        size=14,
                        weight=ft.FontWeight.W_500,
                    ),
                ], spacing=10),
                ft.Divider(height=20),
                self._build_fid_override_section(),
                ft.Container(expand=True),
                ft.Row([
                    ft.TextButton("Back", on_click=lambda _: self.app.navigate("metadata")),
                    ft.TextButton(
                        "Change release",
                        icon=ft.Icons.SWAP_HORIZ,
                        on_click=self._change_release,
                    ),
                    ft.ElevatedButton(
                        "Continue",
                        icon=ft.Icons.ARROW_FORWARD,
                        on_click=self._continue,
                        style=ft.ButtonStyle(padding=ft.Padding(left=30, top=15, right=30, bottom=15)),
                    ),
                ]),
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def _skip(self, e):
        """Proceed without dvdcompare data."""
        log.info("release action: skip workflow=%s fid=%s",
                 self.app.state.get("workflow"), self.app.state.get("dvdcompare_film_id"))
        self.app.state["release"] = None
        self.app.state["dvdcompare_discs"] = []
        self.app.state.pop("_dvdcompare_force_picker", None)
        self.app.navigate(self._skip_next_screen())

    def _use_release(self, release):
        """Convert a dvdcompare release to PlannedDiscs and navigate."""
        try:
            discs = _convert_release(release)
        except Exception as exc:
            log.exception("release conversion failed: fid=%s name=%r",
                          self.app.state.get("dvdcompare_film_id"), release.name)
            self.app.state["release"] = None
            self.app.state["dvdcompare_discs"] = []
            self.app.state["_dvdcompare_error"] = (
                f"Could not read disc data from the selected dvdcompare release: {exc}"
            )
            self.app.navigate("release")
            return

        if not discs:
            log.warning("release conversion returned no discs: fid=%s name=%r",
                        self.app.state.get("dvdcompare_film_id"), release.name)
            self.app.state["release"] = None
            self.app.state["dvdcompare_discs"] = []
            self.app.state["_dvdcompare_error"] = (
                "The selected dvdcompare release did not contain usable disc data. "
                "Try a different search title or continue without disc structure data."
            )
            self.app.navigate("release")
            return

        film = self.app.state.get("_dvdcompare_film")
        _backfill_season_number_from_film_title(self.app.state, film)
        discs = _apply_season_filter(self.app.state, discs, film)
        self.app.state["release"] = release
        self.app.state["dvdcompare_discs"] = discs
        self.app.state.pop("_dvdcompare_force_picker", None)
        log.info("release selected: fid=%s name=%r discs=%s hidden=%s season=%s -> %s",
                 getattr(film, "film_id", None), release.name, [d.number for d in discs],
                 self.app.state.get("hidden_disc_numbers"),
                 self.app.state.get("season_number"), self._next_screen)
        self.app.navigate(self._next_screen)

    def _score_releases(self, releases) -> int:
        """Score releases by matching live disc durations to feature runtimes."""
        disc_info = self.app.state.get("disc_info")
        return score_releases(releases, disc_info)

    def _detect_disc_format(self) -> str | None:
        """Auto-detect dvdcompare format string from disc or scanned file resolutions."""
        disc_info = self.app.state.get("disc_info")
        if disc_info:
            return detect_disc_format(disc_info)
        # Organize mode: infer from scanned files
        scanned = self.app.state.get("scanned")
        if scanned:
            from riplex.detect import detect_format
            return detect_format(scanned)
        return None
