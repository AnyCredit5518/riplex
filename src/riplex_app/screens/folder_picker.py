"""Folder picker screen - select and scan a folder of MKV rips."""

import logging
import re
import threading
from pathlib import Path

import flet as ft

log = logging.getLogger(__name__)

from riplex.config import get_rip_output
from riplex.detect import detect_format
from riplex.scanner import scan_folder
from riplex.snapshot import load_organized_marker
from riplex.title import infer_title_from_scanned


class FolderPickerScreen:
    def __init__(self, app):
        self.app = app

    def build(self) -> ft.Control:
        # Check for scan results from background thread
        scan_result = self.app.state.pop("_scan_result", None)
        if scan_result is not None:
            return self._build_results_view(scan_result)

        scan_error = self.app.state.pop("_scan_error", None)
        if scan_error:
            return self._build_error_view(scan_error)

        # If we already have scanned data (e.g. navigating back from metadata),
        # go straight to the results view without rescanning.
        existing_scanned = self.app.state.get("scanned")
        if existing_scanned:
            return self._build_results_view(existing_scanned)

        # Initial view: folder selection
        self.folder_field = ft.TextField(
            label="Folder path",
            hint_text=r"e.g. D:\Rips\My Movie (2024)",
            expand=True,
            on_submit=self._scan,
        )

        return ft.Column(
            [
                ft.Text("Organize Rips", size=24, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "Select a folder containing MKV rips. This can be a single folder "
                    "of MKV files or a multi-disc layout with Disc 1, Disc 2 subfolders.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                ft.Divider(height=20),
                ft.Row(
                    [
                        self.folder_field,
                        ft.IconButton(
                            ft.Icons.FOLDER_OPEN,
                            on_click=self._browse,
                            tooltip="Browse",
                        ),
                    ],
                    spacing=8,
                ),
                ft.Container(expand=True),
                ft.Row([
                    ft.TextButton("Back", on_click=lambda _: self.app.navigate("welcome")),
                    ft.ElevatedButton(
                        "Scan",
                        icon=ft.Icons.SEARCH,
                        on_click=self._scan,
                        style=ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=30, vertical=15)),
                    ),
                ]),
            ],
            spacing=10,
            expand=True,
        )

    def _browse(self, e):
        """Open native folder picker dialog via tkinter."""
        log.debug("_browse clicked")

        def _pick():
            import tkinter as tk
            from tkinter import filedialog

            try:
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                initial = get_rip_output() or ""
                log.debug("opening askdirectory, initial=%r", initial)
                path = filedialog.askdirectory(
                    title="Select MKV rip folder",
                    initialdir=initial or None,
                )
                root.destroy()
                log.debug("askdirectory returned %r", path)
                if path:
                    self.folder_field.value = path
                    self.app.page.update()
                    log.debug("folder_field updated to %r", path)
            except Exception:
                log.exception("_browse error")

        threading.Thread(target=_pick, daemon=True).start()

    def _scan(self, e):
        """Validate folder and start scanning."""
        path = self.folder_field.value.strip() if self.folder_field.value else ""
        if not path or not Path(path).is_dir():
            self.folder_field.error_text = "Please select a valid folder."
            self.folder_field.update()
            return
        self.folder_field.error_text = None

        self.app.state["source_folder"] = Path(path)

        # Show scanning state with progress
        self._progress_text = ft.Text("Discovering files...", size=14)
        self._progress_bar = ft.ProgressBar(width=400)
        self._progress_detail = ft.Text("", size=12, color=ft.Colors.GREY_500)

        self.app.page.controls.clear()
        self.app.page.controls.append(
            ft.Column(
                [
                    ft.Text("Organize Rips", size=24, weight=ft.FontWeight.BOLD),
                    ft.Divider(height=20),
                    self._progress_text,
                    self._progress_bar,
                    self._progress_detail,
                    ft.Container(expand=True),
                    ft.TextButton("Back", on_click=lambda _: self.app.navigate("welcome")),
                ],
                spacing=10,
                expand=True,
            )
        )
        self.app.page.update()

        threading.Thread(target=self._do_scan, args=(Path(path),), daemon=True).start()

    def _do_scan(self, folder: Path):
        """Run ffprobe scan in background."""
        log.info("scanning %s", folder)

        def _on_progress(current: int, total: int, filename: str):
            log.debug("scan progress %d/%d %s", current, total, filename)

            async def _update():
                self._progress_text.value = f"Scanning file {current} of {total}..."
                self._progress_bar.value = current / total if total else 0
                self._progress_detail.value = filename
                self.app.page.update()

            self.app.page.run_task(_update)

        try:
            scanned = scan_folder(folder, on_progress=_on_progress)
            log.info("scan complete: %d disc(s)", len(scanned))
            self.app.state["_scan_result"] = scanned
        except Exception as exc:
            log.exception("scan failed")
            self.app.state["_scan_error"] = str(exc)

        async def _nav():
            self.app.navigate("folder_picker")

        self.app.page.run_task(_nav)

    def _build_results_view(self, scanned) -> ft.Control:
        """Show scan results and let user confirm/edit title."""
        self.app.state["scanned"] = scanned

        total_files = sum(len(d.files) for d in scanned)
        disc_format = detect_format(scanned) or "unknown"

        # Check for organized marker
        marker = load_organized_marker(self.app.state["source_folder"])
        marker_banner = []
        if marker:
            when = marker.organized_at[:10] if marker.organized_at else "unknown date"
            marker_banner = [
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.INFO_OUTLINE, color=ft.Colors.AMBER_400, size=18),
                        ft.Text(
                            f"This folder was already organized on {when} "
                            f"as \"{marker.title}\". Continue anyway?",
                            size=13,
                            color=ft.Colors.AMBER_400,
                        ),
                    ], spacing=8),
                    bgcolor=ft.Colors.with_opacity(0.1, ft.Colors.AMBER),
                    padding=12,
                    border_radius=8,
                ),
            ]

        # Build disc summary rows
        disc_rows = []
        for d in scanned:
            has_4k = any(f.max_width >= 3840 for f in d.files)
            res_label = "4K" if has_4k else "1080p"
            disc_rows.append(
                ft.Text(f"  {d.folder_name}/  ({len(d.files)} files, {res_label})", size=13)
            )

        # Infer title from folder name or MKV tags
        inferred = infer_title_from_scanned(scanned)
        if not inferred:
            # Try extracting from folder name: "Title (Year)" -> "Title"
            folder_name = self.app.state["source_folder"].name
            m = re.match(r"^(.+?)\s*\(\d{4}\)$", folder_name)
            inferred = m.group(1).strip() if m else folder_name

        self.title_field = ft.TextField(
            label="Title",
            value=inferred,
            width=500,
        )

        return ft.Column(
            [
                ft.Text("Organize Rips", size=24, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "Review the scan results below. Confirm or edit the title, "
                    "then proceed to look up metadata.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                ft.Divider(height=20),
                *marker_banner,
                ft.Text(
                    f"Scanned {len(scanned)} disc{'s' if len(scanned) != 1 else ''}, "
                    f"{total_files} files ({disc_format})",
                    size=14,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Column(disc_rows, spacing=2),
                ft.Container(height=10),
                ft.Text("Detected title:", size=14),
                self.title_field,
                ft.Container(expand=True),
                ft.Row([
                    ft.TextButton("Back", on_click=lambda _: self.app.navigate("welcome")),
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

    def _build_error_view(self, error: str) -> ft.Control:
        """Show scan error."""
        return ft.Column(
            [
                ft.Text("Organize Rips", size=24, weight=ft.FontWeight.BOLD),
                ft.Divider(height=20),
                ft.Text(f"Scan failed: {error}", size=14, color=ft.Colors.ORANGE),
                ft.Container(expand=True),
                ft.TextButton("Back", on_click=lambda _: self.app.navigate("welcome")),
            ],
            spacing=10,
            expand=True,
        )

    def _next(self, e):
        """Store title and proceed to metadata lookup."""
        title = self.title_field.value.strip()
        if not title:
            self.title_field.error_text = "Title is required."
            self.title_field.update()
            return
        self.app.state["title"] = title
        self.app.navigate("metadata")
