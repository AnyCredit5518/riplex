"""Organize preview screen - dry-run plan and execute."""

import asyncio
import threading
from pathlib import Path

import flet as ft

from riplex.config import get_api_key, get_output_root
from riplex.matcher import collect_disc_targets, match_discs
from riplex.metadata.sources.tmdb import TmdbProvider
from riplex.metadata.planner import _plan_movie, _plan_show
from riplex.models import PlannedMovie, SearchRequest
from riplex.organizer import build_organize_plan, execute_plan
from riplex.snapshot import save_organized_marker


class OrganizePreviewScreen:
    def __init__(self, app):
        self.app = app
        self.organize_plan = None
        self.planned = None

    def build(self) -> ft.Control:
        # Check for pre-built plan (re-render after background work)
        cached_plan = self.app.state.pop("_organize_plan", None)
        if cached_plan is not None:
            self.organize_plan, self.planned = cached_plan
            return self._build_preview_view()

        plan_error = self.app.state.pop("_organize_plan_error", None)
        if plan_error:
            return self._build_error_view(plan_error)

        # Loading state
        content = ft.Column(
            [
                ft.Text("Organize Preview", size=24, weight=ft.FontWeight.BOLD),
                ft.Divider(height=20),
                ft.Row([
                    ft.ProgressRing(width=30, height=30),
                    ft.Text("Building organize plan...", size=14),
                ], spacing=10),
                ft.Container(expand=True),
                ft.TextButton("Back", on_click=lambda _: self.app.navigate("release")),
            ],
            spacing=10,
            expand=True,
        )

        threading.Thread(target=self._build_plan, daemon=True).start()
        return content

    def _build_plan(self):
        """Build the organize plan in a background thread."""
        try:
            tmdb_match = self.app.state["tmdb_match"]
            scanned = self.app.state["scanned"]
            dvdcompare_discs = self.app.state.get("dvdcompare_discs", [])

            api_key = get_api_key()

            async def _do_plan():
                provider = TmdbProvider(api_key)
                try:
                    request = SearchRequest(
                        title=tmdb_match.title,
                        year=tmdb_match.year,
                        media_type=tmdb_match.media_type,
                    )
                    if tmdb_match.media_type == "movie":
                        planned = await _plan_movie(tmdb_match, provider, request)
                    else:
                        planned = await _plan_show(tmdb_match, provider, request)
                    return planned
                finally:
                    await provider.close()

            planned = asyncio.run(_do_plan())

            # Match scanned files against planned content
            result = match_discs(scanned, dvdcompare_discs, planned)

            # Build file maps
            file_map = {f.name: f.path for d in scanned for f in d.files}
            scanned_map = {f.name: f for d in scanned for f in d.files}
            targets = collect_disc_targets(dvdcompare_discs, planned) if dvdcompare_discs else None

            output_root = Path(get_output_root())
            org_plan = build_organize_plan(
                result, planned, output_root, file_map,
                scanned_files=scanned_map, disc_targets=targets,
            )

            self.app.state["_organize_plan"] = (org_plan, planned)

        except Exception as exc:
            self.app.state["_organize_plan_error"] = str(exc)

        async def _nav():
            self.app.navigate("organize_preview")

        self.app.page.run_task(_nav)

    def _build_preview_view(self) -> ft.Control:
        """Show the dry-run plan."""
        plan = self.organize_plan
        move_count = len(plan.moves) + sum(len(s.chapter_destinations) for s in plan.splits)
        split_count = len(plan.splits)
        unmatched_count = len(plan.unmatched)
        missing_count = len(plan.missing)

        # Summary
        summary_parts = [f"{move_count} file{'s' if move_count != 1 else ''} to organize"]
        if split_count:
            summary_parts.append(f"{split_count} split{'s' if split_count != 1 else ''}")
        if unmatched_count:
            summary_parts.append(f"{unmatched_count} unmatched")
        if missing_count:
            summary_parts.append(f"{missing_count} missing")
        summary = ", ".join(summary_parts)

        # Move rows
        move_rows = []
        for move in plan.moves:
            src_name = Path(move.source).name
            dest_name = Path(move.destination).name
            dest_folder = Path(move.destination).parent.name
            conf_color = {
                "high": ft.Colors.GREEN,
                "medium": ft.Colors.YELLOW,
                "low": ft.Colors.ORANGE,
            }.get(move.confidence, ft.Colors.GREY)
            move_rows.append(
                ft.Row([
                    ft.Icon(ft.Icons.CHECK_CIRCLE, color=conf_color, size=16),
                    ft.Text(f"{src_name}", size=12, width=250, no_wrap=True),
                    ft.Icon(ft.Icons.ARROW_FORWARD, size=14, color=ft.Colors.GREY_500),
                    ft.Text(f"{dest_folder}/{dest_name}", size=12, expand=True, no_wrap=True),
                ], spacing=6)
            )

        # Split rows
        for split in plan.splits:
            src_name = Path(split.source).name
            dest_count = len(split.chapter_destinations)
            move_rows.append(
                ft.Row([
                    ft.Icon(ft.Icons.CONTENT_CUT, color=ft.Colors.BLUE, size=16),
                    ft.Text(f"{src_name}", size=12, width=250, no_wrap=True),
                    ft.Icon(ft.Icons.ARROW_FORWARD, size=14, color=ft.Colors.GREY_500),
                    ft.Text(f"Split into {dest_count} files", size=12, expand=True),
                ], spacing=6)
            )

        # Unmatched rows
        unmatched_rows = []
        for f in plan.unmatched:
            dur_m = f.duration_seconds // 60
            dur_s = f.duration_seconds % 60
            unmatched_rows.append(
                ft.Row([
                    ft.Icon(ft.Icons.CANCEL, color=ft.Colors.RED_300, size=16),
                    ft.Text(f"{f.name}  ({dur_m}:{dur_s:02d})", size=12),
                ], spacing=6)
            )

        # Missing rows
        missing_rows = []
        for label in plan.missing:
            missing_rows.append(
                ft.Row([
                    ft.Icon(ft.Icons.WARNING, color=ft.Colors.ORANGE, size=16),
                    ft.Text(label, size=12),
                ], spacing=6)
            )

        sections = [
            ft.Text("Organize Preview", size=24, weight=ft.FontWeight.BOLD),
            ft.Text(
                "Review the planned file moves below. Click Organize to execute, "
                "or go back to adjust your selection.",
                size=13,
                color=ft.Colors.GREY_500,
            ),
            ft.Divider(height=20),
            ft.Text(summary, size=14, weight=ft.FontWeight.BOLD),
        ]

        if move_rows:
            sections.append(ft.Text("Matched files:", size=13, weight=ft.FontWeight.BOLD))
            sections.append(ft.Column(move_rows, spacing=2, scroll=ft.ScrollMode.AUTO))

        if unmatched_rows:
            sections.append(ft.Container(height=8))
            sections.append(ft.Text("Unmatched files (will be skipped):", size=13, weight=ft.FontWeight.BOLD))
            sections.append(ft.Column(unmatched_rows, spacing=2))

        if missing_rows:
            sections.append(ft.Container(height=8))
            sections.append(ft.Text("Missing (expected but no file found):", size=13, weight=ft.FontWeight.BOLD))
            sections.append(ft.Column(missing_rows, spacing=2))

        sections.append(ft.Container(expand=True))

        # Buttons
        self.organize_btn = ft.ElevatedButton(
            "Organize",
            icon=ft.Icons.DRIVE_FILE_MOVE,
            on_click=self._execute,
            disabled=move_count == 0,
            style=ft.ButtonStyle(padding=ft.padding.symmetric(horizontal=30, vertical=15)),
        )
        sections.append(
            ft.Row([
                ft.TextButton("Back", on_click=lambda _: self.app.navigate("release")),
                self.organize_btn,
            ])
        )

        return ft.Column(
            sections,
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def _build_error_view(self, error: str) -> ft.Control:
        """Show plan build error."""
        return ft.Column(
            [
                ft.Text("Organize Preview", size=24, weight=ft.FontWeight.BOLD),
                ft.Divider(height=20),
                ft.Text(f"Failed to build plan: {error}", size=14, color=ft.Colors.ORANGE),
                ft.Container(expand=True),
                ft.TextButton("Back", on_click=lambda _: self.app.navigate("release")),
            ],
            spacing=10,
            expand=True,
        )

    def _execute(self, e):
        """Execute the organize plan."""
        self.organize_btn.disabled = True
        self.organize_btn.text = "Organizing..."
        self.organize_btn.update()

        threading.Thread(target=self._do_execute, daemon=True).start()

    def _do_execute(self):
        """Run execute_plan in background thread."""
        try:
            actions = execute_plan(self.organize_plan, dry_run=False)
            self.app.state["organize_plan"] = self.organize_plan
            self.app.state["organize_results"] = actions
            self.app.state["_organize_planned"] = self.planned

            # Write organized marker to source folder
            source_folder = self.app.state.get("source_folder")
            if source_folder:
                title = self.app.state.get("title", "")
                move_count = len(self.organize_plan.moves) + sum(
                    len(s.chapter_destinations) for s in self.organize_plan.splits
                )
                save_organized_marker(
                    source_folder,
                    title=title,
                    file_count=move_count,
                    output_root=str(get_output_root()),
                )
        except Exception as exc:
            self.app.state["organize_results"] = [f"Error: {exc}"]
            self.app.state["organize_plan"] = self.organize_plan
            self.app.state["_organize_planned"] = self.planned

        async def _nav():
            self.app.navigate("organize_done")

        self.app.page.run_task(_nav)
