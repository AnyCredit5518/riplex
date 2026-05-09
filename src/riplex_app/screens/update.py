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
        body = update_info.get("body", "").strip()
        release_url = update_info.get("url", "")
        current = get_current_version()

        # Clean up sparse release notes (auto-generated GitHub changelog links)
        if body:
            # De-duplicate repeated lines
            seen = []
            for line in body.splitlines():
                if line not in seen:
                    seen.append(line)
            body = "\n".join(seen)

            # If it's just changelog links with no real content, replace with a summary
            non_empty = [l for l in seen if l.strip()]
            if all("full changelog" in l.lower() or not l.strip() for l in seen):
                body = ""

        if not body:
            body = (
                f"A new version of riplex ({tag}) is available.\n\n"
                "Visit the release page for full details and download links."
            )

        log.info("Update screen: %s -> %s", current, tag)

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
                    ft.Markdown(
                        body if body else "*No release notes available.*",
                        selectable=True,
                        extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                        on_tap_link=lambda e: webbrowser.open(e.data),
                    ),
                    expand=True,
                    padding=ft.padding.all(10),
                    border=ft.border.all(1, ft.Colors.GREY_800),
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
                                padding=ft.padding.symmetric(horizontal=30, vertical=15),
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
