"""Selection screen - choose which titles to rip from the disc."""

import flet as ft

from riplex.config import get_rip_output
from riplex.disc.analysis import build_dvd_entries, classify_title, format_seconds, select_rippable_titles
from riplex.disc.makemkv import DiscTitle


def _format_size(size_bytes: int) -> str:
    """Format bytes as GB."""
    gb = size_bytes / (1024 ** 3)
    return f"{gb:.1f} GB"


class SelectionScreen:
    def __init__(self, app):
        self.app = app
        self.checkboxes: list[ft.Checkbox] = []

    def build(self) -> ft.Control:
        disc_info = self.app.state["disc_info"]
        tmdb_match = self.app.state["tmdb_match"]
        dvdcompare_discs = self.app.state.get("dvdcompare_discs", [])
        titles = disc_info.titles if disc_info else []

        # Build classification data from dvdcompare
        is_movie = tmdb_match.media_type == "movie" if tmdb_match else True
        movie_runtime = self.app.state.get("movie_runtime")

        dvd_entries: list[tuple[str, int, str]] = []
        total_episode_runtime = 0
        episode_count = 0
        if dvdcompare_discs:
            dvd_entries, total_episode_runtime, episode_count = build_dvd_entries(dvdcompare_discs)

        # Classify each title using dvdcompare data
        classifications: dict[int, str] = {}
        rippable = select_rippable_titles(
            disc_info, dvd_entries, is_movie, movie_runtime,
            total_episode_runtime, episode_count,
        )
        rippable_indices = {t.index for t in rippable}
        for t in titles:
            classifications[t.index] = classify_title(
                t, titles, dvd_entries, is_movie, movie_runtime,
                total_episode_runtime, episode_count,
            )

        self.checkboxes = []
        title_rows = []

        for t in titles:
            is_recommended = t.index in rippable_indices
            classification = classifications.get(t.index, "")
            cb = ft.Checkbox(
                value=is_recommended,
                data=t.index,
            )
            self.checkboxes.append(cb)

            rec_badge = ft.Container(
                ft.Text("RIP", size=10, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                bgcolor=ft.Colors.GREEN_700,
                border_radius=4,
                padding=ft.padding.symmetric(horizontal=6, vertical=2),
                visible=is_recommended,
            )
            skip_badge = ft.Container(
                ft.Text("SKIP", size=10, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                bgcolor=ft.Colors.RED_700,
                border_radius=4,
                padding=ft.padding.symmetric(horizontal=6, vertical=2),
                visible=not is_recommended,
            )

            # Use classification as the display name (comes from dvdcompare matching)
            display_name = classification or t.filename or f"Title {t.index}"

            row = ft.Row(
                [
                    cb,
                    ft.Text(f"#{t.index}", width=30, size=12, color=ft.Colors.GREY_500),
                    ft.Text(format_seconds(t.duration_seconds), width=70, size=12),
                    ft.Text(_format_size(t.size_bytes), width=70, size=12),
                    ft.Text(t.resolution, width=90, size=12),
                    rec_badge,
                    skip_badge,
                    ft.Text(display_name, size=12, color=ft.Colors.GREY_300, expand=True),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
            title_rows.append(row)

        # Summary
        total_selected = sum(1 for cb in self.checkboxes if cb.value)
        total_size = sum(
            titles[i].size_bytes
            for i, cb in enumerate(self.checkboxes)
            if cb.value
        )

        self.summary_text = ft.Text(
            f"{total_selected} titles selected ({_format_size(total_size)})",
            size=14,
            weight=ft.FontWeight.BOLD,
        )

        # Header row
        header = ft.Row(
            [
                ft.Container(width=48),  # checkbox space
                ft.Text("#", width=30, size=11, color=ft.Colors.GREY_500, weight=ft.FontWeight.BOLD),
                ft.Text("Duration", width=70, size=11, color=ft.Colors.GREY_500, weight=ft.FontWeight.BOLD),
                ft.Text("Size", width=70, size=11, color=ft.Colors.GREY_500, weight=ft.FontWeight.BOLD),
                ft.Text("Resolution", width=90, size=11, color=ft.Colors.GREY_500, weight=ft.FontWeight.BOLD),
                ft.Text("", width=50),
                ft.Text("Name", size=11, color=ft.Colors.GREY_500, weight=ft.FontWeight.BOLD, expand=True),
            ],
            spacing=8,
        )

        # Wire up checkboxes to update summary
        for cb in self.checkboxes:
            cb.on_change = self._update_summary

        match_label = ""
        if tmdb_match:
            year_str = f" ({tmdb_match.year})" if tmdb_match.year else ""
            match_label = f"{tmdb_match.title}{year_str}"

        back_btn = ft.TextButton("Back", on_click=lambda _: self.app.navigate("metadata"))
        start_btn = ft.ElevatedButton(
            "Start Rip",
            icon=ft.Icons.PLAY_ARROW,
            on_click=self._start_rip,
            style=ft.ButtonStyle(
                padding=ft.padding.symmetric(horizontal=30, vertical=15),
                bgcolor=ft.Colors.GREEN_700,
            ),
        )

        return ft.Column(
            [
                ft.Text("Select Titles to Rip", size=24, weight=ft.FontWeight.BOLD),
                ft.Text(match_label, size=14, color=ft.Colors.GREY_400) if match_label else ft.Container(),
                ft.Text(
                    "Titles marked RIP are recommended based on dvdcompare data and "
                    "duration matching. Uncheck any you don't want. Titles marked SKIP "
                    "are duplicates, play-alls, or very short clips.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                ft.Divider(height=20),
                header,
                ft.Column(title_rows, spacing=4, scroll=ft.ScrollMode.AUTO, expand=True),
                ft.Divider(height=10),
                self.summary_text,
                ft.Container(height=10),
                ft.Row([back_btn, start_btn]),
            ],
            spacing=10,
            expand=True,
        )

    def _update_summary(self, e):
        """Update the summary text when checkboxes change."""
        disc_info = self.app.state["disc_info"]
        titles = disc_info.titles if disc_info else []
        total_selected = sum(1 for cb in self.checkboxes if cb.value)
        total_size = sum(
            titles[i].size_bytes
            for i, cb in enumerate(self.checkboxes)
            if cb.value and i < len(titles)
        )
        self.summary_text.value = f"{total_selected} titles selected ({_format_size(total_size)})"
        self.app.page.update()

    def _start_rip(self, e):
        """Collect selected titles and proceed to rip."""
        selected = [cb.data for cb in self.checkboxes if cb.value]
        if not selected:
            return

        self.app.state["selected_titles"] = selected

        # Build output directory
        tmdb_match = self.app.state["tmdb_match"]
        if tmdb_match:
            from riplex.manifest import build_rip_path
            output_dir = build_rip_path(tmdb_match.title, tmdb_match.year or 0)
        else:
            from pathlib import Path
            rip_output = get_rip_output()
            output_dir = Path(rip_output) / self.app.state["title"]

        self.app.state["output_dir"] = output_dir

        self.app.navigate("progress")
