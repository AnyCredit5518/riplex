"""Release selection screen - dvdcompare release picker."""

import asyncio
import threading

import flet as ft

from riplex.disc.provider import DiscProvider, _convert_release
from riplex.disc.provider import detect_disc_format, score_releases


class ReleaseScreen:
    def __init__(self, app):
        self.app = app
        self.film_comparison = None
        self._search_field: ft.TextField | None = None

    @property
    def _next_screen(self) -> str:
        workflow = self.app.state.get("workflow")
        if workflow == "organize":
            return "organize_preview"
        if workflow == "orchestrate":
            return "disc_overview"
        return "selection"

    def _current_search_title(self) -> str:
        """Title to use for dvdcompare lookup (user override > TMDb > raw title)."""
        override = self.app.state.get("dvdcompare_title_override")
        if override:
            return override
        tmdb_match = self.app.state.get("tmdb_match")
        if tmdb_match:
            return tmdb_match.title
        return self.app.state["title"]

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
                ft.Text("Disc Release", size=24, weight=ft.FontWeight.BOLD),
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

        return ft.Column(
            [
                ft.Text("Disc Release", size=24, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "Multiple releases were found on dvdcompare.net. Pick the one "
                    "that matches your physical disc (region, edition, distributor).",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                ft.Divider(height=20),
                ft.Text("Select your disc release:", size=14),
                self.release_radio_group,
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
                ft.Text("Disc Release", size=24, weight=ft.FontWeight.BOLD),
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
            log.info("dvdcompare lookup: title=%r format=%r year=%r", title, disc_format, year)
            provider = DiscProvider()
            film = asyncio.run(provider.fetch_film(title, disc_format, year=year))
            log.info("dvdcompare lookup: found %r (%d releases)",
                     film.title if film else None,
                     len(film.releases) if film else 0)
            self.app.state["_dvdcompare_film"] = film
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
        return ft.Column(
            [
                ft.Text("Disc Release", size=24, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "You've already selected a dvdcompare release for this title. "
                    "Continue, or pick a different release.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                ft.Divider(height=20),
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
        self.app.navigate(self._next_screen)

    def _use_release(self, release):
        """Convert a dvdcompare release to PlannedDiscs and navigate."""
        self.app.state["release"] = release
        try:
            discs = _convert_release(release)
            self.app.state["dvdcompare_discs"] = discs
        except Exception:
            self.app.state["dvdcompare_discs"] = []
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
