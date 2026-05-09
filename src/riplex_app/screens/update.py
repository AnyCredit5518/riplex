"""Update screen - shows release notes and link to download."""

import logging
import webbrowser

import flet as ft

from riplex_app.updater import get_current_version

log = logging.getLogger(__name__)


class UpdateScreen:
    def __init__(self, app):
        self.app = app

    def build(self) -> ft.Control:
        update_info = self.app.state.get("update_info")
        if not update_info:
            return ft.Column([
                ft.Text("No update information available.", size=14),
                ft.ElevatedButton("Back", on_click=self._go_back),
            ])

        tag = update_info["tag"]
        releases = update_info.get("releases", [])
        release_url = update_info.get("url", "")
        current = get_current_version()

        log.info("Update screen: %s -> %s (%d releases in series)", current, tag, len(releases))

        # Build release notes content
        notes_controls = []
        for i, rel in enumerate(releases):
            rel_body = self._clean_body(rel.get("body", ""))
            if not rel_body:
                rel_body = "*No release notes available.*"

            notes_controls.append(
                ft.Text(rel["tag"], size=16, weight=ft.FontWeight.BOLD),
            )
            notes_controls.append(
                ft.Markdown(
                    rel_body,
                    selectable=True,
                    extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                    on_tap_link=lambda e: webbrowser.open(e.data),
                ),
            )
            if i < len(releases) - 1:
                notes_controls.append(ft.Divider(height=10, color=ft.Colors.GREY_800))

        return ft.Column(
            [
                ft.Row(
                    [
                        ft.IconButton(
                            ft.Icons.ARROW_BACK,
                            on_click=self._go_back,
                            tooltip="Back to welcome",
                        ),
                        ft.Text(
                            f"Update Available: {tag}",
                            size=24,
                            weight=ft.FontWeight.BOLD,
                        ),
                    ],
                    spacing=8,
                ),
                ft.Text(
                    f"You are running v{current}",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                ft.Divider(height=20),
                ft.Text("Release Notes", size=18, weight=ft.FontWeight.BOLD),
                ft.Container(height=4),
                ft.Container(
                    ft.Column(notes_controls, spacing=8),
                    expand=True,
                    padding=ft.Padding(left=10, top=10, right=10, bottom=10),
                    border=ft.Border.all(1, ft.Colors.GREY_800),
                    border_radius=8,
                ),
                ft.Container(height=10),
                ft.Row(
                    [
                        ft.ElevatedButton(
                            "View Release & Download",
                            icon=ft.Icons.OPEN_IN_NEW,
                            on_click=lambda _: webbrowser.open(release_url),
                            style=ft.ButtonStyle(
                                padding=ft.Padding(left=30, top=15, right=30, bottom=15),
                            ),
                            disabled=not release_url,
                        ),
                        ft.OutlinedButton(
                            "Back",
                            on_click=self._go_back,
                        ),
                    ],
                    spacing=12,
                ),
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def _go_back(self, e):
        self.app.navigate("welcome")

    @staticmethod
    def _clean_body(body: str) -> str:
        """Clean up sparse or auto-generated release notes."""
        body = body.strip()
        if not body:
            return ""
        # De-duplicate repeated lines
        seen = []
        for line in body.splitlines():
            if line not in seen:
                seen.append(line)
        # If it's just changelog links with no real content, discard
        if all("full changelog" in l.lower() or not l.strip() for l in seen):
            return ""
        return "\n".join(seen)
