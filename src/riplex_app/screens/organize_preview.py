"""Organize preview screen - dry-run plan and execute."""

import asyncio
import logging
import threading
from pathlib import Path

import flet as ft

from riplex.config import get_api_key, get_output_root
from riplex.matcher import collect_disc_targets, match_discs
from riplex.metadata.sources.tmdb import TmdbProvider
from riplex.metadata.planner import _plan_movie, _plan_show
from riplex.models import PlannedMovie, SearchRequest
from riplex.organize_by_group import apply_group_overrides, build_multi_group_plan
from riplex.organizer import build_organize_plan, execute_plan
from riplex.snapshot import save_from_scanned, save_organized_marker

log = logging.getLogger(__name__)


def _fmt_duration(seconds: int) -> str:
    """Format seconds as ``m:ss`` (or ``h:mm:ss`` for hour-plus runtimes)."""
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class OrganizePreviewScreen:
    def __init__(self, app):
        self.app = app
        self.organize_plan = None
        self.planned = None
        self._progress_text: ft.Text | None = None

    def _set_progress(self, msg: str) -> None:
        """Thread-safe update of the loading status line."""
        log.info("organize progress: %s", msg)
        text = self._progress_text
        if text is None:
            return
        try:
            text.value = msg
            text.update()
        except Exception:
            # Page may have navigated away; ignore.
            pass

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
        self._progress_text = ft.Text("Starting...", size=14)
        content = ft.Column(
            [
                ft.Text("Organize Preview", size=24, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "Building the organize plan. This involves TMDb episode "
                    "lookups, matching disc files to titles, and computing "
                    "target paths.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                ft.Divider(height=20),
                ft.Row([
                    ft.ProgressRing(width=30, height=30),
                    self._progress_text,
                ], spacing=10),
                ft.Container(expand=True),
                ft.Row([
                    ft.TextButton("Back", on_click=lambda _: self.app.navigate("release")),
                ]),
            ],
            spacing=10,
            expand=True,
        )

        threading.Thread(target=self._build_plan, daemon=True).start()
        return content

    def _build_plan(self):
        """Build the organize plan in a background thread.

        Uses the pass-3 per-group router when ``state['disc_groups']``
        is populated (multi-work releases, multi-film discs); falls
        back to the legacy single-plan path otherwise (single-work
        releases, organize-existing-folder without dvdcompare data)."""
        try:
            tmdb_match = self.app.state["tmdb_match"]
            scanned = self.app.state["scanned"]
            dvdcompare_discs = self.app.state.get("dvdcompare_discs", [])
            disc_groups = self.app.state.get("disc_groups") or []
            overrides = self.app.state.get("group_tmdb_overrides") or {}

            api_key = get_api_key()
            output_root = Path(get_output_root())

            use_group_routing = bool(disc_groups)
            if use_group_routing:
                org_plan, planned = self._build_group_plan(
                    scanned, dvdcompare_discs, disc_groups, overrides,
                    api_key, output_root,
                )
            else:
                org_plan, planned = self._build_single_plan(
                    scanned, dvdcompare_discs, tmdb_match, api_key, output_root,
                )

            # Save organize snapshot (like the CLI does)
            source_folder = self.app.state.get("source_folder")
            if source_folder:
                source_path = Path(source_folder)
                snapshot_out = source_path / f"{source_path.name}.snapshot.json"
                if not snapshot_out.exists():
                    self._set_progress("Saving snapshot...")
                    try:
                        save_from_scanned(source_path, scanned, snapshot_out)
                        log.info("Organize snapshot saved: %s", snapshot_out)
                    except Exception as snap_exc:
                        log.warning("Failed to save organize snapshot: %s", snap_exc)

            self._set_progress("Done. Rendering preview...")
            self.app.state["_organize_plan"] = (org_plan, planned)

        except Exception as exc:
            log.exception("Organize plan build failed: %s", exc)
            self.app.state["_organize_plan_error"] = str(exc)

        async def _nav():
            self.app.navigate("organize_preview")

        self.app.page.run_task(_nav)

    def _build_single_plan(
        self, scanned, dvdcompare_discs, tmdb_match, api_key, output_root,
    ):
        """Legacy single-plan path: one TMDb match covers the whole release."""
        async def _do_plan():
            provider = TmdbProvider(api_key)
            try:
                request = SearchRequest(
                    title=tmdb_match.title,
                    year=tmdb_match.year,
                    season_number=self.app.state.get("season_number"),
                    media_type=tmdb_match.media_type,
                )
                if tmdb_match.media_type == "movie":
                    planned = await _plan_movie(tmdb_match, provider, request)
                else:
                    planned = await _plan_show(tmdb_match, provider, request)
                return planned
            finally:
                await provider.close()

        kind = "movie" if tmdb_match.media_type == "movie" else "show"
        self._set_progress(f"Fetching TMDb {kind} details for \"{tmdb_match.title}\"...")
        planned = asyncio.run(_do_plan())

        n_files = sum(len(d.files) for d in scanned)
        self._set_progress(
            f"Matching {n_files} disc file(s) against "
            f"{len(dvdcompare_discs) or 0} dvdcompare disc(s)..."
        )
        result = match_discs(scanned, dvdcompare_discs, planned)

        self._set_progress("Building target paths...")
        # Key by absolute path, not basename: makemkv can produce files
        # with identical basenames across sibling disc folders.
        file_map = {f.path: f.path for d in scanned for f in d.files}
        scanned_map = {f.path: f for d in scanned for f in d.files}
        targets = collect_disc_targets(dvdcompare_discs, planned) if dvdcompare_discs else None

        org_plan = build_organize_plan(
            result, planned, output_root,
            scanned_files_by_name=file_map,
            scanned_files=scanned_map,
            disc_targets=targets,
        )
        return org_plan, planned

    def _build_group_plan(
        self, scanned, dvdcompare_discs, disc_groups, overrides,
        api_key, output_root,
    ):
        """Group-aware path: each DiscGroup / FilmSlot organizes into its
        own Plex target. The overrides dict comes straight from the disc
        overview screen and gets layered on before routing."""
        apply_group_overrides(disc_groups, overrides)
        self._set_progress(
            f"Planning {len(disc_groups)} group(s) against TMDb..."
        )

        async def _do_plan():
            provider = TmdbProvider(api_key)
            try:
                request = SearchRequest(
                    title="",
                    year=None,
                    season_number=self.app.state.get("season_number"),
                    media_type="auto",
                )
                return await build_multi_group_plan(
                    scanned, dvdcompare_discs, disc_groups, provider,
                    output_root,
                    request_defaults=request,
                    progress=self._set_progress,
                )
            finally:
                await provider.close()

        org_plan, group_plans = asyncio.run(_do_plan())

        # Log every group's outcome so misses are visible in the log.
        for gp in group_plans:
            n_moves = len(gp.plan.moves)
            n_unmatched = len(gp.plan.unmatched)
            n_missing = len(gp.plan.missing)
            if gp.skipped_reason:
                log.info("Organize group %s (%s): skipped — %s",
                         gp.group_id, gp.label, gp.skipped_reason)
            else:
                log.info("Organize group %s (%s): %d move(s), %d unmatched, %d missing",
                         gp.group_id, gp.label, n_moves, n_unmatched, n_missing)

        # Pick a representative planned object for the done-screen
        # display: prefer the first non-None (usually the main group).
        planned = next(
            (gp.planned for gp in group_plans if gp.planned is not None),
            None,
        )
        # Stash the full per-group breakdown for the preview to render
        # provenance chips ("belongs to: Psych 2: Lassie Come Home").
        self.app.state["_organize_group_plans"] = group_plans
        return org_plan, planned

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
            src_path = Path(move.source)
            # Prefix the basename with the disc folder so identical
            # makemkv output names across sibling discs (e.g. every
            # Psych disc yields a C2_t01.mkv) are visually distinct.
            src_parent = src_path.parent.name
            src_name = f"{src_parent}/{src_path.name}" if src_parent else src_path.name
            dest_name = Path(move.destination).name
            dest_folder = Path(move.destination).parent.name
            conf_color = {
                "high": ft.Colors.GREEN,
                "medium": ft.Colors.YELLOW,
                "low": ft.Colors.ORANGE,
            }.get(move.confidence, ft.Colors.GREY)
            # Confidence chip: shows label + delta so the user can spot
            # weak (medium/low) matches before executing.
            delta = getattr(move, "delta_seconds", 0)
            conf_label = (move.confidence or "?").upper()
            if delta:
                conf_text = f"{conf_label} \u00B1{delta}s"
            else:
                conf_text = conf_label
            conf_chip = ft.Container(
                content=ft.Text(conf_text, size=10, color=conf_color, weight=ft.FontWeight.BOLD),
                bgcolor=ft.Colors.with_opacity(0.12, conf_color),
                padding=ft.Padding(left=6, right=6, top=2, bottom=2),
                border_radius=4,
            )
            # Durations make a bad match obvious at a glance: the source
            # file's runtime beside the matched target's expected runtime,
            # highlighted when they diverge by more than a minute.
            file_dur = getattr(move, "file_duration_seconds", 0)
            tgt_dur = getattr(move, "target_runtime_seconds", 0)
            dur_mismatch = tgt_dur > 0 and abs(file_dur - tgt_dur) > 60
            dur_color = ft.Colors.ORANGE if dur_mismatch else ft.Colors.GREY_500
            src_dur_text = _fmt_duration(file_dur) if file_dur else ""
            tgt_dur_text = f"({_fmt_duration(tgt_dur)})" if tgt_dur else ""
            move_rows.append(
                ft.Row([
                    ft.Icon(ft.Icons.CHECK_CIRCLE, color=conf_color, size=16),
                    conf_chip,
                    ft.Text(f"{src_name}", size=12, width=180, no_wrap=True),
                    ft.Text(src_dur_text, size=11, width=54, no_wrap=True, color=dur_color),
                    ft.Icon(ft.Icons.ARROW_FORWARD, size=14, color=ft.Colors.GREY_500),
                    ft.Text(f"{dest_folder}/{dest_name}", size=12, expand=True, no_wrap=True),
                    ft.Text(tgt_dur_text, size=11, no_wrap=True, color=dur_color),
                ], spacing=6)
            )

        # Split rows
        for split in plan.splits:
            split_path = Path(split.source)
            split_parent = split_path.parent.name
            src_name = f"{split_parent}/{split_path.name}" if split_parent else split_path.name
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
            # Prefix with disc folder for the same disambiguation
            # reason as the matched section.
            src_path = Path(f.path) if f.path else Path(f.name)
            src_parent = src_path.parent.name
            display = f"{src_parent}/{f.name}" if src_parent else f.name
            unmatched_rows.append(
                ft.Row([
                    ft.Icon(ft.Icons.CANCEL, color=ft.Colors.RED_300, size=16),
                    ft.Text(f"{display}  ({dur_m}:{dur_s:02d})", size=12),
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
            style=ft.ButtonStyle(padding=ft.Padding(left=30, top=15, right=30, bottom=15)),
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
                ft.Row([
                    ft.TextButton("Back", on_click=lambda _: self.app.navigate("release")),
                ]),
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
