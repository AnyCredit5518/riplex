"""Disc swap screen - prompts user to insert the next disc and verifies it."""

import logging
import sys
import threading

import flet as ft

from riplex.disc.analysis import build_season_labels
from riplex.disc.makemkv import run_disc_info, run_drive_list, eject_disc
from riplex.disc.provider import detect_disc_number, disc_content_summary
from riplex.title import parse_volume_label

log = logging.getLogger(__name__)


class DiscSwapScreen:
    """Shown between discs in orchestrate mode.

    Ejects the current disc, asks user to insert the target disc,
    then scans and verifies before proceeding to selection.
    """

    def __init__(self, app):
        self.app = app

    def build(self) -> ft.Control:
        disc_number = self.app.state.get("_orchestrate_disc_number")
        dvdcompare_discs = self.app.state.get("dvdcompare_discs", [])

        # Find the target disc info from dvdcompare
        target_disc = next(
            (d for d in dvdcompare_discs if d.number == disc_number), None
        )
        summary = disc_content_summary(target_disc) if target_disc else ""
        fmt = getattr(target_disc, "disc_format", None) or ""
        fmt_str = f" ({fmt})" if fmt else ""

        # Season label (e.g. "Season 1, Disc 2") when the release page
        # groups discs by season — same chip we show on Disc Overview.
        season_label = ""
        if dvdcompare_discs:
            season_label = build_season_labels(
                dvdcompare_discs,
                film_title=self.app.state.get("dvdcompare_film_title"),
            ).get(disc_number, "")

        header_children: list[ft.Control] = [
            ft.Text(
                f"Disc {disc_number}{fmt_str}",
                size=18,
                weight=ft.FontWeight.BOLD,
            ),
        ]
        if season_label:
            header_children.append(ft.Container(
                ft.Text(season_label, size=11,
                        color=ft.Colors.LIGHT_BLUE_200,
                        weight=ft.FontWeight.BOLD),
                bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.LIGHT_BLUE_400),
                border_radius=4,
                padding=ft.Padding(left=6, top=2, right=6, bottom=2),
            ))

        self.status_text = ft.Text(
            "Insert the disc and click 'Scan' when ready.",
            size=14,
            color=ft.Colors.GREY_400,
        )
        self.spinner = ft.ProgressRing(width=30, height=30, visible=False)
        self.scan_btn = ft.ElevatedButton(
            "Scan Disc",
            icon=ft.Icons.DISC_FULL,
            on_click=self._scan,
            style=ft.ButtonStyle(
                padding=ft.Padding(left=30, top=15, right=30, bottom=15),
            ),
        )
        self.eject_btn = ft.OutlinedButton(
            "Eject Current Disc",
            icon=ft.Icons.EJECT,
            on_click=self._eject,
        )
        self.skip_btn = ft.TextButton(
            "Skip This Disc",
            on_click=self._skip,
        )
        # "Back to Overview" is only safe before anything has been
        # ripped in this session — once we're mid-queue, the disc list
        # and per-group state may be inconsistent with a re-open of
        # Disc Overview.
        current_idx = self.app.state.get("current_disc_idx", 0)
        back_controls: list[ft.Control] = []
        if current_idx == 0:
            back_controls.append(ft.TextButton(
                "Back to Overview",
                icon=ft.Icons.ARROW_BACK,
                on_click=self._back_to_overview,
            ))
        quit_btn = ft.TextButton(
            "Quit",
            icon=ft.Icons.CLOSE,
            on_click=self._quit,
        )

        return ft.Column(
            [
                ft.Text("Insert Disc", size=24, weight=ft.FontWeight.BOLD),
                ft.Divider(height=20),
                ft.Container(
                    ft.Column([
                        ft.Row(header_children, spacing=8,
                               vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ft.Text(summary, size=13, color=ft.Colors.GREY_400),
                    ], spacing=4),
                    bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.WHITE),
                    border_radius=8,
                    padding=20,
                ),
                ft.Container(height=20),
                ft.Text(
                    "Please insert the disc above into your drive. "
                    "You can eject the current disc first if needed.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                ft.Container(height=10),
                ft.Row([self.spinner, self.status_text], spacing=10),
                ft.Container(expand=True),
                ft.Row(
                    [*back_controls, quit_btn, self.eject_btn,
                     self.skip_btn, self.scan_btn],
                    spacing=12,
                ),
            ],
            spacing=10,
            expand=True,
        )

    def _back_to_overview(self, e):
        """Return to Disc Overview so the user can change which disc
        is currently loaded before the first rip starts."""
        self.app.navigate("disc_overview")

    def _quit(self, e):
        """Abandon the current orchestrate session and return to the
        welcome screen. Any completed rips remain on disk and can be
        resumed later via find_existing_session."""
        self.app.navigate("welcome")

    def _eject(self, e):
        """Eject the current disc."""
        drive = self.app.state.get("drive")
        if drive and drive.device:
            self.status_text.value = "Ejecting..."
            self.app.page.update()

            def _do_eject():
                try:
                    eject_disc(drive.device)
                    self.status_text.value = "Ejected. Insert the next disc and click Scan."
                    self.status_text.color = ft.Colors.GREEN
                except Exception as exc:
                    self.status_text.value = f"Eject failed: {exc}"
                    self.status_text.color = ft.Colors.ORANGE
                self.app.page.update()

            threading.Thread(target=_do_eject, daemon=True).start()
        else:
            self.status_text.value = "No drive detected. Insert disc manually."
            self.app.page.update()

    def _skip(self, e):
        """Skip this disc and move to the next in queue."""
        self._advance_queue()

    def _scan(self, e):
        """Scan the drive for the newly inserted disc."""
        self.scan_btn.disabled = True
        self.spinner.visible = True
        self.status_text.value = "Scanning drive..."
        self.status_text.color = None
        self.app.page.update()

        threading.Thread(target=self._do_scan, daemon=True).start()

    def _do_scan(self):
        """Background: scan drive and verify disc."""
        makemkvcon = self.app.state.get("makemkvcon")
        disc_number = self.app.state.get("_orchestrate_disc_number")
        dvdcompare_discs = self.app.state.get("dvdcompare_discs", [])

        try:
            # Find drive with disc
            drives = run_drive_list(makemkvcon=makemkvcon)
            active = [d for d in drives if d.has_disc]

            if not active:
                self.status_text.value = "No disc found. Insert a disc and try again."
                self.status_text.color = ft.Colors.ORANGE
                self.scan_btn.disabled = False
                self.spinner.visible = False
                self.app.page.update()
                return

            drive = active[0]
            self.app.state["drive"] = drive

            self.status_text.value = f"Reading disc: {drive.disc_label}..."
            self.app.page.update()

            # Read disc info
            disc_info = run_disc_info(drive.index, makemkvcon=makemkvcon)
            if not disc_info or not disc_info.titles:
                self.status_text.value = "No titles found on disc. Try again."
                self.status_text.color = ft.Colors.ORANGE
                self.scan_btn.disabled = False
                self.spinner.visible = False
                self.app.page.update()
                return

            self.app.state["disc_info"] = disc_info

            # Update title from new disc label
            title = parse_volume_label(drive.disc_label)
            if title:
                self.app.state["title"] = title

            # Verify this is the expected disc
            detected = detect_disc_number(disc_info, dvdcompare_discs)
            if detected and detected != disc_number:
                self.status_text.value = (
                    f"Warning: expected Disc {disc_number} but detected Disc {detected}. "
                    "Proceeding anyway."
                )
                self.status_text.color = ft.Colors.ORANGE
                self.app.page.update()
                log.warning("Expected disc %d but detected %d", disc_number, detected)

            # Update inserted disc tracking
            self.app.state["_inserted_disc"] = detected or disc_number

            # Navigate to selection for this disc
            self.spinner.visible = False

            async def _nav():
                self.app.navigate("selection")

            self.app.page.run_task(_nav)

        except Exception as exc:
            log.error("Disc scan failed: %s", exc)
            self.status_text.value = f"Error: {exc}"
            self.status_text.color = ft.Colors.RED
            self.scan_btn.disabled = False
            self.spinner.visible = False
            self.app.page.update()

    def _advance_queue(self):
        """Move to the next disc in queue or finish."""
        disc_queue = self.app.state.get("disc_queue", [])
        current_idx = self.app.state.get("current_disc_idx", 0)
        next_idx = current_idx + 1

        if next_idx < len(disc_queue):
            self.app.state["current_disc_idx"] = next_idx
            self.app.state["_orchestrate_disc_number"] = disc_queue[next_idx]
            self.app.navigate("disc_swap")
        else:
            # All discs done — go to orchestrate done
            self.app.navigate("orchestrate_done")
