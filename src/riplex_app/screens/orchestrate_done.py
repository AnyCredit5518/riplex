"""Orchestrate done screen - multi-disc rip summary with auto-organize."""

import logging
import os
import platform
import subprocess
import threading

import flet as ft

from riplex.manifest import (
    build_rip_path,
    build_scanned_from_manifests,
    read_session_marker,
)

log = logging.getLogger(__name__)


class OrchestrateDoneScreen:
    """Shown after all discs in the orchestrate queue have been ripped.

    Displays a summary of all disc rips and offers to organize the
    ripped files into a Plex-compatible folder structure.
    """

    def __init__(self, app):
        self.app = app

    def build(self) -> ft.Control:
        all_results = self.app.state.get("all_rip_results", {})
        tmdb_match = self.app.state.get("tmdb_match")
        disc_queue = self.app.state.get("disc_queue", [])
        ripped_discs = self.app.state.get("ripped_discs", set())

        canonical = tmdb_match.title if tmdb_match else ""
        year = tmdb_match.year or 0 if tmdb_match else 0
        year_str = f" ({year})" if year else ""

        season = self.app.state.get("season_number") \
            if tmdb_match and getattr(tmdb_match, "media_type", "movie") == "tv" else None
        rip_root = build_rip_path(canonical, year, season_number=season)

        # Count results across all discs
        total_success = 0
        total_failed = 0
        disc_summaries = []

        for disc_num in sorted(all_results.keys()):
            results = all_results[disc_num]
            succeeded = sum(1 for r in results if r.success)
            failed = sum(1 for r in results if not r.success)
            total_success += succeeded
            total_failed += failed
            disc_summaries.append((disc_num, succeeded, failed))

        # Overall status
        if total_failed:
            icon = ft.Icon(ft.Icons.WARNING, color=ft.Colors.ORANGE, size=40)
            summary = f"{total_success} titles ripped, {total_failed} failed"
            summary_color = ft.Colors.ORANGE
        else:
            icon = ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN, size=40)
            summary = f"All {total_success} titles ripped successfully"
            summary_color = ft.Colors.GREEN

        # Per-disc breakdown
        disc_rows = []
        for disc_num, succeeded, failed in disc_summaries:
            status_icon = (
                ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN, size=16)
                if not failed else
                ft.Icon(ft.Icons.WARNING, color=ft.Colors.ORANGE, size=16)
            )
            disc_rows.append(
                ft.Row([
                    status_icon,
                    ft.Text(f"Disc {disc_num}", size=13, weight=ft.FontWeight.BOLD,
                            width=80),
                    ft.Text(f"{succeeded} titles", size=12, color=ft.Colors.GREY_400),
                    ft.Text(f"({failed} failed)" if failed else "", size=12,
                            color=ft.Colors.RED if failed else None),
                ], spacing=10)
            )

        # Skipped discs
        skipped = [n for n in disc_queue if n not in all_results and n not in ripped_discs]
        if skipped:
            for n in skipped:
                disc_rows.append(
                    ft.Row([
                        ft.Icon(ft.Icons.SKIP_NEXT, color=ft.Colors.GREY_500, size=16),
                        ft.Text(f"Disc {n}", size=13, width=80),
                        ft.Text("skipped", size=12, color=ft.Colors.GREY_500),
                    ], spacing=10)
                )

        # Previously ripped
        already_ripped = ripped_discs - set(all_results.keys())
        if already_ripped:
            for n in sorted(already_ripped):
                disc_rows.append(
                    ft.Row([
                        ft.Icon(ft.Icons.CHECK, color=ft.Colors.GREY_500, size=16),
                        ft.Text(f"Disc {n}", size=13, width=80),
                        ft.Text("previously ripped", size=12, color=ft.Colors.GREY_500),
                    ], spacing=10)
                )

        # Actions
        open_folder_btn = ft.ElevatedButton(
            "Open Folder",
            icon=ft.Icons.FOLDER_OPEN,
            on_click=self._open_folder,
        )
        organize_btn = ft.ElevatedButton(
            "Organize into Library",
            icon=ft.Icons.DRIVE_FILE_MOVE,
            on_click=self._organize,
            style=ft.ButtonStyle(
                padding=ft.Padding(left=30, top=15, right=30, bottom=15),
                bgcolor=ft.Colors.GREEN_700,
            ),
            visible=total_success > 0,
        )
        quit_btn = ft.TextButton("Quit", on_click=self._quit)

        self._organize_status = ft.Text("", size=12, color=ft.Colors.GREY_400)

        return ft.Column(
            [
                ft.Row([icon, ft.Text(f"{canonical}{year_str}", size=24,
                                      weight=ft.FontWeight.BOLD)], spacing=12),
                ft.Text(summary, size=16, color=summary_color),
                ft.Text(
                    f"Output: {rip_root}",
                    size=12,
                    color=ft.Colors.GREY_500,
                ),
                ft.Divider(height=20),
                ft.Text("Disc Summary", size=16, weight=ft.FontWeight.BOLD),
                ft.Column(disc_rows, spacing=6),
                ft.Container(height=10),
                ft.Text(
                    "All selected discs have been ripped. Click 'Organize into Library' "
                    "to match files to metadata and move them into your media library.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                self._organize_status,
                ft.Container(expand=True),
                ft.Row([open_folder_btn, organize_btn, quit_btn], spacing=12),
            ],
            spacing=10,
            expand=True,
        )

    def _open_folder(self, e):
        """Open the rip root folder."""
        tmdb_match = self.app.state.get("tmdb_match")
        if not tmdb_match:
            return
        season = self.app.state.get("season_number") \
            if getattr(tmdb_match, "media_type", "movie") == "tv" else None
        rip_root = build_rip_path(
            tmdb_match.title, tmdb_match.year or 0, season_number=season,
        )
        path = str(rip_root)
        system = platform.system()
        if system == "Windows":
            os.startfile(path)
        elif system == "Darwin":
            subprocess.run(["open", path])
        else:
            subprocess.run(["xdg-open", path])

    def _organize(self, e):
        """Scan rip manifests and navigate to organize preview."""
        tmdb_match = self.app.state.get("tmdb_match")
        if not tmdb_match:
            return

        e.control.disabled = True
        e.control.text = "Scanning..."
        self._organize_status.value = "Reading rip manifests..."
        self.app.page.update()

        def _do_organize():
            try:
                season = self.app.state.get("season_number") \
                    if getattr(tmdb_match, "media_type", "movie") == "tv" else None
                rip_root = build_rip_path(
                    tmdb_match.title, tmdb_match.year or 0,
                    season_number=season,
                )

                # Session marker fan-out: when the current rip_root sits
                # in a multi-work release (e.g. Psych TV series + linked
                # films disc), the marker names every sibling work-folder.
                # Read manifests from all of them so the organize preview
                # sees every ripped file across the whole release —
                # ``disc_groups`` (built during disc overview) covers all
                # discs, so routing to per-work Plex targets just works.
                marker = read_session_marker(rip_root)
                scanned = []
                if marker and marker.get("works"):
                    # ``w.folder`` in the marker is relative to the
                    # configured rip output root (may be nested for TV,
                    # e.g. ``Psych (2006)/Season 01``), so resolve it
                    # against that root, not ``rip_root.parent``.
                    from riplex.manifest import _session_root
                    root = _session_root()
                    for w in marker.get("works", []):
                        work_folder_name = w.get("folder", "")
                        if not work_folder_name:
                            continue
                        work_folder = root / work_folder_name
                        if not work_folder.exists():
                            log.info(
                                "Organize: work folder missing, skipping: %s",
                                work_folder,
                            )
                            continue
                        work_scanned = build_scanned_from_manifests(work_folder)
                        if work_scanned:
                            log.info(
                                "Organize: loaded %d disc(s) from %s",
                                len(work_scanned), work_folder,
                            )
                            scanned.extend(work_scanned)
                else:
                    # Single-work / legacy path.
                    scanned = build_scanned_from_manifests(rip_root)

                if not scanned:
                    # Fall back to ffprobe scan of the primary rip_root.
                    from riplex.scanner import scan_folder
                    self._organize_status.value = "No manifests found, scanning with ffprobe..."
                    self.app.page.update()
                    scanned = scan_folder(rip_root)

                self.app.state["scanned"] = scanned
                self.app.state["source_folder"] = str(rip_root)
                self.app.state["workflow"] = "organize"

                async def _nav():
                    self.app.navigate("organize_preview")

                self.app.page.run_task(_nav)

            except Exception as exc:
                log.error("Organize scan failed: %s", exc)
                self._organize_status.value = f"Error: {exc}"
                self._organize_status.color = ft.Colors.RED
                e.control.disabled = False
                e.control.text = "Organize into Library"
                self.app.page.update()

        threading.Thread(target=_do_organize, daemon=True).start()

    def _quit(self, e):
        """Close the application."""
        self.app.page.window.close()
