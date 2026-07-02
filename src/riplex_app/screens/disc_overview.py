"""Disc overview screen - shows all discs in a release with rip status."""

import logging
import threading
from pathlib import Path

import flet as ft

from riplex.disc.analysis import group_release_discs
from riplex.disc.provider import disc_content_summary
from riplex.manifest import build_rip_path, find_ripped_discs

log = logging.getLogger(__name__)


class DiscOverviewScreen:
    """Shows all discs in the selected dvdcompare release.

    Displays which disc is currently inserted, which have been previously
    ripped (via manifest detection), and lets the user select which discs
    to rip in this session.
    """

    def __init__(self, app):
        self.app = app
        self.checkboxes: list[ft.Checkbox] = []
        # group.id -> (toggle_button, its list of toggleable checkboxes)
        self._group_toggle_buttons: dict[str, tuple[ft.TextButton, list[ft.Checkbox]]] = {}

    def build(self) -> ft.Control:
        tmdb_match = self.app.state["tmdb_match"]
        dvdcompare_discs = self.app.state.get("dvdcompare_discs", [])
        disc_info = self.app.state.get("disc_info")
        release = self.app.state.get("release")

        canonical = tmdb_match.title if tmdb_match else ""
        year = tmdb_match.year or 0 if tmdb_match else 0
        release_name = release.name if release else ""

        if not dvdcompare_discs:
            return self._build_empty_state(match_label=self._match_label(canonical, year))

        # Detect currently inserted disc
        from riplex.disc.provider import detect_disc_number
        inserted_disc = None
        if disc_info and dvdcompare_discs:
            inserted_disc = detect_disc_number(disc_info, dvdcompare_discs)
        self.app.state["_inserted_disc"] = inserted_disc

        # Find previously ripped discs from manifests
        rip_root = build_rip_path(canonical, year)
        ripped_discs = find_ripped_discs(rip_root)
        self.app.state["ripped_discs"] = ripped_discs

        log.info("Disc overview: %d discs, inserted=%s, ripped=%s",
                 len(dvdcompare_discs), inserted_disc, ripped_discs)

        # Split the release into organize-target groups. Auto-assigns the
        # current tmdb_match to the group whose kind matches its media_type
        # (movie -> film group; tv -> main group). Groups whose target is
        # still None will prompt the user to assign one via the metadata
        # screen — per-group picks are persisted in group_tmdb_overrides so
        # they survive re-render.
        disc_groups = group_release_discs(dvdcompare_discs, tmdb_match)
        overrides = self.app.state.get("group_tmdb_overrides", {})
        for g in disc_groups:
            if g.id in overrides:
                g.tmdb_match = overrides[g.id]
        self.app.state["disc_groups"] = disc_groups
        log.info("Disc overview: %d group(s): %s",
                 len(disc_groups),
                 [(g.id, g.kind, g.disc_numbers, bool(g.tmdb_match)) for g in disc_groups])

        discs_by_number = {d.number: d for d in dvdcompare_discs}
        self.checkboxes = []
        self._group_toggle_buttons = {}
        group_sections: list[ft.Control] = []

        for group in disc_groups:
            group_sections.append(
                self._build_group_section(
                    group,
                    discs_by_number,
                    ripped_discs,
                    inserted_disc,
                )
            )

        # Summary
        selected_count = sum(1 for cb in self.checkboxes if cb.value)
        self.summary_text = ft.Text(
            f"{selected_count} disc(s) selected for ripping",
            size=14,
            weight=ft.FontWeight.BOLD,
        )

        # Wire checkboxes
        for cb in self.checkboxes:
            cb.on_change = self._update_summary

        match_label = self._match_label(canonical, year)

        # Resume info
        resume_info = ft.Container()
        if ripped_discs:
            ripped_list = ", ".join(str(n) for n in sorted(ripped_discs))
            resume_info = ft.Container(
                ft.Row([
                    ft.Icon(ft.Icons.INFO, color=ft.Colors.BLUE_400, size=16),
                    ft.Text(
                        f"Previously ripped: Disc {ripped_list}. "
                        "These are already done and won't be re-ripped.",
                        size=12, color=ft.Colors.BLUE_400,
                    ),
                ], spacing=8),
                padding=ft.Padding(top=8, bottom=8),
            )

        back_btn = ft.TextButton("Back", on_click=lambda _: self.app.navigate("release"))
        start_btn = ft.ElevatedButton(
            "Start Ripping",
            icon=ft.Icons.PLAY_ARROW,
            on_click=self._start,
            style=ft.ButtonStyle(
                padding=ft.Padding(left=30, top=15, right=30, bottom=15),
                bgcolor=ft.Colors.GREEN_700,
            ),
        )

        return ft.Column(
            [
                ft.Text("Disc Overview", size=24, weight=ft.FontWeight.BOLD),
                ft.Text(match_label, size=14, color=ft.Colors.GREY_400),
                ft.Text(
                    f"Release: {release_name}" if release_name else "",
                    size=12, color=ft.Colors.GREY_500,
                ),
                ft.Text(
                    "Select which discs to rip. The currently inserted disc will "
                    "be ripped first, then you'll be prompted to insert each "
                    "remaining disc.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                ft.Divider(height=20),
                resume_info,
                ft.Column(group_sections, spacing=12, scroll=ft.ScrollMode.AUTO,
                          expand=True),
                ft.Divider(height=10),
                self.summary_text,
                ft.Container(height=10),
                ft.Row([back_btn, start_btn]),
            ],
            spacing=10,
            expand=True,
        )

    def _match_label(self, canonical: str, year: int) -> str:
        year_str = f" ({year})" if year else ""
        return f"{canonical}{year_str}"

    def _build_group_section(
        self,
        group,
        discs_by_number: dict,
        ripped_discs: set,
        inserted_disc: int | None,
    ) -> ft.Control:
        """Render one DiscGroup as a bordered card with header + disc rows.

        Header shows the group's TMDb match (or a "no match set" prompt), a
        Select all / Deselect all toggle for this group's discs, and a
        Change/Assign match button. Rows are the same layout as the
        pre-grouping single flat list, so the visual for a one-group
        release is nearly unchanged.
        """
        match = group.tmdb_match
        if match is not None:
            match_line = ft.Row([
                ft.Icon(ft.Icons.MOVIE if group.kind == "film" else ft.Icons.TV,
                        size=16, color=ft.Colors.GREEN_400),
                ft.Text(self._match_label(match.title, match.year or 0),
                        size=14, weight=ft.FontWeight.BOLD),
                ft.Text(f"[{match.media_type}]", size=12, color=ft.Colors.GREY_400),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)
            header_color = ft.Colors.GREEN_400
            match_btn_label = "Change match…"
            match_btn_icon = ft.Icons.EDIT
        else:
            match_line = ft.Row([
                ft.Icon(ft.Icons.WARNING_AMBER, size=16, color=ft.Colors.AMBER_400),
                ft.Text("No match set — assign a TMDb target for these discs",
                        size=13, color=ft.Colors.AMBER_400,
                        italic=True),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)
            header_color = ft.Colors.AMBER_400
            match_btn_label = "Assign match…"
            match_btn_icon = ft.Icons.ADD

        match_btn = ft.OutlinedButton(
            match_btn_label,
            icon=match_btn_icon,
            on_click=lambda _e, g=group: self._change_match(g),
        )

        # Build disc rows first so we can wire the group's select-all to them.
        group_checkboxes: list[ft.Checkbox] = []
        rows: list[ft.Control] = []
        for disc_num in group.disc_numbers:
            disc = discs_by_number.get(disc_num)
            if disc is None:
                continue
            row, cb = self._build_disc_row(disc, ripped_discs, inserted_disc)
            rows.append(row)
            group_checkboxes.append(cb)

        # A group's select-all only considers enabled (non-RIPPED) checkboxes.
        toggleable = [cb for cb in group_checkboxes if not cb.disabled]
        toggle_btn = ft.TextButton(
            self._select_all_label(toggleable),
            icon=ft.Icons.CHECKLIST,
            on_click=lambda _e, cbs=toggleable, gid=group.id: self._toggle_group(cbs, gid),
        )
        # Remember the button so _toggle_group can flip its label in place.
        self._group_toggle_buttons[group.id] = (toggle_btn, toggleable)

        header = ft.Row(
            [
                ft.Column([
                    ft.Text(group.label, size=13, color=header_color,
                            weight=ft.FontWeight.BOLD),
                    match_line,
                ], spacing=2, expand=True),
                toggle_btn,
                match_btn,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        return ft.Container(
            content=ft.Column(
                [header, ft.Divider(height=8), *rows],
                spacing=6,
            ),
            border=ft.Border.all(1, ft.Colors.GREY_700),
            border_radius=6,
            padding=12,
        )

    def _build_disc_row(
        self,
        disc,
        ripped_discs: set,
        inserted_disc: int | None,
    ):
        """Render a single disc row. Returns (row_control, checkbox)."""
        is_ripped = disc.number in ripped_discs
        is_inserted = disc.number == inserted_disc

        cb = ft.Checkbox(
            value=not is_ripped,
            data=disc.number,
            disabled=is_ripped,
        )
        self.checkboxes.append(cb)

        if is_ripped:
            badge_text, badge_color = "RIPPED", ft.Colors.GREEN_700
        elif is_inserted:
            badge_text, badge_color = "INSERTED", ft.Colors.BLUE_700
        else:
            badge_text, badge_color = "PENDING", ft.Colors.GREY_700
        badge = ft.Container(
            ft.Text(badge_text, size=10, color=ft.Colors.WHITE,
                    weight=ft.FontWeight.BOLD),
            bgcolor=badge_color,
            border_radius=4,
            padding=ft.Padding(left=6, top=2, right=6, bottom=2),
        )

        fmt = getattr(disc, "disc_format", None) or ""
        fmt_text = f" ({fmt})" if fmt else ""
        summary = disc_content_summary(disc)

        row = ft.Row(
            [
                cb,
                ft.Text(f"Disc {disc.number}{fmt_text}", width=120, size=13,
                        weight=ft.FontWeight.BOLD),
                badge,
                ft.Text(summary, size=12, color=ft.Colors.GREY_300, expand=True),
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        return row, cb

    @staticmethod
    def _select_all_label(cbs: list[ft.Checkbox]) -> str:
        if cbs and all(cb.value for cb in cbs):
            return f"Deselect all ({len(cbs)})"
        return f"Select all ({len(cbs)})"

    def _toggle_group(self, cbs: list[ft.Checkbox], group_id: str) -> None:
        """Flip every toggleable checkbox in a group. If any are unchecked,
        select all; otherwise deselect all."""
        if not cbs:
            return
        target = not all(cb.value for cb in cbs)
        for cb in cbs:
            cb.value = target
        btn, _ = self._group_toggle_buttons.get(group_id, (None, None))
        if btn is not None:
            btn.text = self._select_all_label(cbs)
        self._update_summary(None)

    def _change_match(self, group) -> None:
        """Navigate to the metadata screen in scoped mode to assign a TMDb
        match for this group only. On return, the pick lands in
        state['group_tmdb_overrides'][group.id] and disc_overview re-renders
        with the new match displayed."""
        current_title = self.app.state.get("title", "") or ""
        self.app.state["_group_match_target_id"] = group.id
        self.app.state["_group_match_saved_title"] = current_title
        # Seed the search field with the best hint we have for this group.
        seed = group.default_search_title or current_title or group.label
        self.app.state["title"] = seed
        # Force the metadata screen to run a fresh search.
        self.app.state.pop("_tmdb_results", None)
        self.app.state.pop("_tmdb_error", None)
        log.info("Change match for group %s (seed='%s')", group.id, seed)
        self.app.navigate("metadata")

    def _build_empty_state(self, *, match_label: str) -> ft.Control:
        """Show a recoverable state when orchestrate has no disc structure."""
        return ft.Column(
            [
                ft.Text("Disc Overview", size=24, weight=ft.FontWeight.BOLD),
                ft.Text(match_label, size=14, color=ft.Colors.GREY_400),
                ft.Text(
                    "No usable dvdcompare disc structure is selected for this title. "
                    "Pick a different dvdcompare result, or continue with duration-only "
                    "single-disc selection.",
                    size=13,
                    color=ft.Colors.ORANGE,
                ),
                ft.Container(expand=True),
                ft.Row([
                    ft.TextButton("Back", on_click=lambda _: self.app.navigate("release")),
                    ft.ElevatedButton(
                        "Continue without",
                        icon=ft.Icons.ARROW_FORWARD,
                        on_click=self._continue_without_dvdcompare,
                    ),
                ]),
            ],
            spacing=10,
            expand=True,
        )

    def _continue_without_dvdcompare(self, _e):
        """Proceed with a single-disc duration-only rip when no release data exists."""
        self.app.state["dvdcompare_discs"] = []
        self.app.state["_orchestrate_disc_number"] = 1
        self.app.state["disc_queue"] = [1]
        self.app.state["current_disc_idx"] = 0
        self.app.state["all_rip_results"] = {}
        self.app.navigate("selection")

    def _update_summary(self, e):
        """Update summary when checkboxes change."""
        selected_count = sum(1 for cb in self.checkboxes if cb.value)
        self.summary_text.value = f"{selected_count} disc(s) selected for ripping"
        self.app.page.update()

    def _start(self, e):
        """Build disc queue and start the orchestrate loop."""
        selected_nums = [cb.data for cb in self.checkboxes if cb.value]
        if not selected_nums:
            return

        # Order: inserted disc first, then remaining in number order
        inserted = self.app.state.get("_inserted_disc")
        if inserted and inserted in selected_nums:
            ordered = [inserted] + sorted(n for n in selected_nums if n != inserted)
        else:
            ordered = sorted(selected_nums)

        self.app.state["disc_queue"] = ordered
        self.app.state["current_disc_idx"] = 0
        self.app.state["all_rip_results"] = {}

        log.info("Orchestrate: disc_queue=%s", ordered)

        # Start with the first disc
        self._begin_disc(ordered[0])

    def _begin_disc(self, disc_number: int):
        """Navigate to selection for the given disc number."""
        inserted = self.app.state.get("_inserted_disc")

        if disc_number == inserted:
            # Already have disc info, go straight to selection
            self.app.state["_orchestrate_disc_number"] = disc_number
            self.app.navigate("selection")
        else:
            # Need to swap disc first
            self.app.state["_orchestrate_disc_number"] = disc_number
            self.app.navigate("disc_swap")
