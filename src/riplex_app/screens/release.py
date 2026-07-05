"""Release selection screen - dvdcompare release picker."""

import asyncio
import threading
import webbrowser

import flet as ft

from riplex import cache as _cache
from riplex.disc.provider import DiscProvider, _convert_release
from riplex.disc.provider import detect_disc_format, film_url, parse_film_id, score_releases


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

    def _save_persisted_override(self, film_id: int) -> None:
        _cache.cache_set(
            _OVERRIDE_CACHE_NS,
            self._override_cache_key(),
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
        self.app.state["dvdcompare_title_override"] = new_title
        # Clear any previously-selected release so we don't auto-skip the
        # lookup with the old data.
        self.app.state["release"] = None
        self.app.state["dvdcompare_discs"] = []
        self.app.state.pop("_dvdcompare_film", None)
        self.app.state.pop("_dvdcompare_error", None)
        self.app.navigate("release")

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
        self.app.state["_dvdcompare_film_id_override"] = fid
        self.app.state["release"] = None
        self.app.state["dvdcompare_discs"] = []
        self.app.state.pop("_dvdcompare_film", None)
        self.app.state.pop("_dvdcompare_error", None)
        self.app.navigate("release")

    def _on_clear_override(self, _e):
        self._clear_persisted_override()
        self.app.state["release"] = None
        self.app.state["dvdcompare_discs"] = []
        self.app.state.pop("_dvdcompare_film", None)
        self.app.state.pop("_dvdcompare_error", None)
        self.app.navigate("release")


    def build(self) -> ft.Control:
        title = self._current_search_title()

        # Check if dvdcompare data already fetched (re-render after background lookup)
        cached_film = self.app.state.pop("_dvdcompare_film", None)
        if cached_film is not None:
            self.film_comparison = cached_film
            releases = self.film_comparison.releases if self.film_comparison else []
            if not releases:
                return self._build_no_releases_view(title=title)
            if len(releases) == 1:
                self._use_release(releases[0])
                return ft.Column()  # will navigate away
            return self._build_releases_view(releases)

        # Error/skip state
        dvdc_error = self.app.state.pop("_dvdcompare_error", None)
        if dvdc_error:
            return self._build_no_releases_view(dvdc_error, title=title)

        # If we already have a release selected (e.g. user came back from a
        # later screen), avoid re-fetching. Show a summary with the option
        # to change.
        existing_release = self.app.state.get("release")
        existing_discs = self.app.state.get("dvdcompare_discs")
        if existing_release is not None and existing_discs:
            return self._build_current_release_view(existing_release, existing_discs)

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
        threading.Thread(target=self._lookup_dvdcompare, daemon=True).start()

        return content

    def _build_releases_view(self, releases) -> ft.Control:
        """Build view showing release options."""
        rec_idx = self._score_releases(releases)

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
        )

        film_link = self._build_film_link(self.film_comparison)
        header_children = [
            *self._build_film_heading(),
            ft.Text(
                "Multiple releases were found on dvdcompare.net. Pick the one "
                "that matches your physical disc (region, edition, distributor).",
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

    def _lookup_dvdcompare(self):
        """Fetch dvdcompare releases in background."""
        import logging
        log = logging.getLogger(__name__)

        title = self._current_search_title()
        tmdb_match = self.app.state.get("tmdb_match")

        try:
            disc_format = self._detect_disc_format()
            year = tmdb_match.year if tmdb_match else None
            provider = DiscProvider()

            # Per-session manual override (just submitted).
            session_fid = self.app.state.pop("_dvdcompare_film_id_override", None)
            # Persisted override (set on a previous run for this title/format).
            persisted_fid = self._load_persisted_override() if session_fid is None else None
            override_fid = session_fid if session_fid is not None else persisted_fid

            if override_fid is not None:
                log.info("dvdcompare lookup: using film id override fid=%s (source=%s)",
                         override_fid, "session" if session_fid is not None else "persisted")
                film = asyncio.run(provider.fetch_film_by_id(override_fid))
                # Persist on success so subsequent navigations / disc swaps
                # auto-use the same fid.
                if session_fid is not None:
                    self._save_persisted_override(override_fid)
            else:
                log.info("dvdcompare lookup: title=%r format=%r year=%r",
                         title, disc_format, year)
                film = asyncio.run(provider.fetch_film(title, disc_format, year=year))

            log.info("dvdcompare lookup: found %r (fid=%s, %d releases)",
                     film.title if film else None,
                     film.film_id if film else None,
                     len(film.releases) if film else 0)
            self.app.state["_dvdcompare_film"] = film
            # Persist film_id so the "View on dvdcompare.net" link on the
            # current-release view survives re-navigation (film_comparison
            # is popped out of state on each build).
            if film and getattr(film, "film_id", None):
                self.app.state["dvdcompare_film_id"] = film.film_id
            if film and getattr(film, "title", None):
                self.app.state["dvdcompare_film_title"] = film.title
            _backfill_season_number_from_film_title(self.app.state, film)
        except Exception as exc:
            log.warning("dvdcompare lookup failed: %s", exc)
            self.app.state["_dvdcompare_error"] = str(exc)

        # Schedule navigation on main event loop
        async def _nav():
            self.app.navigate("release")

        self.app.page.run_task(_nav)

    def _next(self, e):
        """Convert selected release and proceed."""
        idx = int(self.release_radio_group.value)
        release = self.film_comparison.releases[idx]
        self._use_release(release)

    def _continue(self, _e):
        """Proceed to the next screen using the already-selected release."""
        self.app.navigate(self._next_screen)

    def _change_release(self, _e):
        """Clear the current dvdcompare selection and re-trigger lookup."""
        self.app.state["release"] = None
        self.app.state["dvdcompare_discs"] = []
        self.app.state.pop("_dvdcompare_film", None)
        self.app.state.pop("_dvdcompare_error", None)
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
            expand=True,
        )

    def _skip(self, e):
        """Proceed without dvdcompare data."""
        self.app.state["dvdcompare_discs"] = []
        self.app.navigate(self._skip_next_screen())

    def _use_release(self, release):
        """Convert a dvdcompare release to PlannedDiscs and navigate."""
        try:
            discs = _convert_release(release)
        except Exception as exc:
            self.app.state["release"] = None
            self.app.state["dvdcompare_discs"] = []
            self.app.state["_dvdcompare_error"] = (
                f"Could not read disc data from the selected dvdcompare release: {exc}"
            )
            self.app.navigate("release")
            return

        if not discs:
            self.app.state["release"] = None
            self.app.state["dvdcompare_discs"] = []
            self.app.state["_dvdcompare_error"] = (
                "The selected dvdcompare release did not contain usable disc data. "
                "Try a different search title or continue without disc structure data."
            )
            self.app.navigate("release")
            return

        self.app.state["release"] = release
        self.app.state["dvdcompare_discs"] = discs
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
