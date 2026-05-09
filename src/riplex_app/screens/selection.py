"""Selection screen - choose which titles to rip from the disc."""

import logging

import flet as ft

from riplex.config import get_rip_output
from riplex.disc.analysis import analyze_disc, format_seconds
from riplex.disc.makemkv import DiscTitle

log = logging.getLogger(__name__)


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

        # Debug: log release context
        log.info("=== Selection Screen ===")
        log.info("Volume label: %s", disc_info.disc_name if disc_info else None)
        log.info("dvdcompare_discs: %d discs in release", len(dvdcompare_discs))
        for d in dvdcompare_discs:
            ep_count = len(d.episodes) if hasattr(d, 'episodes') else 0
            ex_count = len(d.extras) if hasattr(d, 'extras') else 0
            log.info("  Disc %d: %d episodes, %d extras, format=%s",
                     d.number, ep_count, ex_count, getattr(d, 'disc_format', None))
        log.info("Live disc: %d titles", len(titles))

        # Build classification data from dvdcompare
        is_movie = tmdb_match.media_type == "movie" if tmdb_match else True
        movie_runtime = self.app.state.get("movie_runtime")

        # In orchestrate mode, use the explicit disc number from the queue
        orchestrate_disc_num = self.app.state.get("_orchestrate_disc_number")

        # Use shared analyze_disc — same logic as CLI rip and orchestrate
        analysis = analyze_disc(
            disc_info, dvdcompare_discs,
            disc_number=orchestrate_disc_num,
            is_movie=is_movie,
            movie_runtime=movie_runtime,
        )
        self._analysis = analysis  # store for _start_rip
        rippable_indices = {t.index for t in analysis.rippable_titles}
        classifications = analysis.classifications

        log.info("Detected disc number: %s", analysis.disc_number)
        log.info("dvd_entries: %d, total_episode_runtime: %s, episode_count: %d",
                 len(analysis.dvd_entries), format_seconds(analysis.total_episode_runtime),
                 analysis.episode_count)
        for name, runtime, etype in analysis.dvd_entries:
            log.info("  %s: %s (%s)", etype, name, format_seconds(runtime))

        log.info("is_movie=%s, movie_runtime=%s", is_movie, format_seconds(movie_runtime) if movie_runtime else None)
        log.info("%d/%d titles recommended for rip:", len(rippable_indices), len(titles))
        for t in titles:
            marker = "RIP " if t.index in rippable_indices else "SKIP"
            log.info("  [%s] #%2d  %8s  %.1f GB  %s  %s",
                     marker, t.index, format_seconds(t.duration_seconds),
                     t.size_bytes/(1024**3), t.resolution, classifications[t.index])

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

        back_target = "disc_overview" if self.app.state.get("workflow") == "orchestrate" else "metadata"
        back_btn = ft.TextButton("Back", on_click=lambda _: self.app.navigate(back_target))
        start_btn = ft.ElevatedButton(
            "Start Rip",
            icon=ft.Icons.PLAY_ARROW,
            on_click=self._start_rip,
            style=ft.ButtonStyle(
                padding=ft.padding.symmetric(horizontal=30, vertical=15),
                bgcolor=ft.Colors.GREEN_700,
            ),
        )

        # Disc number indicator for orchestrate mode
        disc_label = ""
        if self.app.state.get("workflow") == "orchestrate" and orchestrate_disc_num:
            disc_queue = self.app.state.get("disc_queue", [])
            queue_pos = disc_queue.index(orchestrate_disc_num) + 1 if orchestrate_disc_num in disc_queue else 0
            disc_label = f"Disc {orchestrate_disc_num} ({queue_pos}/{len(disc_queue)})"

        return ft.Column(
            [
                ft.Text("Select Titles to Rip", size=24, weight=ft.FontWeight.BOLD),
                ft.Text(match_label, size=14, color=ft.Colors.GREY_400) if match_label else ft.Container(),
                ft.Text(disc_label, size=13, color=ft.Colors.BLUE_400,
                        weight=ft.FontWeight.BOLD) if disc_label else ft.Container(),
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

            disc_num = self._analysis.disc_number if hasattr(self, "_analysis") else None
            output_dir = build_rip_path(tmdb_match.title, tmdb_match.year or 0, disc_number=disc_num)
        else:
            from pathlib import Path
            rip_output = get_rip_output()
            output_dir = Path(rip_output) / self.app.state["title"]

        self.app.state["output_dir"] = output_dir

        # Save early snapshot at selection phase (before rip starts)
        self._save_selection_snapshot(selected)

        self.app.navigate("progress")

    def _save_selection_snapshot(self, selected_titles: list[int]):
        """Save snapshot with disc info and metadata before rip starts."""
        from pathlib import Path
        from riplex.snapshot import get_debug_dir, save_rip_snapshot

        output_dir = self.app.state.get("output_dir")
        if not output_dir:
            return

        try:
            debug_dir = get_debug_dir(Path(output_dir).parent)
            disc_info = self.app.state.get("disc_info")
            tmdb_match = self.app.state.get("tmdb_match")
            discs = self.app.state.get("dvdcompare_discs", [])
            release = self.app.state.get("release")

            canonical = tmdb_match.title if tmdb_match else ""
            year = tmdb_match.year if tmdb_match else None
            is_movie = getattr(tmdb_match, "media_type", "movie") != "tv"
            movie_runtime = self.app.state.get("movie_runtime")

            save_rip_snapshot(
                debug_dir, disc_info,
                canonical=canonical, year=year, is_movie=is_movie,
                movie_runtime=movie_runtime,
                release_name=release.name if release else "",
                discs=discs,
                selected_titles=selected_titles,
                phase="selection",
            )
            self.app.state["debug_dir"] = str(debug_dir)
            log.info("Wrote selection snapshot to %s", debug_dir)
        except Exception as exc:
            log.warning("Failed to write selection snapshot: %s", exc)
