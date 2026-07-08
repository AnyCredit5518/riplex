"""Season selection screen - picks which season is on the disc for
multi-season TV shows so downstream dvdcompare queries can bias the
lookup with ``: Season N``.

Auto-skipped in three cases: (1) ``state["season_number"]`` already set
(volume label ``PSYCH_S2_D1`` parsed, folder-name parsed, or session
resume), (2) the TMDb match is a movie, (3) the show has one or fewer
non-special seasons (mini-series like Planet Earth II). In all of those
we navigate straight to the release screen with no user interaction.
"""

import logging
import threading

import flet as ft

log = logging.getLogger(__name__)

# Poll interval for the "waiting on show_detail" spinner. show_detail is
# fetched by the metadata screen in a background thread; we only need to
# poll when the user gets here before the fetch completes.
_POLL_INTERVAL_MS = 200


class SeasonSelectScreen:
    def __init__(self, app):
        self.app = app
        self._radio_group: ft.RadioGroup | None = None
        # Cached ordered list of non-special seasons for _next() lookup.
        self._non_special_seasons: list = []

    def _next_screen(self) -> str:
        return "release"

    def _should_auto_skip(self) -> tuple[bool, str]:
        """Return (skip, reason) — reason is used only for logging."""
        if self.app.state.get("season_number") is not None:
            return True, "season_number already set"
        tmdb_match = self.app.state.get("tmdb_match")
        if not tmdb_match:
            return True, "no tmdb_match (nothing to prompt about)"
        if getattr(tmdb_match, "media_type", None) != "tv":
            return True, f"media_type={getattr(tmdb_match, 'media_type', None)!r}"
        return False, ""

    def build(self) -> ft.Control:
        skip, reason = self._should_auto_skip()
        if skip:
            log.info("season_select auto-skip: %s -> %s", reason, self._next_screen())
            self._navigate_soon(self._next_screen())
            return self._loading_view("Loading...")

        show_detail = self.app.state.get("show_detail")
        if show_detail is None:
            # The metadata screen kicks off show_detail fetch in a background
            # thread right before navigating here; usually it lands within a
            # few hundred ms. Poll until it arrives (or an error was flagged).
            self._schedule_poll()
            return self._loading_view("Loading seasons from TMDb...")

        non_special = [s for s in show_detail.seasons if s.season_number != 0]
        if len(non_special) <= 1:
            # Mini-series or empty. Do NOT set season_number -- bare title
            # is what dvdcompare wants for these (per the CLI behavior).
            log.info(
                "season_select auto-skip: %d non-special season(s), mini-series path",
                len(non_special),
            )
            self._navigate_soon(self._next_screen())
            return self._loading_view("Loading...")

        self._non_special_seasons = non_special
        return self._picker_view(show_detail, non_special)

    # -- views ----------------------------------------------------------------

    def _loading_view(self, msg: str) -> ft.Control:
        return ft.Column(
            [
                ft.Text("Select Season", size=24, weight=ft.FontWeight.BOLD),
                ft.Divider(height=20),
                ft.Row(
                    [ft.ProgressRing(width=30, height=30), ft.Text(msg, size=14)],
                    spacing=10,
                ),
                ft.Container(expand=True),
                ft.Row([ft.TextButton("Back", on_click=self._on_back)]),
            ],
            spacing=10,
            expand=True,
        )

    def _picker_view(self, show_detail, non_special: list) -> ft.Control:
        title = getattr(show_detail, "title", "") or self.app.state.get("title", "")
        year = getattr(show_detail, "year", None)
        header_line = title
        if year:
            header_line = f"{title} ({year})"

        in_progress = self._scan_in_progress_seasons(title)

        # Default = first in-progress season (in TMDb order) if any,
        # else the first non-special season. Rationale: if the user is
        # mid-way through ripping any season under this show, that's
        # the most likely target for the disc they just inserted;
        # otherwise Season 1 is the sensible starting point.
        default_season: int | None = None
        for s in non_special:
            if s.season_number in in_progress:
                default_season = s.season_number
                break
        if default_season is None:
            default_season = non_special[0].season_number

        # Per-season metadata table, exposed for tests to introspect
        # without needing to walk the rendered control tree.
        self._season_meta: dict[int, dict] = {}
        rows: list[ft.Control] = []
        for s in non_special:
            base_label = f"Season {s.season_number}"
            name = (getattr(s, "name", "") or "").strip()
            if name and name.lower() != base_label.lower():
                base_label = f"{base_label} ({name})"
            ep_count = len(s.episodes)
            ep_word = "episode" if ep_count == 1 else "episodes"
            radio_label = f"{base_label} \u2014 {ep_count} {ep_word}"
            hint = in_progress.get(s.season_number)
            self._season_meta[s.season_number] = {
                "label": radio_label,
                "hint": hint,
            }
            rows.append(self._season_row(s.season_number, radio_label, hint))

        self._radio_group = ft.RadioGroup(
            value=str(default_season),
            content=ft.Column(rows, spacing=4),
        )

        picker_card = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.LIVE_TV, color=ft.Colors.BLUE_300, size=20),
                            ft.Text(
                                header_line,
                                size=14,
                                weight=ft.FontWeight.W_500,
                                color=ft.Colors.BLUE_200,
                            ),
                        ],
                        spacing=8,
                    ),
                    ft.Container(height=6),
                    self._radio_group,
                ],
                spacing=0,
            ),
            padding=ft.Padding(left=16, top=14, right=16, bottom=14),
            border=ft.Border.all(1, ft.Colors.GREY_800),
            border_radius=8,
            bgcolor=ft.Colors.with_opacity(0.03, ft.Colors.BLUE),
        )

        specials_note = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.INFO_OUTLINE, color=ft.Colors.GREY_500, size=16),
                    ft.Text(
                        "Season 0 (Specials) is not shown \u2014 extras that "
                        "match a TMDb special still route to Season 00/ "
                        "automatically at organize time.",
                        size=12,
                        color=ft.Colors.GREY_500,
                        expand=True,
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            padding=ft.Padding(left=2, top=8, right=0, bottom=0),
        )

        return ft.Column(
            [
                ft.Text("Select Season", size=24, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "Which season is on this disc?",
                    size=14,
                    color=ft.Colors.GREY_400,
                ),
                ft.Container(height=6),
                picker_card,
                specials_note,
                ft.Container(expand=True),
                ft.Row(
                    [
                        ft.TextButton("Back", on_click=self._on_back),
                        ft.FilledButton(
                            "Next",
                            icon=ft.Icons.ARROW_FORWARD,
                            on_click=self._on_next,
                        ),
                    ],
                ),
            ],
            spacing=6,
            expand=True,
        )

    def _season_row(
        self, season_number: int, radio_label: str, hint: str | None,
    ) -> ft.Control:
        """One selectable season row: radio + optional in-progress chip.

        The radio's ``label`` carries the plain-text season summary so
        the RadioGroup remains keyboard-navigable; the chip is a
        sibling control that adds color/iconography without changing
        the underlying selection semantics.
        """
        controls: list[ft.Control] = [
            ft.Radio(value=str(season_number), label=radio_label),
        ]
        if hint:
            controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(
                                ft.Icons.HOURGLASS_BOTTOM,
                                color=ft.Colors.AMBER_400,
                                size=14,
                            ),
                            ft.Text(
                                hint,
                                size=12,
                                color=ft.Colors.AMBER_400,
                                weight=ft.FontWeight.W_500,
                            ),
                        ],
                        spacing=4,
                        tight=True,
                    ),
                    padding=ft.Padding(left=8, top=2, right=8, bottom=2),
                    border=ft.Border.all(
                        1, ft.Colors.with_opacity(0.5, ft.Colors.AMBER_700),
                    ),
                    border_radius=10,
                    bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.AMBER),
                )
            )
        return ft.Row(
            controls,
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    # -- actions --------------------------------------------------------------

    def _on_back(self, _e):
        self.app.navigate("metadata")

    def _on_next(self, _e):
        if self._radio_group is None or self._radio_group.value is None:
            return
        try:
            picked = int(self._radio_group.value)
        except (TypeError, ValueError):
            log.warning("season_select: non-integer radio value %r", self._radio_group.value)
            return
        self.app.state["season_number"] = picked
        # Invalidate any dvdcompare state now that the query bias changed.
        # (No-op on the first pass; matters if the user back-navigates from
        # release, changes their season pick, and comes forward again.)
        self.app.state["release"] = None
        self.app.state["dvdcompare_discs"] = []
        self.app.state.pop("_dvdcompare_film", None)
        self.app.state.pop("_dvdcompare_error", None)
        log.info("season_select: picked season=%d", picked)

        # Orchestrate resume disambiguation: if a session exists for
        # this exact (title, season), start a full resume instead of
        # walking the fresh release-picker flow. Handles both the
        # "user came from disc_detection resume prep" path and the
        # "user backtracked from a fresh pick and changed their mind"
        # path uniformly.
        if self.app.state.get("workflow") == "orchestrate":
            title = self.app.state.get("title")
            if title:
                from riplex.manifest import find_existing_session
                session = find_existing_session(title, season_number=picked)
                if session:
                    log.info(
                        "season_select: found existing session for "
                        "'%s' season=%d — resuming",
                        title, picked,
                    )
                    self._start_resume(session)
                    return

        self.app.navigate(self._next_screen())

    def _start_resume(self, session):
        """Kick off a full resume in a background thread. Reuses the
        shared ``perform_resume_fetch`` helper that disc_detection also
        uses so both entry points converge on the same disc_overview
        state.
        """
        from riplex_app.screens.disc_detection import perform_resume_fetch

        threading.Thread(
            target=perform_resume_fetch,
            args=(self.app, session),
            daemon=True,
        ).start()

    # -- helpers --------------------------------------------------------------

    def _navigate_soon(self, screen: str):
        """Navigate on the next event-loop tick so build() returns first.

        Calling ``app.navigate`` synchronously inside ``build()`` triggers a
        re-entrant page rebuild; scheduling with ``run_task`` lets the
        current build finish, matching the pattern used by the metadata
        prefill fast-path.
        """
        async def _nav():
            self.app.navigate(screen)
        self.app.page.run_task(_nav)

    def _schedule_poll(self):
        """Re-render this screen shortly to pick up show_detail when ready."""
        def _tick():
            # Only re-navigate if the user is still on this screen; navigating
            # away (e.g. Back) should cancel the poll.
            if getattr(self.app, "_current_screen_name", None) == "season_select":
                async def _rerender():
                    if getattr(self.app, "_current_screen_name", None) == "season_select":
                        self.app.navigate("season_select")
                try:
                    self.app.page.run_task(_rerender)
                except Exception:
                    pass

        threading.Timer(_POLL_INTERVAL_MS / 1000.0, _tick).start()

    def _scan_in_progress_seasons(self, title: str) -> dict[int, str]:
        """Return ``{season_number: hint_text}`` for seasons of *title*
        that have an in-progress rip session on disk.

        Thin wrapper around ``riplex.manifest.scan_in_progress_seasons``
        that adapts the picker's ``_non_special_seasons`` list to the
        shared helper's plain-int input. See the helper for hint-text
        format and failure semantics.
        """
        from riplex.manifest import scan_in_progress_seasons
        return scan_in_progress_seasons(
            title, (s.season_number for s in self._non_special_seasons),
        )
