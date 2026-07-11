"""Update screen - shows release notes and link to download."""

import logging
import threading
import webbrowser

import flet as ft

from riplex.updater import can_self_update, get_current_version

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

        # Action controls (populated by _action_buttons; progress/status are
        # revealed during an in-place update).
        self._progress = ft.ProgressBar(width=400, visible=False)
        self._status = ft.Text("", size=13)
        self._actions = ft.Row(self._action_buttons(release_url), spacing=12)

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
                self._progress,
                self._status,
                self._actions,
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    # ------------------------------------------------------------------
    # Actions row (in-place update when available, else browser download)
    # ------------------------------------------------------------------
    def _action_buttons(self, release_url: str) -> list[ft.Control]:
        buttons: list[ft.Control] = []
        if can_self_update():
            buttons.append(
                ft.ElevatedButton(
                    "Update & Restart",
                    icon=ft.Icons.SYSTEM_UPDATE_ALT,
                    on_click=self._start_self_update,
                    style=ft.ButtonStyle(
                        padding=ft.Padding(left=30, top=15, right=30, bottom=15),
                    ),
                    tooltip="Download the update, verify it, and restart riplex automatically.",
                )
            )
            download_label = "Download in Browser"
        else:
            download_label = "View Release & Download"
        buttons.append(
            ft.OutlinedButton(
                download_label,
                icon=ft.Icons.OPEN_IN_NEW,
                on_click=lambda _: webbrowser.open(release_url),
                disabled=not release_url,
            )
        )
        buttons.append(ft.OutlinedButton("Back", on_click=self._go_back))
        return buttons

    def _start_self_update(self, _e):
        """Kick off the in-place download + verify + swap in the background."""
        info = self.app.state.get("update_info") or {}
        self._progress.visible = True
        self._progress.value = None  # indeterminate until first byte
        self._status.value = "Downloading update\u2026"
        self._status.color = ft.Colors.BLUE_300
        self._actions.controls = [
            ft.Row([ft.ProgressRing(width=18, height=18), ft.Text("Updating\u2026")], spacing=10),
        ]
        self.app.page.update()
        threading.Thread(target=self._run_self_update, args=(info,), daemon=True).start()

    def _run_self_update(self, info: dict):
        from riplex import updater

        def _on_progress(got: int, total: int):
            frac = got / total if total else None
            pct = f" {got * 100 // total}%" if total else ""

            async def _u():
                self._progress.value = frac
                self._status.value = f"Downloading update\u2026{pct}"
                self.app.page.update()

            try:
                self.app.page.run_task(_u)
            except Exception:
                pass

        try:
            staged = updater.stage_update(info, progress=_on_progress)
        except Exception as exc:
            log.exception("in-place update failed")

            async def _fail():
                self._progress.visible = False
                self._status.value = (
                    f"Update failed: {exc}. Use the browser download instead."
                )
                self._status.color = ft.Colors.ORANGE
                self._actions.controls = self._action_buttons(info.get("url", ""))
                self.app.page.update()

            self.app.page.run_task(_fail)
            return

        async def _apply():
            self._progress.value = 1.0
            self._status.value = "Update verified. Restarting riplex\u2026"
            self._status.color = ft.Colors.GREEN
            self.app.page.update()

        self.app.page.run_task(_apply)
        # Swap the exe and relaunch; this terminates the current process.
        updater.apply_update_and_relaunch(staged)

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
