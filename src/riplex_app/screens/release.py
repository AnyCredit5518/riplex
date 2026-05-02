"""Release selection screen - dvdcompare release picker."""

import asyncio
import threading

import flet as ft

from dvdcompare.scraper import find_film
from riplex.disc.provider import _convert_release
from riplex.disc.provider import detect_disc_format, score_releases


class ReleaseScreen:
    def __init__(self, app):
        self.app = app
        self.film_comparison = None

    @property
    def _next_screen(self) -> str:
        return "organize_preview" if self.app.state.get("workflow") == "organize" else "selection"
        self.release_radio_group = None

    def build(self) -> ft.Control:
        tmdb_match = self.app.state["tmdb_match"]
        title = tmdb_match.title if tmdb_match else self.app.state["title"]

        # Check if dvdcompare data already fetched (re-render after background lookup)
        cached_film = self.app.state.pop("_dvdcompare_film", None)
        if cached_film is not None:
            self.film_comparison = cached_film
            releases = self.film_comparison.releases if self.film_comparison else []
            if not releases:
                return self._build_no_releases_view()
            if len(releases) == 1:
                self._use_release(releases[0])
                return ft.Column()  # will navigate away
            return self._build_releases_view(releases)

        # Error/skip state
        dvdc_error = self.app.state.pop("_dvdcompare_error", None)
        if dvdc_error:
            return self._build_no_releases_view(dvdc_error)

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
                ft.Row([
                    ft.ProgressRing(width=30, height=30),
                    ft.Text(f"Looking up disc structure for \"{title}\" on dvdcompare.net...", size=14),
                ], spacing=10),
                ft.Container(expand=True),
                ft.TextButton("Back", on_click=lambda _: self.app.navigate("metadata")),
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

        release_rows = []
        for i, rel in enumerate(releases):
            disc_count = len(rel.discs)
            disc_word = "disc" if disc_count == 1 else "discs"
            label = f"{rel.name} [{disc_count} {disc_word}]"
            if i == rec_idx:
                label += "  (* recommended)"
            release_rows.append(ft.Radio(value=str(i), label=label))

        self.release_radio_group = ft.RadioGroup(
            content=ft.Column(release_rows, spacing=2),
            value=str(rec_idx),
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
                        style=ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=30, vertical=15)),
                    ),
                ]),
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def _build_no_releases_view(self, message: str = None) -> ft.Control:
        """Build view when no releases found."""
        msg = message or "No dvdcompare releases found. Proceeding without disc structure data."
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
                ft.Text(msg, size=14, color=ft.Colors.ORANGE),
                ft.Container(expand=True),
                ft.Row([
                    ft.TextButton("Back", on_click=lambda _: self.app.navigate("metadata")),
                    ft.ElevatedButton(
                        "Continue without",
                        icon=ft.Icons.ARROW_FORWARD,
                        on_click=self._skip,
                        style=ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=30, vertical=15)),
                    ),
                ]),
            ],
            spacing=10,
            expand=True,
        )

    def _lookup_dvdcompare(self):
        """Fetch dvdcompare releases in background."""
        tmdb_match = self.app.state["tmdb_match"]
        title = tmdb_match.title if tmdb_match else self.app.state["title"]

        try:
            disc_format = self._detect_disc_format()
            year = tmdb_match.year if tmdb_match else None
            film = asyncio.run(find_film(title, disc_format, year=year))
            self.app.state["_dvdcompare_film"] = film
        except Exception as exc:
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

    def _skip(self, e):
        """Proceed without dvdcompare data."""
        self.app.state["dvdcompare_discs"] = []
        self.app.navigate(self._next_screen)

    def _use_release(self, release):
        """Convert a dvdcompare release to PlannedDiscs and navigate."""
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
