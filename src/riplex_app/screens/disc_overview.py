"""Disc overview screen - shows all discs in a release with rip status.

Handles the release-groups UX: splits a release into per-work DiscGroups,
renders one bordered card per group with three-state match indicators
(unassigned / auto-filled / user-confirmed), eager-fires TMDb best-guess
lookups for unfilled slots on screen entry, and guards Start Ripping until
every selected disc's group is complete.
"""

import asyncio
import logging
import threading

import flet as ft

from riplex.config import get_api_key
from riplex.disc.analysis import build_season_labels, group_release_discs
from riplex.disc.provider import DiscProvider, disc_content_summary, strip_dvdcompare_annotations
from riplex.manifest import (
    SessionWork,
    build_rip_path,
    find_existing_session,
    find_ripped_discs,
    write_session_marker,
)
from riplex.normalize import sanitize_filename
from riplex.metadata.autosearch import best_guess, strip_boxset_suffix
from riplex.metadata.sources.tmdb import TmdbProvider

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
        self._start_btn: ft.ElevatedButton | None = None
        self._blocker_text: ft.Text | None = None

    # ------------------------------------------------------------------
    # build()
    # ------------------------------------------------------------------

    def build(self) -> ft.Control:
        tmdb_match = self.app.state["tmdb_match"]
        dvdcompare_discs = self.app.state.get("dvdcompare_discs", [])
        disc_info = self.app.state.get("disc_info")
        release = self.app.state.get("release")
        film = self.app.state.get("_dvdcompare_film")

        canonical = tmdb_match.title if tmdb_match else ""
        year = tmdb_match.year or 0 if tmdb_match else 0
        release_name = release.name if release else ""
        film_title = film.title if film else ""

        if not dvdcompare_discs:
            return self._build_empty_state(match_label=self._match_label(canonical, year))

        # Currently-loaded disc: auto-detected from disc_info if possible,
        # overridable via the dropdown at the top of the screen. We can't
        # be 100% confident in detection (season TV boxsets have many
        # discs with near-identical runtimes) so the user always has the
        # last word. The manual override is scoped to the current
        # ``disc_info`` — reading a fresh disc clears it.
        from riplex.disc.provider import detect_disc_number
        disc_info_id = id(disc_info) if disc_info is not None else None
        if self.app.state.get("_inserted_disc_di_id") != disc_info_id:
            self.app.state.pop("_inserted_disc_manual", None)
            self.app.state["_inserted_disc_di_id"] = disc_info_id

        auto_detected = None
        if disc_info and dvdcompare_discs:
            auto_detected = detect_disc_number(disc_info, dvdcompare_discs)
        self.app.state["_auto_detected_disc"] = auto_detected

        manual = self.app.state.get("_inserted_disc_manual")
        if manual is not None:
            inserted_disc = manual
        elif auto_detected is not None:
            inserted_disc = auto_detected
        else:
            inserted_disc = dvdcompare_discs[0].number
        self.app.state["_inserted_disc"] = inserted_disc

        # Find previously ripped discs from manifests. Aggregates across
        # sibling work-folders when a session marker exists so resume of
        # a multi-work release shows every completed disc regardless of
        # which work-folder it's in.
        season_number = self.app.state.get("season_number")
        top_season = season_number if tmdb_match and tmdb_match.media_type == "tv" else None
        rip_root = build_rip_path(canonical, year, season_number=top_season)
        existing = find_existing_session(canonical)
        if existing and existing.all_ripped_discs:
            ripped_discs = set(existing.all_ripped_discs)
        else:
            ripped_discs = find_ripped_discs(rip_root)
        self.app.state["ripped_discs"] = ripped_discs

        log.info("Disc overview: %d discs, inserted=%s, ripped=%s",
                 len(dvdcompare_discs), inserted_disc, ripped_discs)

        # Split the release into organize-target groups. Auto-assigns the
        # current tmdb_match to the group whose kind matches its media_type;
        # per-group and per-film overrides are then layered on top.
        disc_groups = group_release_discs(dvdcompare_discs, tmdb_match)
        self._apply_overrides(disc_groups)
        self.app.state["disc_groups"] = disc_groups
        log.info(
            "Disc overview: %d group(s): %s",
            len(disc_groups),
            [
                (g.id, g.disc_numbers,
                 f"{len(g.films)} film slot(s)" if g.films else "single-work",
                 "complete" if g.is_complete() else "incomplete")
                for g in disc_groups
            ],
        )

        # Kick off eager TMDb auto-fill for any group with unfilled slots
        # that hasn't been attempted yet. Runs in a background thread; the
        # worker writes results into state["group_tmdb_overrides"] and
        # re-navigates so the amber "auto-filled" state is shown.
        self._maybe_autofill(disc_groups, release_name=release_name,
                             film_title=film_title)

        discs_by_number = {d.number: d for d in dvdcompare_discs}
        self.checkboxes = []
        self._group_toggle_buttons = {}
        group_sections: list[ft.Control] = []

        for group in disc_groups:
            group_sections.append(
                self._build_group_section(
                    group, discs_by_number, ripped_discs, inserted_disc,
                )
            )

        selected_count = sum(1 for cb in self.checkboxes if cb.value)
        self.summary_text = ft.Text(
            f"{selected_count} disc(s) selected for ripping",
            size=14,
            weight=ft.FontWeight.BOLD,
        )
        self._blocker_text = ft.Text("", size=12, color=ft.Colors.RED_400, italic=True)

        for cb in self.checkboxes:
            cb.on_change = self._update_summary

        match_label = self._match_label(canonical, year)

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
        self._start_btn = ft.ElevatedButton(
            "Start Ripping",
            icon=ft.Icons.PLAY_ARROW,
            on_click=self._start,
            style=ft.ButtonStyle(
                padding=ft.Padding(left=30, top=15, right=30, bottom=15),
                bgcolor=ft.Colors.GREEN_700,
            ),
        )
        self._refresh_start_guard()

        multigroup_banner = self._build_multigroup_banner(disc_groups)
        loaded_selector = self._build_loaded_disc_selector(
            dvdcompare_discs, inserted_disc, auto_detected,
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
                    "Select which discs to rip. The disc marked below "
                    "will be ripped first, then you'll be prompted to "
                    "insert each remaining disc.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                ft.Divider(height=20),
                loaded_selector,
                multigroup_banner,
                resume_info,
                ft.Column(group_sections, spacing=12, scroll=ft.ScrollMode.AUTO,
                          expand=True),
                ft.Divider(height=10),
                self.summary_text,
                self._blocker_text,
                ft.Container(height=10),
                ft.Row([back_btn, self._start_btn]),
            ],
            spacing=10,
            expand=True,
        )

    # ------------------------------------------------------------------
    # overrides + auto-fill
    # ------------------------------------------------------------------

    def _apply_overrides(self, disc_groups) -> None:
        """Layer per-session overrides on top of the freshly-computed groups.

        Override schema (kept in ``state['group_tmdb_overrides']``)::

            {gid: {
                "match": tmdb | None,
                "source": "user" | "auto" | None,
                "films": {film_idx: {"match": tmdb, "source": "user"|"auto"}},
            }}
        """
        overrides = self.app.state.get("group_tmdb_overrides", {})
        for g in disc_groups:
            entry = overrides.get(g.id)
            if not entry:
                continue
            if entry.get("match") is not None:
                g.tmdb_match = entry["match"]
                g.source = entry.get("source")
            for idx, film_entry in (entry.get("films") or {}).items():
                if 0 <= idx < len(g.films) and film_entry.get("match") is not None:
                    g.films[idx].tmdb_match = film_entry["match"]
                    g.films[idx].source = film_entry.get("source")

    def _maybe_autofill(self, disc_groups, *, release_name: str = "",
                        film_title: str = "") -> None:
        """Start a background auto-fill for any group with unfilled slots
        that hasn't been attempted yet this session."""
        attempted = self.app.state.setdefault("_autofill_attempted", set())
        pending = [g for g in disc_groups if g.id not in attempted and not g.is_complete()]
        if not pending:
            return
        for g in pending:
            attempted.add(g.id)
        log.info("Auto-fill kicking off for %d group(s): %s",
                 len(pending), [g.id for g in pending])
        threading.Thread(
            target=self._autofill_worker,
            args=(pending, release_name, film_title),
            daemon=True,
        ).start()

    def _autofill_worker(self, groups, release_name: str = "",
                         film_title: str = "") -> None:
        """Off-thread TMDb best-guess lookup for every unfilled slot in the
        given groups. Results land in ``state['group_tmdb_overrides']`` with
        ``source='auto'``; a re-navigate then redraws the screen."""
        try:
            api_key = get_api_key()
        except Exception as exc:
            log.warning("Auto-fill skipped: no TMDb API key (%s)", exc)
            return

        overrides = self.app.state.setdefault("group_tmdb_overrides", {})

        async def _do_all():
            provider = TmdbProvider(api_key)
            disc_provider = DiscProvider()
            try:
                for g in groups:
                    log.info("Auto-fill: entering group %s (films=%d "
                             "tmdb_match=%s default_title=%r)",
                             g.id, len(g.films),
                             getattr(g.tmdb_match, "title", None),
                             g.default_search_title)
                    if g.films:
                        for idx, film in enumerate(g.films):
                            if film.tmdb_match is not None:
                                continue
                            query = film.title
                            # When dvdcompare hyperlinked this bonus title
                            # to a distinct film page, hit that fid for the
                            # canonical title — those cross-page links are
                            # curated so they're a stronger signal than the
                            # free-text bonus label.
                            fid = getattr(film, "dvdcompare_fid", None)
                            if fid:
                                try:
                                    linked = await disc_provider.fetch_film_by_id(fid)
                                    if linked and getattr(linked, "title", ""):
                                        # dvdcompare film titles bake in
                                        # format markers like "(TV)" and
                                        # "(Blu-ray)"; strip them before
                                        # searching TMDb — those markers
                                        # never appear in TMDb entries and
                                        # otherwise drive the search to
                                        # zero results.
                                        query = strip_dvdcompare_annotations(
                                            linked.title,
                                        )
                                        log.info(
                                            "Auto-fill: %s films[%d] fid=%s "
                                            "resolved to %r -> query %r (%s)",
                                            g.id, idx, fid, linked.title,
                                            query,
                                            getattr(linked, "year", None),
                                        )
                                except Exception as exc:
                                    log.info(
                                        "Auto-fill: %s films[%d] fid=%s "
                                        "lookup failed (%s); falling back to '%s'",
                                        g.id, idx, fid, exc, film.title,
                                    )
                            got = await best_guess(
                                provider, query, media_type="movie",
                            )
                            if got is None:
                                continue
                            match, _score = got
                            entry = overrides.setdefault(g.id, {})
                            films_map = entry.setdefault("films", {})
                            films_map[idx] = {"match": match, "source": "auto"}
                            log.info("Auto-fill: %s films[%d] '%s' -> '%s (%s)'",
                                     g.id, idx, query,
                                     match.title, match.year)
                    else:
                        if g.tmdb_match is not None:
                            continue
                        # Try the most specific source first, falling back
                        # to the release title (which is what the user just
                        # picked from dvdcompare, e.g. "Psych: The Complete
                        # Series"). Boxset / collection markers are stripped
                        # so the top TMDb hit scores above the fuzzy
                        # threshold.
                        # Fallback chain for the query:
                        #   1. group's default_search_title (empty for
                        #      main groups today)
                        #   2. dvdcompare film title — the parent object
                        #      the user picked, e.g. "Psych: The Complete
                        #      Series". Preferred over state["title"]
                        #      because that field can hold the currently
                        #      inserted disc's volume label ("Psych The
                        #      Movie"), which mismatches a TV-show search.
                        #   3. state["title"] as last resort
                        #   4. dvdcompare release name (edition/format)
                        # strip_boxset_suffix trims "Complete Series",
                        # "Trilogy", etc so TMDb sees a bare title.
                        raw_query = (
                            g.default_search_title
                            or film_title
                            or self.app.state.get("title", "")
                            or release_name
                            or ""
                        )
                        query = strip_boxset_suffix(raw_query)
                        log.info("Auto-fill: %s raw_query=%r stripped=%r "
                                 "(default=%r film=%r state.title=%r release=%r)",
                                 g.id, raw_query, query,
                                 g.default_search_title, film_title,
                                 self.app.state.get("title"), release_name)
                        if not query.strip():
                            log.info("Auto-fill: %s skipped (empty query)", g.id)
                            continue
                        media_type = "auto"
                        got = await best_guess(provider, query, media_type=media_type)
                        if got is None:
                            log.info("Auto-fill: %s no confident guess for %r",
                                     g.id, query)
                            continue
                        match, _score = got
                        entry = overrides.setdefault(g.id, {})
                        entry["match"] = match
                        entry["source"] = "auto"
                        log.info("Auto-fill: %s '%s' -> '%s (%s)'",
                                 g.id, query, match.title, match.year)
            finally:
                await provider.close()

        try:
            asyncio.run(_do_all())
        except Exception as exc:
            log.exception("Auto-fill worker failed: %s", exc)

        async def _nav():
            self.app.navigate("disc_overview")

        try:
            self.app.page.run_task(_nav)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # rendering
    # ------------------------------------------------------------------

    def _match_label(self, canonical: str, year: int) -> str:
        year_str = f" ({year})" if year else ""
        return f"{canonical}{year_str}"

    def _build_loaded_disc_selector(
        self, dvdcompare_discs, inserted_disc: int | None,
        auto_detected: int | None,
    ) -> ft.Control:
        """Dropdown letting the user override which disc is loaded.

        Auto-detection isn't always reliable — TV seasons in particular
        have many discs with near-identical episode runtimes — so users
        need the last word on which disc riplex will rip first.
        """
        options = [
            ft.dropdown.Option(str(d.number), f"Disc {d.number}")
            for d in dvdcompare_discs
        ]
        if auto_detected is not None:
            hint = f"Auto-detected: Disc {auto_detected}"
            if inserted_disc != auto_detected:
                hint += "  (overridden)"
            hint_color = ft.Colors.GREY_500
        else:
            hint = "Auto-detection inconclusive — please confirm."
            hint_color = ft.Colors.AMBER_300

        return ft.Container(
            content=ft.Row(
                [
                    ft.Text("Currently loaded:", size=13,
                            color=ft.Colors.GREY_300),
                    ft.Dropdown(
                        value=str(inserted_disc) if inserted_disc else None,
                        options=options,
                        on_select=self._on_loaded_disc_changed,
                        width=160,
                        dense=True,
                    ),
                    ft.Text(hint, size=11, color=hint_color, italic=True),
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding(top=4, bottom=4, left=0, right=0),
        )

    def _on_loaded_disc_changed(self, e) -> None:
        val = e.control.value
        try:
            self.app.state["_inserted_disc_manual"] = int(val) if val else None
        except (TypeError, ValueError):
            self.app.state["_inserted_disc_manual"] = None
        # Re-render so the INSERTED badge tracks the new selection.
        self.app.navigate("disc_overview")

    def _build_multigroup_banner(self, disc_groups) -> ft.Control:
        """Info card explaining the multi-group / multi-film workflow.

        Only shown when the release splits into more than one group, or
        when any single group holds multiple per-film slots — that's the
        case where the auto-fill / confirm workflow is non-obvious."""
        multi_group = len(disc_groups) > 1
        multi_film = any(len(g.films) > 1 for g in disc_groups)
        if not (multi_group or multi_film):
            return ft.Container()

        if multi_group and multi_film:
            headline = "This release contains multiple works and multi-film discs"
            body = (
                "We split the discs into groups and tried to auto-fill a "
                "TMDb match for each work / bonus film. Confirm the amber "
                "auto-fills or use Change… to correct them; assign any "
                "empty slots before ripping."
            )
        elif multi_group:
            headline = "This release contains multiple works"
            body = (
                "We split the discs into groups and tried to auto-fill a "
                "TMDb match for each. Confirm the amber auto-fills or use "
                "Change… to correct them; assign any empty slots before "
                "ripping."
            )
        else:
            headline = "One of these discs contains multiple feature films"
            body = (
                "We tried to auto-fill a TMDb match for each film. Confirm "
                "the amber auto-fills or use Change… to correct them; "
                "assign any empty slots before ripping."
            )

        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.INFO_OUTLINE, color=ft.Colors.BLUE_300, size=20),
                    ft.Column(
                        [
                            ft.Text(
                                headline,
                                size=13,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.BLUE_300,
                            ),
                            ft.Text(body, size=12, color=ft.Colors.GREY_300),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            padding=12,
            border=ft.Border.all(1, ft.Colors.BLUE_800),
            border_radius=6,
            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.BLUE_400),
        )

    def _build_group_section(
        self, group, discs_by_number, ripped_discs, inserted_disc,
    ) -> ft.Control:
        """Render one DiscGroup as a bordered card. Film groups with
        per-film slots list each film separately; main groups (and film
        groups without slots) show a single group-level match line."""
        border_color = self._group_border_color(group)

        header_children: list[ft.Control] = [
            ft.Text(group.label, size=13, weight=ft.FontWeight.BOLD,
                    color=border_color),
        ]

        if group.films:
            for idx, film in enumerate(group.films):
                header_children.append(self._build_film_row(group, idx, film))
        else:
            header_children.append(self._build_group_match_row(group))

        group_checkboxes: list[ft.Checkbox] = []
        rows: list[ft.Control] = []
        # Compute per-disc season labels ("Season 1, Disc 2") once per
        # group so the disc rows can prefix their summaries with the
        # season info from dvdcompare placeholders.
        group_discs = [
            discs_by_number[n] for n in group.disc_numbers
            if n in discs_by_number
        ]
        season_labels = build_season_labels(
            group_discs,
            film_title=self.app.state.get("dvdcompare_film_title"),
        )
        for disc_num in group.disc_numbers:
            disc = discs_by_number.get(disc_num)
            if disc is None:
                continue
            row, cb = self._build_disc_row(
                disc, ripped_discs, inserted_disc,
                season_label=season_labels.get(disc.number, ""),
            )
            rows.append(row)
            group_checkboxes.append(cb)

        toggleable = [cb for cb in group_checkboxes if not cb.disabled]
        toggle_btn = ft.TextButton(
            self._select_all_label(toggleable),
            icon=ft.Icons.CHECKLIST,
            on_click=lambda _e, cbs=toggleable, gid=group.id: self._toggle_group(cbs, gid),
        )
        self._group_toggle_buttons[group.id] = (toggle_btn, toggleable)

        discs_header = ft.Row(
            [
                ft.Text("Discs", size=12, color=ft.Colors.GREY_500,
                        weight=ft.FontWeight.BOLD, expand=True),
                toggle_btn,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        return ft.Container(
            content=ft.Column(
                [*header_children, ft.Divider(height=12), discs_header, *rows],
                spacing=6,
            ),
            border=ft.Border.all(1, border_color),
            border_radius=6,
            padding=12,
        )

    def _group_border_color(self, group) -> str:
        """Green iff every slot in the group is user-confirmed. Amber if
        any slot is auto-filled or empty."""
        if not group.is_complete():
            return ft.Colors.AMBER_400
        if group.films:
            return (ft.Colors.GREEN_400
                    if all(f.source == "user" for f in group.films)
                    else ft.Colors.AMBER_400)
        return (ft.Colors.GREEN_400 if group.source == "user"
                else ft.Colors.AMBER_400)

    def _build_group_match_row(self, group) -> ft.Control:
        """Match line + buttons for a group without per-film slots."""
        match = group.tmdb_match
        source = group.source
        # Icon reflects the assigned match's media_type when present;
        # generic disc icon when nothing is assigned yet.
        if match is not None:
            match_icon = (ft.Icons.TV if getattr(match, "media_type", None) == "tv"
                          else ft.Icons.MOVIE)
        else:
            match_icon = ft.Icons.ALBUM

        if match is not None and source == "user":
            return ft.Row(
                [
                    ft.Row([
                        ft.Icon(match_icon, size=16, color=ft.Colors.GREEN_400),
                        ft.Text(self._match_label(match.title, match.year or 0),
                                size=14, weight=ft.FontWeight.BOLD,
                                color=ft.Colors.GREEN_400),
                        ft.Text(f"[{match.media_type}]", size=12,
                                color=ft.Colors.GREY_400),
                    ], spacing=8, expand=True),
                    ft.OutlinedButton(
                        "Change match…",
                        icon=ft.Icons.EDIT,
                        on_click=lambda _e, g=group: self._change_group_match(g),
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        if match is not None and source == "auto":
            search_hint = (group.default_search_title
                           or self.app.state.get("title", "") or "")
            return ft.Row(
                [
                    ft.Column(
                        [
                            ft.Row([
                                ft.Icon(ft.Icons.AUTO_AWESOME, size=16,
                                        color=ft.Colors.AMBER_400),
                                ft.Text(self._match_label(match.title,
                                                          match.year or 0),
                                        size=14, weight=ft.FontWeight.BOLD,
                                        color=ft.Colors.AMBER_400),
                                ft.Text(f"[{match.media_type}]", size=12,
                                        color=ft.Colors.GREY_400),
                            ], spacing=8),
                            ft.Text(
                                f"Auto-filled from title '{search_hint}' — click Confirm if this is right.",
                                size=11, italic=True,
                                color=ft.Colors.AMBER_400,
                            ),
                        ],
                        expand=True, spacing=2,
                    ),
                    ft.ElevatedButton(
                        "Confirm",
                        icon=ft.Icons.CHECK,
                        on_click=lambda _e, g=group: self._confirm_group_match(g),
                    ),
                    ft.OutlinedButton(
                        "Change…",
                        icon=ft.Icons.EDIT,
                        on_click=lambda _e, g=group: self._change_group_match(g),
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=8,
            )
        return ft.Row(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.WARNING_AMBER, size=16,
                                color=ft.Colors.AMBER_400),
                        ft.Text(
                            "No match set — assign a TMDb target for these discs",
                            size=13, color=ft.Colors.AMBER_400, italic=True,
                        ),
                    ],
                    spacing=8, expand=True,
                ),
                ft.OutlinedButton(
                    "Assign match…",
                    icon=ft.Icons.ADD,
                    on_click=lambda _e, g=group: self._change_group_match(g),
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _build_film_row(self, group, idx: int, film) -> ft.Control:
        """Render one FilmSlot inside a film-group card."""
        runtime_str = self._format_runtime(film.runtime_seconds)
        left_col = ft.Column(
            [
                ft.Text(f"{film.title}  ({runtime_str})",
                        size=13, weight=ft.FontWeight.BOLD),
            ],
            spacing=2, expand=True,
        )

        buttons: list[ft.Control] = []
        if film.tmdb_match is not None and film.source == "user":
            left_col.controls.append(ft.Row([
                ft.Icon(ft.Icons.MOVIE, size=14, color=ft.Colors.GREEN_400),
                ft.Text(self._match_label(film.tmdb_match.title,
                                          film.tmdb_match.year or 0),
                        size=13, color=ft.Colors.GREEN_400,
                        weight=ft.FontWeight.BOLD),
            ], spacing=6))
            buttons.append(ft.OutlinedButton(
                "Change…",
                icon=ft.Icons.EDIT,
                on_click=lambda _e, g=group, i=idx: self._change_film_match(g, i),
            ))
        elif film.tmdb_match is not None and film.source == "auto":
            left_col.controls.append(ft.Row([
                ft.Icon(ft.Icons.AUTO_AWESOME, size=14, color=ft.Colors.AMBER_400),
                ft.Text(self._match_label(film.tmdb_match.title,
                                          film.tmdb_match.year or 0),
                        size=13, color=ft.Colors.AMBER_400,
                        weight=ft.FontWeight.BOLD),
            ], spacing=6))
            left_col.controls.append(ft.Text(
                f"Auto-filled from title '{film.title}' — click Confirm if this is right.",
                size=11, italic=True, color=ft.Colors.AMBER_400,
            ))
            buttons.extend([
                ft.ElevatedButton(
                    "Confirm",
                    icon=ft.Icons.CHECK,
                    on_click=lambda _e, g=group, i=idx: self._confirm_film_match(g, i),
                ),
                ft.OutlinedButton(
                    "Change…",
                    icon=ft.Icons.EDIT,
                    on_click=lambda _e, g=group, i=idx: self._change_film_match(g, i),
                ),
            ])
        else:
            left_col.controls.append(ft.Row([
                ft.Icon(ft.Icons.WARNING_AMBER, size=14, color=ft.Colors.AMBER_400),
                ft.Text("No match set", size=12, italic=True,
                        color=ft.Colors.AMBER_400),
            ], spacing=6))
            buttons.append(ft.OutlinedButton(
                "Assign match…",
                icon=ft.Icons.ADD,
                on_click=lambda _e, g=group, i=idx: self._change_film_match(g, i),
            ))

        return ft.Container(
            content=ft.Row(
                [left_col, *buttons],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=6,
            ),
            padding=ft.Padding(left=8, top=6, right=8, bottom=6),
            border_radius=4,
            bgcolor=ft.Colors.with_opacity(0.04, ft.Colors.WHITE),
        )

    def _build_disc_row(self, disc, ripped_discs, inserted_disc,
                        *, season_label: str = ""):
        """Render a single disc row. Returns (row_control, checkbox).

        ``season_label`` is an optional dvdcompare-derived prefix like
        ``"Season 1, Disc 2"``; when set it renders as a subtle light-blue
        info chip to the left of the content summary so users can
        cross-reference the physical case. Amber is reserved for
        warnings elsewhere on this screen, so metadata uses a neutral
        info color instead.
        """
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

        row_controls: list[ft.Control] = [
            cb,
            ft.Text(f"Disc {disc.number}{fmt_text}", width=120, size=13,
                    weight=ft.FontWeight.BOLD),
            badge,
        ]
        if season_label:
            row_controls.append(ft.Container(
                ft.Text(season_label, size=11,
                        color=ft.Colors.LIGHT_BLUE_200,
                        weight=ft.FontWeight.BOLD),
                bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.LIGHT_BLUE_400),
                border_radius=4,
                padding=ft.Padding(left=6, top=2, right=6, bottom=2),
            ))
        row_controls.append(
            ft.Text(summary, size=12, color=ft.Colors.GREY_300, expand=True),
        )

        row = ft.Row(
            row_controls,
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        return row, cb

    @staticmethod
    def _select_all_label(cbs) -> str:
        if cbs and all(cb.value for cb in cbs):
            return f"Deselect all ({len(cbs)})"
        return f"Select all ({len(cbs)})"

    @staticmethod
    def _format_runtime(seconds: int) -> str:
        if not seconds:
            return "unknown runtime"
        h, rem = divmod(seconds, 3600)
        m = rem // 60
        if h:
            return f"{h}h {m:02d}m"
        return f"{m}m"

    def _toggle_group(self, cbs, group_id: str) -> None:
        if not cbs:
            return
        target = not all(cb.value for cb in cbs)
        for cb in cbs:
            cb.value = target
        btn, _ = self._group_toggle_buttons.get(group_id, (None, None))
        if btn is not None:
            btn.text = self._select_all_label(cbs)
        self._update_summary(None)

    # ------------------------------------------------------------------
    # button handlers
    # ------------------------------------------------------------------

    def _change_group_match(self, group) -> None:
        self._enter_metadata_scope(
            seed=group.default_search_title or self.app.state.get("title", "") or group.label,
            target_group_id=group.id,
            target_film_idx=None,
        )

    def _change_film_match(self, group, film_idx: int) -> None:
        film = group.films[film_idx]
        self._enter_metadata_scope(
            seed=film.title,
            target_group_id=group.id,
            target_film_idx=film_idx,
        )

    def _enter_metadata_scope(self, *, seed: str, target_group_id: str,
                              target_film_idx) -> None:
        current_title = self.app.state.get("title", "") or ""
        self.app.state["_group_match_target_id"] = target_group_id
        self.app.state["_group_match_target_film_idx"] = target_film_idx
        self.app.state["_group_match_saved_title"] = current_title
        self.app.state["title"] = seed
        self.app.state.pop("_tmdb_results", None)
        self.app.state.pop("_tmdb_error", None)
        log.info("Change match: group=%s film_idx=%s seed=%r",
                 target_group_id, target_film_idx, seed)
        self.app.navigate("metadata")

    def _confirm_group_match(self, group) -> None:
        overrides = self.app.state.setdefault("group_tmdb_overrides", {})
        entry = overrides.setdefault(group.id, {})
        entry["match"] = group.tmdb_match
        entry["source"] = "user"
        log.info("Confirmed group %s auto-fill", group.id)
        self.app.navigate("disc_overview")

    def _confirm_film_match(self, group, film_idx: int) -> None:
        overrides = self.app.state.setdefault("group_tmdb_overrides", {})
        entry = overrides.setdefault(group.id, {})
        films_map = entry.setdefault("films", {})
        film = group.films[film_idx]
        films_map[film_idx] = {"match": film.tmdb_match, "source": "user"}
        log.info("Confirmed film %s[%d] auto-fill", group.id, film_idx)
        self.app.navigate("disc_overview")

    # ------------------------------------------------------------------
    # empty state
    # ------------------------------------------------------------------

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
        self.app.state["dvdcompare_discs"] = []
        self.app.state["_orchestrate_disc_number"] = 1
        self.app.state["disc_queue"] = [1]
        self.app.state["current_disc_idx"] = 0
        self.app.state["all_rip_results"] = {}
        self.app.navigate("selection")

    # ------------------------------------------------------------------
    # start / guard
    # ------------------------------------------------------------------

    def _update_summary(self, e):
        selected_count = sum(1 for cb in self.checkboxes if cb.value)
        self.summary_text.value = f"{selected_count} disc(s) selected for ripping"
        self._refresh_start_guard()
        self.app.page.update()

    def _selected_disc_numbers(self) -> list[int]:
        return [cb.data for cb in self.checkboxes if cb.value]

    def _groups_blocking_start(self):
        """DiscGroups holding at least one selected disc but not complete."""
        selected = set(self._selected_disc_numbers())
        blocking = []
        for g in self.app.state.get("disc_groups", []) or []:
            if not any(n in selected for n in g.disc_numbers):
                continue
            if not g.is_complete():
                blocking.append(g)
        return blocking

    def _refresh_start_guard(self) -> None:
        """Enable Start Ripping only when every selected disc's group is
        complete. Shows a red caption naming the blockers so it reads like
        a required-field validation, and hints at the escape hatch
        (deselecting the discs)."""
        if self._start_btn is None or self._blocker_text is None:
            return
        blockers = self._groups_blocking_start()
        selected = self._selected_disc_numbers()
        if not selected:
            self._start_btn.disabled = True
            self._blocker_text.value = ""
        elif blockers:
            self._start_btn.disabled = True
            names = ", ".join(g.label for g in blockers)
            self._blocker_text.value = (
                f"Assign a match for: {names} "
                "(or deselect those discs to skip them for now)."
            )
        else:
            self._start_btn.disabled = False
            self._blocker_text.value = ""

    def _start(self, e):
        selected_nums = self._selected_disc_numbers()
        if not selected_nums:
            return
        if self._groups_blocking_start():
            return

        inserted = self.app.state.get("_inserted_disc")
        if inserted and inserted in selected_nums:
            ordered = [inserted] + sorted(n for n in selected_nums if n != inserted)
        else:
            ordered = sorted(selected_nums)

        self.app.state["disc_queue"] = ordered
        self.app.state["current_disc_idx"] = 0
        self.app.state["all_rip_results"] = {}

        # Session marker: write one _riplex_session.json per work-folder
        # so a later resume of any sibling folder can discover the full
        # release layout and aggregate ripped-disc state across works.
        try:
            self._write_session_marker()
        except Exception as exc:
            log.warning("Failed to write session marker: %s", exc)

        log.info("Orchestrate: disc_queue=%s", ordered)

        self._begin_disc(ordered[0])

    def _build_session_works(self) -> list[SessionWork]:
        """Collapse ``disc_groups`` into per-folder SessionWork entries.

        Uses the same "effective match" rule as the selection screen:
        a group's own ``tmdb_match`` when set, otherwise the top-level
        match. Groups that resolve to the same folder are merged so we
        don't write two markers with disjoint disc lists.

        TV works are nested one level deeper under ``Season NN`` so that
        different seasons of the same show don't collide on ``Disc N``
        folder names. The top-level ``season_number`` in app state
        supplies the number (there is currently a single season per
        orchestrate run); movie works stay flat.
        """
        from riplex.normalize import season_folder_name

        top_match = self.app.state.get("tmdb_match")
        top_season = self.app.state.get("season_number")
        groups = self.app.state.get("disc_groups", []) or []
        seen: dict[str, SessionWork] = {}
        for g in groups:
            match = g.tmdb_match if g.tmdb_match is not None else top_match
            if match is None:
                continue
            title = getattr(match, "title", "") or ""
            year = getattr(match, "year", 0) or 0
            media_type = getattr(match, "media_type", "movie") or "movie"
            base_folder = sanitize_filename(f"{title} ({year})")
            if media_type == "tv" and top_season is not None:
                folder = f"{base_folder}/{season_folder_name(top_season)}"
            else:
                folder = base_folder
            if folder in seen:
                seen[folder].disc_numbers.extend(g.disc_numbers)
            else:
                seen[folder] = SessionWork(
                    title=title, year=year, media_type=media_type,
                    folder=folder, disc_numbers=list(g.disc_numbers),
                )
        return list(seen.values())

    def _write_session_marker(self) -> None:
        works = self._build_session_works()
        if not works:
            return
        release = self.app.state.get("release")
        release_name = release.name if release else ""
        paths = write_session_marker(works, release_name=release_name)
        log.info("Wrote session marker to %d work-folder(s)", len(paths))

    def _begin_disc(self, disc_number: int):
        # Always route through disc_swap so the user confirms via Scan
        # that the drive really contains the disc riplex is about to
        # rip. Auto-detection isn't reliable enough to short-circuit
        # this, especially for TV seasons where all discs look similar.
        self.app.state["_orchestrate_disc_number"] = disc_number
        self.app.navigate("disc_swap")
