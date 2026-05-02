"""Disc detection screen - scans drives and reads disc info."""

import sys
import threading

import flet as ft

from riplex.disc.makemkv import run_drive_list, run_disc_info, DriveInfo
from riplex.title import parse_volume_label


def _safe_update(page: ft.Page):
    """Force a UI update from a background thread."""
    try:
        page.update()
    except Exception:
        pass


class DiscDetectionScreen:
    def __init__(self, app):
        self.app = app

    def build(self) -> ft.Control:
        # Check if disc was already read (re-navigate after background read)
        disc_read_done = self.app.state.pop("_disc_read_done", False)
        drive = self.app.state.get("drive")
        disc_info = self.app.state.get("disc_info")

        if disc_read_done and disc_info and drive:
            # Show results directly
            title = self.app.state.get("title", "")
            n_titles = len(disc_info.titles)
            total_size = sum(t.size_bytes for t in disc_info.titles) / (1024 ** 3)

            self.title_field = ft.TextField(
                label="Title",
                hint_text="Auto-detected from disc label",
                value=title,
                width=500,
            )
            self.search_btn = ft.ElevatedButton(
                "Search Metadata",
                icon=ft.Icons.SEARCH,
                on_click=self._search,
                style=ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=30, vertical=15)),
            )
            self.back_btn = ft.TextButton("Back", on_click=lambda _: self.app.navigate("welcome"))

            return ft.Column(
                [
                    ft.Text("Disc Detection", size=24, weight=ft.FontWeight.BOLD),
                    ft.Text(
                        "Your disc has been read. Verify the title below and edit it if "
                        "the auto-detected name is wrong, then search for metadata.",
                        size=13,
                        color=ft.Colors.GREY_500,
                    ),
                    ft.Divider(height=20),
                    ft.Row([
                        ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN),
                        ft.Text(f"Found: {drive.disc_label} ({drive.device})", size=14, color=ft.Colors.GREEN),
                    ], spacing=10),
                    ft.Text(f"{n_titles} titles, {total_size:.1f} GB total", size=12, color=ft.Colors.GREY_400),
                    ft.Container(height=10),
                    self.title_field,
                    ft.Container(expand=True),
                    ft.Row([self.back_btn, self.search_btn]),
                ],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
            )

        # Normal flow: scanning
        self.status_text = ft.Text("Scanning drives...", size=14)
        self.spinner = ft.ProgressRing(width=30, height=30)
        self.drive_list = ft.Column(spacing=8)
        self.title_field = ft.TextField(
            label="Title",
            hint_text="Auto-detected from disc label",
            width=500,
            visible=False,
        )
        self.search_btn = ft.ElevatedButton(
            "Search Metadata",
            icon=ft.Icons.SEARCH,
            on_click=self._search,
            visible=False,
            style=ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=30, vertical=15)),
        )
        self.back_btn = ft.TextButton("Back", on_click=lambda _: self.app.navigate("welcome"))

        self.content = ft.Column(
            [
                ft.Text("Disc Detection", size=24, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "Scanning for disc drives. Make sure a disc is inserted.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                ft.Divider(height=20),
                ft.Row([self.spinner, self.status_text], spacing=10),
                self.drive_list,
                ft.Container(height=10),
                self.title_field,
                ft.Container(expand=True),
                ft.Row([self.back_btn, self.search_btn]),
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        # Start scanning in background
        threading.Thread(target=self._scan_drives, daemon=True).start()

        return self.content

    def _scan_drives(self):
        """Scan for disc drives in background thread."""
        try:
            drives = run_drive_list(makemkvcon=self.app.state["makemkvcon"])
            drives_with_disc = [d for d in drives if d.has_disc]

            if not drives_with_disc:
                self.spinner.visible = False
                self.status_text.value = "No disc found. Insert a disc and try again."
                self.status_text.color = ft.Colors.ORANGE
                self.app.page.update()
                return

            # If multiple drives with discs, let user pick
            if len(drives_with_disc) > 1:
                self.spinner.visible = False
                self.status_text.value = "Multiple discs detected. Select one:"
                for drive in drives_with_disc:
                    self.drive_list.controls.append(
                        ft.ElevatedButton(
                            f"{drive.disc_label} ({drive.device})",
                            on_click=lambda _, d=drive: self._select_drive(d),
                        )
                    )
                self.app.page.update()
            else:
                # Single drive: read it directly in this thread (no nested thread)
                drive = drives_with_disc[0]
                self.app.state["drive"] = drive
                self.status_text.value = f"Reading disc: {drive.disc_label} ({drive.device})...\nThis can take up to a minute."
                self.status_text.color = None
                self.app.page.update()
                self._read_disc(drive)

        except Exception as exc:
            self.spinner.visible = False
            self.status_text.value = f"Error scanning drives: {exc}"
            self.status_text.color = ft.Colors.RED
            self.app.page.update()

    def _select_drive(self, drive: DriveInfo):
        """Read disc info from selected drive."""
        self.app.state["drive"] = drive
        self.spinner.visible = True
        self.status_text.value = f"Reading disc: {drive.disc_label} ({drive.device})...\nThis can take up to a minute."
        self.status_text.color = None
        self.drive_list.controls.clear()
        self.app.page.update()

        threading.Thread(target=self._read_disc, args=(drive,), daemon=True).start()

    def _read_disc(self, drive: DriveInfo):
        """Read disc info in background."""
        try:
            print(f"[disc_detection] Reading disc info for drive {drive.index}...", file=sys.stderr)
            disc_info = run_disc_info(drive.index, makemkvcon=self.app.state["makemkvcon"])
            print(f"[disc_detection] Got {len(disc_info.titles) if disc_info else 0} titles", file=sys.stderr)

            if disc_info is None or not disc_info.titles:
                self.spinner.visible = False
                self.status_text.value = "No titles found on disc. Try ejecting and reinserting."
                self.status_text.color = ft.Colors.ORANGE
                _safe_update(self.app.page)
                return

            self.app.state["disc_info"] = disc_info

            # Parse title from volume label
            title = self._parse_volume_label(drive.disc_label)
            self.app.state["title"] = title
            self.app.state["_disc_read_done"] = True

            # Schedule navigation on the main event loop
            async def _nav():
                self.app.navigate("disc_detection")

            self.app.page.run_task(_nav)

        except Exception as exc:
            print(f"[disc_detection] Error: {exc}", file=sys.stderr)
            self.spinner.visible = False
            self.status_text.value = f"Error reading disc: {exc}"
            self.status_text.color = ft.Colors.RED
            _safe_update(self.app.page)

    def _parse_volume_label(self, label: str) -> str:
        """Convert volume label to a human title guess."""
        result = parse_volume_label(label)
        return result if result else label.replace("_", " ").strip().title()

    def _search(self, e):
        """Proceed to metadata lookup with the current title."""
        self.app.state["title"] = self.title_field.value.strip()
        if not self.app.state["title"]:
            self.title_field.error_text = "Enter a title"
            self.app.page.update()
            return
        self.app.navigate("metadata")
