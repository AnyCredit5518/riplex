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
        self._search_field: ft.TextField | None = None

    @property
    def _back_screen(self) -> str:
        return "folder_picker" if self.app.state.get("workflow") == "organize" else "disc_detection"

    def _build_search_bar(self, title: str, *, searching: bool) -> ft.Control:
        """Search field + button so the user can refine the query in place."""
        self._search_field = ft.TextField(
            label="Search title",
            value=title,
            expand=True,
            on_submit=self._on_search_click,
            disabled=searching,
            hint_text="Edit and press Enter to search again",
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
        """Re-run TMDb search with the edited title."""
        if self._search_field is None:
            return
        new_title = (self._search_field.value or "").strip()
        if not new_title:
            return
        self.app.state["title"] = new_title
        # Clear any pending results/error so build() goes back to loading state.
        self.app.state.pop("_tmdb_results", None)
        self.app.state.pop("_tmdb_error", None)
        self.app.navigate("metadata")

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
                self._build_search_bar(title, searching=True),
                ft.Row([
                    ft.ProgressRing(width=30, height=30),
                    ft.Text(f"Searching TMDb for \"{title}\"...", size=14),
                ], spacing=10),
                ft.Container(expand=True),
                ft.Row([
                    ft.TextButton("Back", on_click=lambda _: self.app.navigate(self._back_screen)),
                    ft.TextButton("Skip", on_click=lambda _: self._continue_without_metadata(title)),
                ]),
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
                    "This determines the title, year, and runtime used for matching. "
                    "Not seeing what you expected? Edit the title and search again.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                ft.Divider(height=20),
                self._build_search_bar(title, searching=False),
                ft.Text("Select a match:", size=14),
                self.radio_group,
                ft.Container(expand=True),
                ft.Row([
                    ft.TextButton("Back", on_click=lambda _: self.app.navigate(self._back_screen)),
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

    def _build_error_view(self, title: str, error: str) -> ft.Control:
        """Build the error view with option to continue without metadata."""
        return ft.Column(
            [
                ft.Text("Metadata Lookup", size=24, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "TMDb is needed for canonical titles, years, and media-library folder "
                    "structure. Without it, you can still rip the disc and organize later.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                ft.Divider(height=20),
                self._build_search_bar(title, searching=False),
                ft.Text(error, size=14, color=ft.Colors.ORANGE),
                ft.Container(height=10),
                ft.Text(
                    f"You can continue with the disc label \"{title}\" and rip "
                    "without metadata. Organize your rips later when TMDb is available.",
                    size=13,
                ),
                ft.Container(expand=True),
                ft.Row([
                    ft.TextButton("Back", on_click=lambda _: self.app.navigate(self._back_screen)),
                    ft.ElevatedButton(
                        "Rip without metadata",
                        icon=ft.Icons.ARROW_FORWARD,
                        on_click=lambda _: self._continue_without_metadata(title),
                        style=ft.ButtonStyle(padding=ft.Padding(left=30, top=15, right=30, bottom=15)),
                    ),
                ]),
            ],
            spacing=10,
            expand=True,
        )

    def _continue_without_metadata(self, title: str):
        """Skip TMDb and proceed with volume label as title."""
        self.app.state["tmdb_match"] = None
        self.app.state["movie_runtime"] = None
        self.app.state["skip_metadata"] = True
        # Go directly to selection (skip release/dvdcompare — no metadata to match against)
        self.app.navigate("selection")

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
        # A new TMDb match invalidates any prior dvdcompare selection. The
        # release screen reuses state["release"]/state["dvdcompare_discs"] when
        # present (to avoid re-querying on back-navigation), so leaving stale
        # values here would make a freshly chosen film silently reuse the
        # previous film's disc structure — e.g. starting "The Patriot" right
        # after ripping "The Last Reef" in the same app session showed the
        # Last Reef discs. Clear them so the lookup re-runs for this film.
        self.app.state.pop("dvdcompare_title_override", None)
        self.app.state["release"] = None
        self.app.state["dvdcompare_discs"] = []
        self.app.state.pop("_dvdcompare_film", None)
        self.app.state.pop("_dvdcompare_error", None)

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
