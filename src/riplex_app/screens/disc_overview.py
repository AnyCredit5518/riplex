"""Disc overview screen - shows all discs in a release with rip status."""

import logging
import threading
from pathlib import Path

import flet as ft

from riplex.disc.provider import disc_content_summary
from riplex.manifest import build_rip_path, find_ripped_discs

log = logging.getLogger(__name__)


class DiscOverviewScreen:
    """Shows all discs in the selected dvdcompare release.

    Displays which disc is currently inserted, which have been previously
    ripped (via manifest detection), and lets the user select which discs
    to rip in this session.
    """

    def __init__(self, app):
        self.app = app
        self.checkboxes: list[ft.Checkbox] = []

    def build(self) -> ft.Control:
        tmdb_match = self.app.state["tmdb_match"]
        dvdcompare_discs = self.app.state.get("dvdcompare_discs", [])
        disc_info = self.app.state.get("disc_info")
        release = self.app.state.get("release")

        canonical = tmdb_match.title if tmdb_match else ""
        year = tmdb_match.year or 0 if tmdb_match else 0
        release_name = release.name if release else ""

        # Detect currently inserted disc
        from riplex.disc.provider import detect_disc_number
        inserted_disc = None
        if disc_info and dvdcompare_discs:
            inserted_disc = detect_disc_number(disc_info, dvdcompare_discs)
        self.app.state["_inserted_disc"] = inserted_disc

        # Find previously ripped discs from manifests
        rip_root = build_rip_path(canonical, year)
        ripped_discs = find_ripped_discs(rip_root)
        self.app.state["ripped_discs"] = ripped_discs

        log.info("Disc overview: %d discs, inserted=%s, ripped=%s",
                 len(dvdcompare_discs), inserted_disc, ripped_discs)

        # Build disc rows with checkboxes
        self.checkboxes = []
        disc_rows = []

        for disc in sorted(dvdcompare_discs, key=lambda d: d.number):
            is_ripped = disc.number in ripped_discs
            is_inserted = disc.number == inserted_disc

            cb = ft.Checkbox(
                value=not is_ripped,  # Pre-select unripped discs
                data=disc.number,
                disabled=is_ripped,
            )
            self.checkboxes.append(cb)

            # Status badge
            if is_ripped:
                badge = ft.Container(
                    ft.Text("RIPPED", size=10, color=ft.Colors.WHITE,
                            weight=ft.FontWeight.BOLD),
                    bgcolor=ft.Colors.GREEN_700,
                    border_radius=4,
                    padding=ft.Padding(left=6, top=2, right=6, bottom=2),
                )
            elif is_inserted:
                badge = ft.Container(
                    ft.Text("INSERTED", size=10, color=ft.Colors.WHITE,
                            weight=ft.FontWeight.BOLD),
                    bgcolor=ft.Colors.BLUE_700,
                    border_radius=4,
                    padding=ft.Padding(left=6, top=2, right=6, bottom=2),
                )
            else:
                badge = ft.Container(
                    ft.Text("PENDING", size=10, color=ft.Colors.WHITE,
                            weight=ft.FontWeight.BOLD),
                    bgcolor=ft.Colors.GREY_700,
                    border_radius=4,
                    padding=ft.Padding(left=6, top=2, right=6, bottom=2),
                )

            # Disc format
            fmt = getattr(disc, "disc_format", None) or ""
            fmt_text = f" ({fmt})" if fmt else ""

            # Content summary
            summary = disc_content_summary(disc)

            row = ft.Row(
                [
                    cb,
                    ft.Text(f"Disc {disc.number}{fmt_text}", width=120, size=13,
                            weight=ft.FontWeight.BOLD),
                    badge,
                    ft.Text(summary, size=12, color=ft.Colors.GREY_300,
                            expand=True),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
            disc_rows.append(row)

        # Summary
        selected_count = sum(1 for cb in self.checkboxes if cb.value)
        self.summary_text = ft.Text(
            f"{selected_count} disc(s) selected for ripping",
            size=14,
            weight=ft.FontWeight.BOLD,
        )

        # Wire checkboxes
        for cb in self.checkboxes:
            cb.on_change = self._update_summary

        # Title display
        year_str = f" ({year})" if year else ""
        match_label = f"{canonical}{year_str}"

        # Resume info
        resume_info = ft.Container()
        if ripped_discs:
            ripped_list = ", ".join(str(n) for n in sorted(ripped_discs))
            resume_info = ft.Container(
                ft.Row([
                    ft.Icon(ft.Icons.INFO, color=ft.Colors.BLUE_400, size=16),
                    ft.Text(
                        f"Previously ripped: Disc {ripped_list}. "
                        "These are already done and won't be re-ripped.",
                        size=12, color=ft.Colors.BLUE_400,
                    ),
                ], spacing=8),
                padding=ft.Padding(top=8, bottom=8),
            )

        back_btn = ft.TextButton("Back", on_click=lambda _: self.app.navigate("release"))
        start_btn = ft.ElevatedButton(
            "Start Ripping",
            icon=ft.Icons.PLAY_ARROW,
            on_click=self._start,
            style=ft.ButtonStyle(
                padding=ft.Padding(left=30, top=15, right=30, bottom=15),
                bgcolor=ft.Colors.GREEN_700,
            ),
        )

        return ft.Column(
            [
                ft.Text("Disc Overview", size=24, weight=ft.FontWeight.BOLD),
                ft.Text(match_label, size=14, color=ft.Colors.GREY_400),
                ft.Text(
                    f"Release: {release_name}" if release_name else "",
                    size=12, color=ft.Colors.GREY_500,
                ),
                ft.Text(
                    "Select which discs to rip. The currently inserted disc will "
                    "be ripped first, then you'll be prompted to insert each "
                    "remaining disc.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                ft.Divider(height=20),
                resume_info,
                ft.Column(disc_rows, spacing=8, scroll=ft.ScrollMode.AUTO,
                          expand=True),
                ft.Divider(height=10),
                self.summary_text,
                ft.Container(height=10),
                ft.Row([back_btn, start_btn]),
            ],
            spacing=10,
            expand=True,
        )

    def _update_summary(self, e):
        """Update summary when checkboxes change."""
        selected_count = sum(1 for cb in self.checkboxes if cb.value)
        self.summary_text.value = f"{selected_count} disc(s) selected for ripping"
        self.app.page.update()

    def _start(self, e):
        """Build disc queue and start the orchestrate loop."""
        selected_nums = [cb.data for cb in self.checkboxes if cb.value]
        if not selected_nums:
            return

        # Order: inserted disc first, then remaining in number order
        inserted = self.app.state.get("_inserted_disc")
        if inserted and inserted in selected_nums:
            ordered = [inserted] + sorted(n for n in selected_nums if n != inserted)
        else:
            ordered = sorted(selected_nums)

        self.app.state["disc_queue"] = ordered
        self.app.state["current_disc_idx"] = 0
        self.app.state["all_rip_results"] = {}

        log.info("Orchestrate: disc_queue=%s", ordered)

        # Start with the first disc
        self._begin_disc(ordered[0])

    def _begin_disc(self, disc_number: int):
        """Navigate to selection for the given disc number."""
        inserted = self.app.state.get("_inserted_disc")

        if disc_number == inserted:
            # Already have disc info, go straight to selection
            self.app.state["_orchestrate_disc_number"] = disc_number
            self.app.navigate("selection")
        else:
            # Need to swap disc first
            self.app.state["_orchestrate_disc_number"] = disc_number
            self.app.navigate("disc_swap")
