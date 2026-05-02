"""Metadata screen - TMDb search and title selection."""

import asyncio
import threading

import flet as ft

from riplex.config import get_api_key
from riplex.metadata.provider import MetadataSearchResult
from riplex.metadata.sources.tmdb import TmdbProvider


class MetadataScreen:
    def __init__(self, app):
        self.app = app
        self.tmdb_results: list[MetadataSearchResult] = []

    @property
    def _back_screen(self) -> str:
        return "folder_picker" if self.app.state.get("workflow") == "organize" else "disc_detection"

    def build(self) -> ft.Control:
        title = self.app.state["title"]

        # Check if results already fetched (re-render after background search)
        cached_results = self.app.state.pop("_tmdb_results", None)
        if cached_results is not None:
            self.tmdb_results = cached_results
            return self._build_results_view(title)

        # Error state
        tmdb_error = self.app.state.pop("_tmdb_error", None)
        if tmdb_error:
            return self._build_error_view(title, tmdb_error)

        # Loading state
        content = ft.Column(
            [
                ft.Text("Metadata Lookup", size=24, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "Searching TMDb for the correct movie or TV show match.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                ft.Divider(height=20),
                ft.Row([
                    ft.ProgressRing(width=30, height=30),
                    ft.Text(f"Searching TMDb for \"{title}\"...", size=14),
                ], spacing=10),
                ft.Container(expand=True),
                ft.TextButton("Back", on_click=lambda _: self.app.navigate(self._back_screen)),
            ],
            spacing=10,
            expand=True,
        )

        # Start search in background
        threading.Thread(target=self._search_tmdb, daemon=True).start()

        return content

    def _build_results_view(self, title: str) -> ft.Control:
        """Build the view showing TMDb results."""
        if not self.tmdb_results:
            return self._build_error_view(title, "No results found. Try a different title.")

        self.radio_group = ft.RadioGroup(
            content=ft.Column(
                [self._build_result_row(i, r) for i, r in enumerate(self.tmdb_results)],
                spacing=2,
            ),
            value="0",
        )

        return ft.Column(
            [
                ft.Text("Metadata Lookup", size=24, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "Choose the correct movie or TV show from the results below. "
                    "This determines the title, year, and runtime used for matching.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                ft.Divider(height=20),
                ft.Text("Select a match:", size=14),
                self.radio_group,
                ft.Container(expand=True),
                ft.Row([
                    ft.TextButton("Back", on_click=lambda _: self.app.navigate(self._back_screen)),
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

    def _build_error_view(self, title: str, error: str) -> ft.Control:
        """Build the error view."""
        return ft.Column(
            [
                ft.Text("Metadata Lookup", size=24, weight=ft.FontWeight.BOLD),
                ft.Divider(height=20),
                ft.Text(error, size=14, color=ft.Colors.ORANGE),
                ft.Container(expand=True),
                ft.TextButton("Back", on_click=lambda _: self.app.navigate(self._back_screen)),
            ],
            spacing=10,
            expand=True,
        )

    def _search_tmdb(self):
        """Search TMDb in background, then re-navigate to show results."""
        try:
            api_key = get_api_key()
            title = self.app.state["title"]

            async def _do_search():
                provider = TmdbProvider(api_key)
                try:
                    return await provider.search(title)
                finally:
                    await provider.close()

            results = asyncio.run(_do_search())
            # Reorder: best match first (same logic as CLI planner)
            candidates = results[:8]
            if candidates:
                query_lower = title.lower()
                exact = [r for r in candidates if r.title.lower() == query_lower]
                auto_pick = exact[0] if exact else candidates[0]
                candidates = [auto_pick] + [r for r in candidates if r is not auto_pick]
            self.app.state["_tmdb_results"] = candidates

        except Exception as exc:
            self.app.state["_tmdb_error"] = str(exc)

        # Schedule navigation on main event loop
        async def _nav():
            self.app.navigate("metadata")

        self.app.page.run_task(_nav)

    def _build_result_row(self, idx: int, result: MetadataSearchResult) -> ft.Radio:
        """Build a radio option for a TMDb result."""
        year_str = str(result.year) if result.year else "?"
        overview = result.overview[:100] + "..." if len(result.overview) > 100 else result.overview
        label = f"{result.title} ({year_str}) [{result.media_type}]"
        if idx == 0:
            label += "  (* recommended)"
        if overview:
            label += f"\n    {overview}"

        return ft.Radio(
            value=str(idx),
            label=label,
        )

    def _next(self, e):
        """Store TMDb selection, fetch movie detail for runtime, and navigate."""
        idx = int(self.radio_group.value)
        selected = self.tmdb_results[idx]
        self.app.state["tmdb_match"] = selected

        # For movies, fetch full detail to get runtime before proceeding
        if selected.media_type == "movie":
            threading.Thread(target=self._fetch_movie_detail, daemon=True).start()
        else:
            self.app.state["movie_runtime"] = None
            self.app.navigate("release")

    def _fetch_movie_detail(self):
        """Fetch movie runtime from TMDb in background."""
        try:
            api_key = get_api_key()
            source_id = self.app.state["tmdb_match"].source_id

            async def _do_fetch():
                provider = TmdbProvider(api_key)
                try:
                    return await provider.get_movie_detail(source_id)
                finally:
                    await provider.close()

            detail = asyncio.run(_do_fetch())
            self.app.state["movie_runtime"] = detail.runtime_seconds
        except Exception:
            self.app.state["movie_runtime"] = None

        async def _nav():
            self.app.navigate("release")

        self.app.page.run_task(_nav)
