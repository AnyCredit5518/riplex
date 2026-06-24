"""Welcome screen - checks config, tool availability, and offers workflow choice."""

import logging
import shutil
import threading
import webbrowser
from pathlib import Path

import flet as ft

from riplex.config import load_config, get_api_key
from riplex.disc.makemkv import find_makemkvcon
from riplex.scanner import find_ffprobe
from riplex.updater import check_for_update, get_current_version

log = logging.getLogger(__name__)


def has_complete_config(config: dict) -> bool:
    """Return True when required GUI setup values are present."""
    return bool(
        config
        and config.get("tmdb_api_key")
        and config.get("output_root")
        and config.get("rip_output")
    )


def should_show_setup(config: dict, state: dict) -> bool:
    """Return True when the welcome screen should show setup fields."""
    return not has_complete_config(config) or bool(state.get("_show_setup"))


class WelcomeScreen:
    def __init__(self, app):
        self.app = app

    def build(self) -> ft.Control:
        config = load_config()
        has_api_key = bool(config and config.get("tmdb_api_key"))
        has_config = has_complete_config(config)
        show_setup = should_show_setup(config, self.app.state)
        has_makemkv = find_makemkvcon() is not None
        has_ffprobe = find_ffprobe() is not None
        from riplex.splitter import find_mkvmerge
        has_mkvmerge = find_mkvmerge() is not None

        # Status indicators
        checks = [
            ("Config file", has_config),
            ("TMDb API key", has_api_key),
            ("makemkvcon", has_makemkv),
            ("ffprobe", has_ffprobe),
            ("mkvmerge", has_mkvmerge),
        ]

        missing_tools = []
        if not has_makemkv:
            missing_tools.append("makemkvcon")
        if not has_ffprobe:
            missing_tools.append("ffprobe")
        if not has_mkvmerge:
            missing_tools.append("mkvmerge")
        self._missing_tools = missing_tools

        status_rows = []
        for label, ok in checks:
            icon = ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN) if ok else ft.Icon(ft.Icons.ERROR, color=ft.Colors.RED)
            status_rows.append(
                ft.Row([icon, ft.Text(label, size=14)], spacing=8)
            )

        # Online service connectivity (checked in background)
        self._tmdb_status_icon = ft.Icon(ft.Icons.HOURGLASS_EMPTY, color=ft.Colors.GREY_500)
        self._tmdb_status_text = ft.Text("TMDb API", size=14, color=ft.Colors.GREY_500)
        self._dvdc_status_icon = ft.Icon(ft.Icons.HOURGLASS_EMPTY, color=ft.Colors.GREY_500)
        self._dvdc_status_text = ft.Text("dvdcompare.net", size=14, color=ft.Colors.GREY_500)
        status_rows.append(ft.Row([self._tmdb_status_icon, self._tmdb_status_text], spacing=8))
        status_rows.append(ft.Row([self._dvdc_status_icon, self._dvdc_status_text], spacing=8))

        # Install tools section (shown when tools are missing)
        self._install_status = ft.Text("", size=12, color=ft.Colors.GREY_400)
        self._install_progress = ft.ProgressBar(visible=False, width=400)
        install_section = ft.Container(
            ft.Column([
                ft.Text(
                    "Some tools are missing. Click below to install them automatically, "
                    "or use the links to download manually.",
                    size=13,
                    color=ft.Colors.ORANGE,
                ),
                ft.Container(height=4),
                ft.Row([
                    ft.ElevatedButton(
                        "Install Missing Tools",
                        icon=ft.Icons.DOWNLOAD,
                        on_click=self._on_install_click,
                    ),
                    ft.TextButton(
                        "MakeMKV ↗",
                        url="https://www.makemkv.com/download/",
                    ),
                    ft.TextButton(
                        "FFmpeg ↗",
                        url="https://ffmpeg.org/download.html",
                    ),
                    ft.TextButton(
                        "MKVToolNix ↗",
                        url="https://mkvtoolnix.download/downloads.html",
                    ),
                ], spacing=8, wrap=True),
                self._install_progress,
                self._install_status,
            ], spacing=4),
            visible=bool(missing_tools),
        )

        # Rip requires all tools; organize only needs ffprobe + config
        can_rip = all(ok for _, ok in checks)
        can_organize = has_config and has_ffprobe

        # Setup fields (shown if config missing or user chooses to edit)
        self.api_key_field = ft.TextField(
            label="TMDb API key",
            value=config.get("tmdb_api_key", ""),
            password=True,
            can_reveal_password=True,
            expand=True,
        )
        self.output_root_field = ft.TextField(
            label="Media library root",
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
                    "Required. Get a free API Key or Read Access Token at "
                    "themoviedb.org/settings/api — used to look up movie and "
                    "TV show metadata.",
                    size=11,
                    color=ft.Colors.GREY_600,
                ),
                ft.Container(height=8),
                _make_browse_row(self.output_root_field),
                ft.Text(
                    "Your media library root. Organized files will be placed "
                    "into Movies/ and TV Shows/ subfolders here using "
                    "Plex-compatible naming.",
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
                ft.Row(
                    [
                        ft.ElevatedButton("Save Config", on_click=self._save_config),
                        ft.TextButton(
                            "Cancel",
                            on_click=self._hide_setup,
                            visible=has_config,
                        ),
                    ],
                    spacing=8,
                ),
            ],
            spacing=4,
            visible=show_setup,
        )

        # Workflow buttons
        rip_button = ft.ElevatedButton(
            "Rip Disc",
            icon=ft.Icons.ALBUM,
            on_click=self._start_rip,
            disabled=not can_rip,
            style=ft.ButtonStyle(padding=ft.Padding(left=30, top=15, right=30, bottom=15)),
            tooltip="Detect a disc, look up metadata, rip selected titles, and organize into your media library.",
        )
        organize_button = ft.ElevatedButton(
            "Organize Rips",
            icon=ft.Icons.FOLDER_OPEN,
            on_click=self._start_organize,
            disabled=not can_organize,
            style=ft.ButtonStyle(padding=ft.Padding(left=30, top=15, right=30, bottom=15)),
            tooltip="Organize existing MKV rips into Plex-compatible folder structure.",
        )

        # Update banner (hidden until check completes)
        self.update_banner = ft.Container(
            ft.Row(
                [
                    ft.Icon(ft.Icons.SYSTEM_UPDATE, color=ft.Colors.BLUE_700),
                    ft.Text("", size=13, color=ft.Colors.BLUE_900),
                    ft.TextButton("View Details", on_click=self._open_update),
                ],
                spacing=8,
            ),
            bgcolor=ft.Colors.BLUE_50,
            border_radius=8,
            padding=ft.Padding(left=12, top=8, right=12, bottom=8),
            visible=False,
        )
        self._update_info = None

        return ft.Column(
            [
                ft.Text("riplex", size=32, weight=ft.FontWeight.BOLD),
                ft.Text(
                    f"v{get_current_version()}",
                    size=12,
                    color=ft.Colors.GREY_500,
                ),
                self.update_banner,
                ft.Text(
                    "Rip physical discs and organize them into a media library with Plex-compatible naming.",
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
                install_section,
                ft.Container(height=10),
                ft.Row(
                    [
                        ft.OutlinedButton(
                            "Edit Settings",
                            icon=ft.Icons.SETTINGS,
                            on_click=self._show_setup,
                            visible=has_config and not show_setup,
                        ),
                    ],
                ),
                setup_section,
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
            try:
                import tkinter as tk
                from tkinter import filedialog
            except ModuleNotFoundError:
                field.hint_text = "Folder picker unavailable — type the path manually (brew install python-tk@3.12 to enable it)"
                self.app.page.update()
                return

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

    def check_for_updates(self):
        """Run update check in background thread (call after page is available)."""
        def _check():
            info = check_for_update()
            if info:
                self._update_info = info
                # Update UI from main thread
                import asyncio

                async def _show():
                    banner_row = self.update_banner.content
                    banner_row.controls[1] = ft.Text(
                        f"Update available: {info['tag']}",
                        size=13,
                        color=ft.Colors.BLUE_900,
                    )
                    self.update_banner.visible = True
                    self.app.page.update()

                self.app.page.run_task(_show)

        threading.Thread(target=_check, daemon=True).start()

    def check_connectivity(self):
        """Ping TMDb and dvdcompare.net in background and update status icons.

        Results are cached on ``self.app.state`` for the session so revisiting
        the welcome screen does not re-fire requests. The dvdcompare ping uses
        the same browser-like User-Agent and headers as the real scraper so
        the status check itself can't trip bot detection.
        """
        import httpx
        from dvdcompare.scraper import build_browser_headers

        # Session-cached results — never re-ping in the same process.
        cached_tmdb = self.app.state.get("_connectivity_tmdb")
        cached_dvdc = self.app.state.get("_connectivity_dvdc")
        if cached_tmdb is not None and cached_dvdc is not None:
            self._apply_connectivity(cached_tmdb, cached_dvdc)
            return

        def _ping(url: str, *, headers: dict | None = None, timeout: float = 5.0) -> bool:
            try:
                # Use GET, not HEAD — HEAD is uncommon in browsers and some
                # WAFs treat it as a bot signal. We're hitting the homepage
                # which a browser visit would hit anyway.
                resp = httpx.get(
                    url,
                    headers=headers,
                    timeout=timeout,
                    follow_redirects=True,
                )
                return resp.status_code < 500
            except Exception:
                return False

        def _check():
            # TMDb: small, cheap, well-known API endpoint. The default httpx
            # UA is fine here because TMDb is not bot-sensitive.
            tmdb_ok = _ping("https://api.themoviedb.org/3")
            # dvdcompare: browser headers so this ping is indistinguishable
            # from a normal homepage visit.
            dvdc_ok = _ping("https://www.dvdcompare.net/", headers=build_browser_headers())

            self.app.state["_connectivity_tmdb"] = tmdb_ok
            self.app.state["_connectivity_dvdc"] = dvdc_ok

            async def _update():
                self._apply_connectivity(tmdb_ok, dvdc_ok)
                self.app.page.update()

            self.app.page.run_task(_update)

        threading.Thread(target=_check, daemon=True).start()

    def _apply_connectivity(self, tmdb_ok: bool, dvdc_ok: bool) -> None:
        """Update the status icons / text given known connectivity results."""
        self._tmdb_status_icon.name = ft.Icons.CHECK_CIRCLE if tmdb_ok else ft.Icons.WARNING
        self._tmdb_status_icon.color = ft.Colors.GREEN if tmdb_ok else ft.Colors.ORANGE
        self._tmdb_status_text.color = None if tmdb_ok else ft.Colors.ORANGE
        self._tmdb_status_text.value = "TMDb API" if tmdb_ok else "TMDb API (unreachable)"

        self._dvdc_status_icon.name = ft.Icons.CHECK_CIRCLE if dvdc_ok else ft.Icons.WARNING
        self._dvdc_status_icon.color = ft.Colors.GREEN if dvdc_ok else ft.Colors.ORANGE
        self._dvdc_status_text.color = None if dvdc_ok else ft.Colors.ORANGE
        self._dvdc_status_text.value = "dvdcompare.net" if dvdc_ok else "dvdcompare.net (unreachable)"

    def _open_update(self, e):
        """Navigate to the in-app update screen."""
        if self._update_info:
            self.app.state["update_info"] = self._update_info
            self.app.navigate("update")

    def _on_install_click(self, e):
        """Handle Install Missing Tools button click."""
        self._install_progress.visible = True
        self._install_status.value = "Starting installation..."
        self.app.page.update()
        self._install_tools(self._missing_tools)

    def _install_tools(self, missing: list[str]):
        """Install missing tools via system package manager in background."""
        import platform
        import subprocess

        system = platform.system()
        packages = {
            "Windows": {"makemkvcon": "GuinpinSoft.MakeMKV", "ffprobe": "Gyan.FFmpeg", "mkvmerge": "MoritzBunkus.MKVToolNix"},
            "Darwin": {"makemkvcon": "makemkv", "ffprobe": "ffmpeg", "mkvmerge": "mkvtoolnix"},
            "Linux": {"makemkvcon": "makemkv", "ffprobe": "ffmpeg", "mkvmerge": "mkvtoolnix"},
        }

        pkg_map = packages.get(system, {})
        to_install = sorted(set(pkg_map[t] for t in missing if pkg_map.get(t)))
        if not to_install:
            self._install_status.value = "Auto-install not supported on this platform. Use the links above."
            self._install_progress.visible = False
            self.app.page.update()
            return

        def _do_install():
            try:
                if system == "Windows":
                    cmds = " && ".join(
                        f'winget install --accept-source-agreements --accept-package-agreements {pkg}'
                        for pkg in to_install
                    )
                    self._install_status.value = f"Installing {', '.join(to_install)}... (accept the admin prompt)"
                    self.app.page.update()
                    result = subprocess.run(
                        ["powershell", "-Command",
                         f"Start-Process cmd -ArgumentList '/c {cmds} & pause' -Verb RunAs -Wait"],
                        capture_output=True,
                        text=True,
                    )
                    if result.returncode != 0:
                        raise subprocess.CalledProcessError(result.returncode, "winget", output=result.stdout, stderr=result.stderr)
                elif system == "Darwin":
                    # Check if macOS is too old for Homebrew bottles (pre-built
                    # packages).  On older versions brew compiles everything from
                    # source which can take over an hour — not a great UX.
                    mac_ver = platform.mac_ver()[0]  # e.g. "13.7.7"
                    mac_major = int(mac_ver.split(".")[0]) if mac_ver else 0
                    brew_path = shutil.which("brew")

                    if brew_path and mac_major >= 14:
                        self._install_status.value = (
                            f"Installing {', '.join(to_install)} via Homebrew — "
                            "this may take several minutes..."
                        )
                        self.app.page.update()
                        proc = subprocess.Popen(
                            ["brew", "install"] + to_install,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True,
                        )
                        import time as _time
                        last_update = _time.monotonic()
                        for line in proc.stdout:
                            line = line.strip()
                            if not line:
                                continue
                            # Skip noisy Homebrew warnings about Xcode / macOS version
                            if any(s in line for s in (
                                "Tier 2", "Tier 3",
                                "Please update to Xcode",
                                "before opening any issues",
                                "Read the above",
                                "Command Line Tools",
                                "sudo rm -rf",
                                "sudo xcode-select",
                                "developer.apple.com",
                                "You are using macOS",
                                "MacPorts",
                                "docs.brew.sh/Support-Tiers",
                            )):
                                # Show a heartbeat if no useful output for a while
                                now = _time.monotonic()
                                if now - last_update > 15:
                                    self._install_status.value = "Still installing... (compiling from source, please wait)"
                                    self.app.page.update()
                                    last_update = now
                                continue
                            self._install_status.value = line
                            self.app.page.update()
                            last_update = _time.monotonic()
                        proc.wait()
                        if proc.returncode != 0:
                            raise subprocess.CalledProcessError(proc.returncode, "brew")
                    else:
                        # Old macOS or no Homebrew — auto-download ffprobe and
                        # open download pages for the other tools.
                        download_urls = {
                            "makemkv": "https://www.makemkv.com/download/",
                            "mkvtoolnix": "https://mkvtoolnix.download/downloads.html#macosx",
                        }
                        opened_pages = []
                        for pkg in to_install:
                            if pkg in download_urls:
                                webbrowser.open(download_urls[pkg])
                                opened_pages.append(pkg)

                        # Auto-download ffprobe from evermeet.cx
                        if "ffmpeg" in to_install:
                            self._install_status.value = "Downloading ffprobe..."
                            self.app.page.update()
                            try:
                                self._download_ffprobe_macos()
                            except Exception as exc:
                                webbrowser.open("https://evermeet.cx/ffmpeg/")
                                opened_pages.append("ffprobe")
                                log.warning("ffprobe auto-download failed: %s", exc)

                        if opened_pages:
                            reason = (
                                f"Your macOS version ({mac_ver}) is too old for fast Homebrew installs."
                                if mac_major < 14
                                else "Homebrew is not installed."
                            )
                            self._install_status.value = (
                                f"{reason} Download pages opened — "
                                "install the tools, then restart the app."
                            )
                        else:
                            self._install_status.value = "Done! Reloading..."
                            self._install_progress.visible = False
                            self.app.page.update()
                            import time
                            time.sleep(1.5)
                            self.app.navigate("welcome")
                            return

                        self._install_progress.visible = False
                        self.app.page.update()
                        return
                elif system == "Linux":
                    apt = shutil.which("apt-get") or shutil.which("apt")
                    if apt:
                        self._install_status.value = (
                            f"Installing {', '.join(to_install)} via apt — "
                            "this may take a minute..."
                        )
                        self.app.page.update()
                        proc = subprocess.Popen(
                            ["sudo", apt, "install", "-y"] + to_install,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True,
                        )
                        for line in proc.stdout:
                            line = line.strip()
                            if line:
                                self._install_status.value = line
                                self.app.page.update()
                        proc.wait()
                        if proc.returncode != 0:
                            raise subprocess.CalledProcessError(proc.returncode, apt)
                    else:
                        download_urls = {
                            "makemkv": "https://www.makemkv.com/download/",
                            "ffmpeg": "https://ffmpeg.org/download.html",
                            "mkvtoolnix": "https://mkvtoolnix.download/downloads.html",
                        }
                        for pkg in to_install:
                            if pkg in download_urls:
                                webbrowser.open(download_urls[pkg])
                        self._install_status.value = "Opened download pages in your browser. Install the tools, then restart the app."
                        self._install_progress.visible = False
                        self.app.page.update()
                        return
                else:
                    download_urls = {
                        "makemkv": "https://www.makemkv.com/download/",
                        "ffmpeg": "https://ffmpeg.org/download.html",
                        "mkvtoolnix": "https://mkvtoolnix.download/downloads.html",
                    }
                    for pkg in to_install:
                        if pkg in download_urls:
                            webbrowser.open(download_urls[pkg])
                    self._install_status.value = "Opened download pages in your browser. Install the tools, then restart the app."
                    self._install_progress.visible = False
                    self.app.page.update()
                    return

                self._install_status.value = "Done! Reloading..."
                self._install_progress.visible = False
                self.app.page.update()
                import time
                time.sleep(1.5)
                self.app.navigate("welcome")
            except Exception as exc:
                self._install_progress.visible = False
                self._install_status.value = f"Install failed: {exc}. Try the manual links above."
                try:
                    self.app.page.update()
                except Exception:
                    pass  # Window may have been closed during install

        threading.Thread(target=_do_install, daemon=True).start()

    def _download_ffprobe_macos(self):
        """Download a pre-built ffprobe binary to ~/.riplex/bin/.

        Uses the evermeet.cx download API which provides static Intel
        macOS binaries as .zip files (no extra dependencies needed).
        """
        import os
        import stat
        import subprocess
        import tempfile
        import urllib.request
        import zipfile

        url = "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip"
        dest_dir = Path.home() / ".riplex" / "bin"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "ffprobe"

        self._install_status.value = "Downloading ffprobe from evermeet.cx..."
        self.app.page.update()

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            urllib.request.urlretrieve(url, tmp_path)

            self._install_status.value = "Extracting ffprobe..."
            self.app.page.update()

            with zipfile.ZipFile(tmp_path) as zf:
                # The zip contains a single 'ffprobe' binary
                names = zf.namelist()
                ffprobe_name = next(
                    (n for n in names if n.rstrip("/") == "ffprobe"), names[0]
                )
                with zf.open(ffprobe_name) as src, open(dest, "wb") as dst:
                    dst.write(src.read())

            # Make executable
            dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

            # Remove macOS quarantine flag so Gatekeeper doesn't block it
            subprocess.run(
                ["xattr", "-dr", "com.apple.quarantine", str(dest)],
                capture_output=True,
            )

            self._install_status.value = f"ffprobe installed to {dest}"
            self.app.page.update()
        finally:
            Path(tmp_path).unlink(missing_ok=True)

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
        self.app.state.pop("_show_setup", None)
        self.app.navigate("welcome")

    def _show_setup(self, e):
        """Reveal config fields for editing after first-run setup."""
        self.app.state["_show_setup"] = True
        self.app.navigate("welcome")

    def _hide_setup(self, e):
        """Hide config fields without saving changes."""
        self.app.state.pop("_show_setup", None)
        self.app.navigate("welcome")

    def _start_rip(self, e):
        """Start the rip (orchestrate) workflow."""
        self.app.state["workflow"] = "orchestrate"
        self.app.state["makemkvcon"] = find_makemkvcon()
        self.app.state["disc_queue"] = []
        self.app.state["current_disc_idx"] = 0
        self.app.state["ripped_discs"] = set()
        self.app.state["all_rip_results"] = {}
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
