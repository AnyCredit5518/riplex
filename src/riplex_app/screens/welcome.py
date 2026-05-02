"""Welcome screen - checks config, tool availability, and offers workflow choice."""

import shutil
import threading

import flet as ft

from riplex.config import load_config, get_api_key
from riplex.disc.makemkv import find_makemkvcon


class WelcomeScreen:
    def __init__(self, app):
        self.app = app

    def build(self) -> ft.Control:
        config = load_config()
        has_config = bool(config and config.get("tmdb_api_key"))
        has_makemkv = find_makemkvcon() is not None
        has_ffprobe = shutil.which("ffprobe") is not None
        has_mkvmerge = shutil.which("mkvmerge") is not None

        # Status indicators
        checks = [
            ("Config file", has_config),
            ("TMDb API key", has_config),
            ("makemkvcon", has_makemkv),
            ("ffprobe", has_ffprobe),
            ("mkvmerge", has_mkvmerge),
        ]

        status_rows = []
        for label, ok in checks:
            icon = ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN) if ok else ft.Icon(ft.Icons.ERROR, color=ft.Colors.RED)
            status_rows.append(
                ft.Row([icon, ft.Text(label, size=14)], spacing=8)
            )

        # Rip requires all tools; organize only needs ffprobe + config
        can_rip = all(ok for _, ok in checks)
        can_organize = has_config and has_ffprobe

        # Setup fields (shown if config missing)
        self.api_key_field = ft.TextField(
            label="TMDb API key",
            value=config.get("tmdb_api_key", ""),
            password=True,
            can_reveal_password=True,
            expand=True,
        )
        self.output_root_field = ft.TextField(
            label="Plex library root",
            value=config.get("output_root", ""),
            expand=True,
        )
        self.rip_output_field = ft.TextField(
            label="MakeMKV rip output folder",
            value=config.get("rip_output", ""),
            expand=True,
        )
        self.archive_root_field = ft.TextField(
            label="Archive folder (optional)",
            value=config.get("archive_root", ""),
            expand=True,
        )

        def _make_browse_row(field, button_tooltip="Browse"):
            return ft.Row([
                field,
                ft.IconButton(
                    ft.Icons.FOLDER_OPEN,
                    on_click=lambda _: self._browse_for(field),
                    tooltip=button_tooltip,
                ),
            ], spacing=8)

        setup_section = ft.Column(
            [
                ft.Text("Setup", size=18, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "Configure riplex before getting started. You only need to do this once.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                ft.Container(height=4),
                self.api_key_field,
                ft.Text(
                    "Required. Get a free API key at themoviedb.org/settings/api — "
                    "used to look up movie and TV show metadata.",
                    size=11,
                    color=ft.Colors.GREY_600,
                ),
                ft.Container(height=8),
                _make_browse_row(self.output_root_field),
                ft.Text(
                    "Your Plex media library root. Organized files will be placed "
                    "into Movies/ and TV Shows/ subfolders here.",
                    size=11,
                    color=ft.Colors.GREY_600,
                ),
                ft.Container(height=8),
                _make_browse_row(self.rip_output_field),
                ft.Text(
                    "Where MakeMKV saves raw rips. This is also the default folder "
                    "shown when browsing for files to organize.",
                    size=11,
                    color=ft.Colors.GREY_600,
                ),
                ft.Container(height=8),
                _make_browse_row(self.archive_root_field),
                ft.Text(
                    "Optional. After organizing, rip folders are moved here to keep "
                    "your rip output tidy. Leave blank to skip archiving.",
                    size=11,
                    color=ft.Colors.GREY_600,
                ),
                ft.Container(height=8),
                ft.ElevatedButton("Save Config", on_click=self._save_config),
            ],
            spacing=4,
            visible=not has_config,
        )

        # Tool warning
        tool_warning = ft.Container(
            ft.Text(
                "Some required tools are missing. Install them and restart the app.",
                color=ft.Colors.ORANGE,
            ),
            visible=not can_rip and has_config,
        )

        # Workflow buttons
        rip_button = ft.ElevatedButton(
            "Rip Disc",
            icon=ft.Icons.ALBUM,
            on_click=self._start_rip,
            disabled=not can_rip,
            style=ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=30, vertical=15)),
            tooltip="Detect a disc, look up metadata, and rip selected titles.",
        )
        organize_button = ft.ElevatedButton(
            "Organize Rips",
            icon=ft.Icons.FOLDER_OPEN,
            on_click=self._start_organize,
            disabled=not can_organize,
            style=ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=30, vertical=15)),
            tooltip="Organize existing MKV rips into Plex-compatible folder structure.",
        )

        return ft.Column(
            [
                ft.Text("riplex", size=32, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "Rip physical discs and organize into Plex-compatible libraries.",
                    size=14,
                    color=ft.Colors.GREY_400,
                ),
                ft.Divider(height=20),
                ft.Text(
                    "Make sure all required tools are installed and a valid TMDb API "
                    "key is configured, then choose a workflow below.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                ft.Container(height=5),
                ft.Text("Status", size=18, weight=ft.FontWeight.BOLD),
                ft.Column(status_rows, spacing=4),
                ft.Container(height=10),
                setup_section,
                tool_warning,
                ft.Container(expand=True),
                ft.Text("What would you like to do?", size=16, weight=ft.FontWeight.BOLD),
                ft.Row([rip_button, organize_button], spacing=20),
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def _browse_for(self, field: ft.TextField):
        """Open a native folder picker and populate *field* with the result."""
        def _pick():
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = filedialog.askdirectory(
                title=f"Select {field.label}",
                initialdir=field.value or None,
            )
            root.destroy()
            if path:
                field.value = path
                self.app.page.update()

        threading.Thread(target=_pick, daemon=True).start()

    def _save_config(self, e):
        """Write config from the setup fields."""
        from riplex.config import save_config

        save_config(
            tmdb_api_key=self.api_key_field.value or "",
            output_root=self.output_root_field.value or "",
            rip_output=self.rip_output_field.value or "",
            archive_root=self.archive_root_field.value or "",
        )

        # Refresh the screen
        self.app.navigate("welcome")

    def _start_rip(self, e):
        """Start the rip workflow."""
        self.app.state["workflow"] = "rip"
        self.app.state["makemkvcon"] = find_makemkvcon()
        self.app.navigate("disc_detection")

    def _start_organize(self, e):
        """Start the organize workflow."""
        self.app.state["workflow"] = "organize"
        self.app.state["source_folder"] = None
        self.app.state["scanned"] = None
        self.app.state["organize_plan"] = None
        self.app.state["organize_results"] = None
        self.app.state["tmdb_match"] = None
        self.app.state["dvdcompare_discs"] = []
        self.app.state["title"] = ""
        self.app.state["movie_runtime"] = None
        self.app.navigate("folder_picker")
