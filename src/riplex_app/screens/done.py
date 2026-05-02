"""Done screen - shows results and offers next actions."""

import os
import platform
import subprocess
import urllib.parse
import webbrowser

import flet as ft


class DoneScreen:
    def __init__(self, app):
        self.app = app

    def build(self) -> ft.Control:
        results = self.app.state.get("rip_results", [])
        output_dir = self.app.state.get("output_dir")
        tmdb_match = self.app.state.get("tmdb_match")

        successful = [r for r in results if r.success]
        failed = [r for r in results if not r.success]

        # Title
        if tmdb_match:
            year_str = f" ({tmdb_match.year})" if tmdb_match.year else ""
            match_label = f"{tmdb_match.title}{year_str}"
        else:
            match_label = self.app.state.get("title", "")

        # Result summary
        if failed:
            icon = ft.Icon(ft.Icons.WARNING, color=ft.Colors.ORANGE, size=40)
            summary = f"{len(successful)} of {len(results)} titles ripped successfully"
            summary_color = ft.Colors.ORANGE
        else:
            icon = ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN, size=40)
            summary = f"All {len(successful)} titles ripped successfully"
            summary_color = ft.Colors.GREEN

        # File list
        file_rows = []
        for r in results:
            status_icon = ft.Icon(ft.Icons.CHECK, color=ft.Colors.GREEN, size=16) if r.success else ft.Icon(ft.Icons.CLOSE, color=ft.Colors.RED, size=16)
            filename = os.path.basename(r.output_file) if r.output_file else r.error_message
            file_rows.append(
                ft.Row([status_icon, ft.Text(filename, size=12)], spacing=8)
            )

        # Output location
        output_text = ft.Text(
            f"Output: {output_dir}",
            size=12,
            color=ft.Colors.GREY_400,
        ) if output_dir else ft.Container()

        # Action buttons
        open_folder_btn = ft.ElevatedButton(
            "Open Folder",
            icon=ft.Icons.FOLDER_OPEN,
            on_click=self._open_folder,
            visible=output_dir is not None,
        )
        rip_another_btn = ft.ElevatedButton(
            "Rip Another Disc",
            icon=ft.Icons.ALBUM,
            on_click=self._rip_another,
            style=ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=30, vertical=15)),
        )
        report_bug_btn = ft.OutlinedButton(
            "Report a Bug",
            icon=ft.Icons.BUG_REPORT,
            on_click=self._report_bug,
        )
        quit_btn = ft.TextButton("Quit", on_click=self._quit)

        return ft.Column(
            [
                ft.Row([icon, ft.Text(match_label, size=24, weight=ft.FontWeight.BOLD)], spacing=12),
                ft.Text(summary, size=16, color=summary_color),
                ft.Text(
                    "Ripped files are in the output folder below. You can open the "
                    "folder to verify, rip another disc, or report a bug if something "
                    "went wrong.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                ft.Divider(height=20),
                output_text,
                ft.Container(height=10),
                ft.Text("Files", size=14, weight=ft.FontWeight.BOLD),
                ft.Column(file_rows, spacing=4, scroll=ft.ScrollMode.AUTO, expand=True),
                ft.Container(height=10),
                ft.Row([open_folder_btn, rip_another_btn, quit_btn], spacing=12),
                ft.Row([report_bug_btn], spacing=12),
            ],
            spacing=10,
            expand=True,
        )

    def _report_bug(self, e):
        """Open a pre-filled GitHub issue in the browser."""
        disc_info = self.app.state.get("disc_info")
        debug_dir = self.app.state.get("debug_dir", "")
        results = self.app.state.get("rip_results", [])

        try:
            from importlib.metadata import version
            riplex_version = version("riplex")
        except Exception:
            riplex_version = "unknown"

        disc_name = disc_info.disc_name if disc_info else "unknown"
        title_count = len(disc_info.titles) if disc_info and disc_info.titles else 0
        failed = [r for r in results if not r.success]
        error_lines = "\n".join(
            f"- Title {r.title_index}: {r.error_message}" for r in failed
        ) if failed else "N/A"

        body = (
            f"**Environment**\n"
            f"- riplex version: {riplex_version}\n"
            f"- Platform: {platform.platform()}\n"
            f"- Frontend: GUI\n"
            f"\n"
            f"**Disc**\n"
            f"- Name: {disc_name}\n"
            f"- Titles: {title_count}\n"
            f"\n"
            f"**What happened?**\n"
            f"<!-- Describe the issue -->\n"
            f"\n"
            f"**Errors**\n"
            f"{error_lines}\n"
            f"\n"
            f"**Debug files**\n"
            f"Please zip and attach the debug folder:\n"
            f"`{debug_dir}`\n"
        )

        params = urllib.parse.urlencode({
            "template": "bug_report.yml",
            "title": f"[Bug] {disc_name}",
            "labels": "bug",
            "body": body,
        })
        url = f"https://github.com/AnyCredit5518/riplex/issues/new?{params}"
        webbrowser.open(url)

        # Copy debug folder path to clipboard
        if debug_dir:
            self.app.page.set_clipboard(debug_dir)

    def _open_folder(self, e):
        """Open the output folder in the system file manager."""
        output_dir = self.app.state.get("output_dir")
        if not output_dir:
            return
        path = str(output_dir)
        system = platform.system()
        if system == "Windows":
            os.startfile(path)
        elif system == "Darwin":
            subprocess.run(["open", path])
        else:
            subprocess.run(["xdg-open", path])

    def _rip_another(self, e):
        """Reset state and go back to disc detection."""
        self.app.state["drive"] = None
        self.app.state["disc_info"] = None
        self.app.state["title"] = ""
        self.app.state["tmdb_match"] = None
        self.app.state["release"] = None
        self.app.state["selected_titles"] = []
        self.app.state["output_dir"] = None
        self.app.state["rip_results"] = []
        self.app.navigate("disc_detection")

    def _quit(self, e):
        """Close the application."""
        self.app.page.window.close()
