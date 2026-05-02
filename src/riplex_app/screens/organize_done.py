"""Organize done screen - results summary after organizing."""

import logging
import os
import platform
import subprocess
from pathlib import Path

import flet as ft

from riplex.config import get_archive_root, get_output_root
from riplex.models import PlannedMovie
from riplex.organizer import archive_source_folder

log = logging.getLogger(__name__)


class OrganizeDoneScreen:
    def __init__(self, app):
        self.app = app

    def build(self) -> ft.Control:
        plan = self.app.state.get("organize_plan")
        actions = self.app.state.get("organize_results", [])
        planned = self.app.state.get("_organize_planned")

        # Compute stats
        move_count = 0
        split_count = 0
        unmatched_count = 0
        missing_count = 0
        if plan:
            move_count = len(plan.moves)
            split_count = len(plan.splits)
            unmatched_count = len(plan.unmatched)
            missing_count = len(plan.missing)

        total_organized = move_count + sum(
            len(s.chapter_destinations) for s in (plan.splits if plan else [])
        )

        # Determine output folder
        output_root = get_output_root()
        output_folder = None
        if planned and output_root:
            if isinstance(planned, PlannedMovie):
                output_folder = Path(output_root) / "Movies" / f"{planned.canonical_title} ({planned.year})"
            else:
                output_folder = Path(output_root) / "TV Shows" / f"{planned.canonical_title} ({planned.year})"

        # Title
        title_text = ""
        if planned:
            title_text = f"{planned.canonical_title} ({planned.year})"

        # Summary stats
        stat_rows = []
        if total_organized:
            stat_rows.append(
                ft.Row([
                    ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN, size=18),
                    ft.Text(f"{total_organized} file{'s' if total_organized != 1 else ''} organized", size=14),
                ], spacing=8)
            )
        if split_count:
            stat_rows.append(
                ft.Row([
                    ft.Icon(ft.Icons.CONTENT_CUT, color=ft.Colors.BLUE, size=18),
                    ft.Text(f"{split_count} file{'s' if split_count != 1 else ''} split by chapter", size=14),
                ], spacing=8)
            )
        if unmatched_count:
            stat_rows.append(
                ft.Row([
                    ft.Icon(ft.Icons.WARNING, color=ft.Colors.ORANGE, size=18),
                    ft.Text(f"{unmatched_count} file{'s' if unmatched_count != 1 else ''} skipped (unmatched)", size=14),
                ], spacing=8)
            )
        if missing_count:
            stat_rows.append(
                ft.Row([
                    ft.Icon(ft.Icons.WARNING, color=ft.Colors.ORANGE, size=18),
                    ft.Text(f"{missing_count} expected file{'s' if missing_count != 1 else ''} not found", size=14),
                ], spacing=8)
            )

        sections = [
            ft.Text("Organize Complete", size=24, weight=ft.FontWeight.BOLD),
            ft.Text(
                "Files have been moved into the Plex-compatible folder structure.",
                size=13,
                color=ft.Colors.GREY_500,
            ),
            ft.Divider(height=20),
        ]

        if title_text:
            sections.append(ft.Text(title_text, size=16, weight=ft.FontWeight.BOLD))

        if stat_rows:
            sections.append(ft.Column(stat_rows, spacing=4))

        if output_folder:
            sections.append(ft.Container(height=8))
            sections.append(ft.Text(f"Output: {output_folder}", size=12, color=ft.Colors.GREY_400))

        # Archive source folder if configured
        source_folder = self.app.state.get("source_folder")
        archive_root = get_archive_root()
        if source_folder and archive_root and source_folder.exists():
            archive_dest = archive_source_folder(source_folder, archive_root)
            if archive_dest:
                sections.append(ft.Container(height=4))
                sections.append(
                    ft.Row([
                        ft.Icon(ft.Icons.ARCHIVE, color=ft.Colors.BLUE_300, size=16),
                        ft.Text(
                            f"Archived rip folder to: {archive_dest}",
                            size=12,
                            color=ft.Colors.GREY_400,
                        ),
                    ], spacing=6)
                )
            else:
                log.warning("Archive failed for %s", source_folder)

        sections.append(ft.Container(expand=True))

        # Buttons
        buttons = []
        if output_folder:
            buttons.append(
                ft.ElevatedButton(
                    "Open Folder",
                    icon=ft.Icons.FOLDER_OPEN,
                    on_click=lambda _: self._open_folder(output_folder),
                )
            )
        buttons.append(
            ft.ElevatedButton(
                "Organize Another",
                icon=ft.Icons.REFRESH,
                on_click=self._organize_another,
            )
        )
        buttons.append(
            ft.OutlinedButton(
                "Done",
                on_click=lambda _: self.app.navigate("welcome"),
            )
        )
        sections.append(ft.Row(buttons, spacing=12))

        return ft.Column(
            sections,
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def _open_folder(self, folder: Path):
        """Open the output folder in the system file manager."""
        folder_str = str(folder)
        system = platform.system()
        if system == "Windows":
            os.startfile(folder_str)
        elif system == "Darwin":
            subprocess.Popen(["open", folder_str])
        else:
            subprocess.Popen(["xdg-open", folder_str])

    def _organize_another(self, e):
        """Reset organize state and go to folder picker."""
        self.app.state["source_folder"] = None
        self.app.state["scanned"] = None
        self.app.state["organize_plan"] = None
        self.app.state["organize_results"] = None
        self.app.state["tmdb_match"] = None
        self.app.state["dvdcompare_discs"] = []
        self.app.state["title"] = ""
        self.app.state["movie_runtime"] = None
        self.app.navigate("folder_picker")
