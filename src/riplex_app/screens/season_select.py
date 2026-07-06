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
                ft.TextButton("Back", on_click=self._on_back),
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

        radios: list[ft.Control] = []
        for s in non_special:
            label = f"Season {s.season_number}"
            name = (getattr(s, "name", "") or "").strip()
            if name and name.lower() != label.lower():
                label = f"{label} ({name})"
            ep_count = len(s.episodes)
            ep_word = "episode" if ep_count == 1 else "episodes"
            radios.append(
                ft.Radio(
                    value=str(s.season_number),
                    label=f"{label} \u2014 {ep_count} {ep_word}",
                )
            )

        # Default = the first non-special season (usually season 1).
        default_value = str(non_special[0].season_number)
        self._radio_group = ft.RadioGroup(
            value=default_value,
            content=ft.Column(radios, spacing=6),
        )

        return ft.Column(
            [
                ft.Text("Select Season", size=24, weight=ft.FontWeight.BOLD),
                ft.Text(
                    f"Which season is on this disc? ({header_line})",
                    size=14,
                    color=ft.Colors.GREY_400,
                ),
                ft.Text(
                    "Season 0 (Specials) is not shown here \u2014 extras on "
                    "the disc that match a TMDb special still route to "
                    "Season 00/ automatically at organize time.",
                    size=12,
                    color=ft.Colors.GREY_500,
                ),
                ft.Divider(height=20),
                ft.Container(
                    content=self._radio_group,
                    padding=ft.Padding(left=10, top=0, right=0, bottom=0),
                ),
                ft.Container(expand=True),
                ft.Row(
                    [
                        ft.TextButton("Back", on_click=self._on_back),
                        ft.FilledButton("Next", on_click=self._on_next),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
            ],
            spacing=10,
            expand=True,
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
        self.app.navigate(self._next_screen())

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
