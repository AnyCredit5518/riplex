"""Disc detection screen — lists drives, polls for inserted discs, and lets
the user pick which drive to read from.

Replaces the original auto-pick-only flow. The screen now:

* Runs a one-shot ``makemkv_preflight`` so a missing or broken makemkvcon
  surfaces immediately instead of after a 60 s scan.
* Polls ``MakeMKV.drive_list`` every few seconds in a background thread so
  inserting / ejecting a disc updates the UI without manual refresh.
* Renders one row per detected drive with a per-drive status badge and a
  primary action (``Read disc``).
* Auto-starts the read only when exactly one drive is loaded and the user
  has not already clicked another drive.
* Routes failures through a friendly error panel with ``Retry`` and
  ``Open bug report`` buttons; the bug bundle picks up the captured
  preflight context via ``app.state['makemkv_diag']``.
"""

import asyncio
import logging
import sys
import threading

import flet as ft

from riplex.disc.makemkv import (
    DriveInfo,
    MakeMKV,
    MakeMKVError,
    MakeMKVPreflight,
    makemkv_preflight,
    run_disc_info,
)
from riplex.title import parse_title_and_season, parse_volume_label

log = logging.getLogger(__name__)

POLL_INTERVAL_S = 3.0


def _safe_update(page: ft.Page) -> None:
    """Force a UI update from a background thread."""
    try:
        page.update()
    except Exception:
        pass


def diff_drive_lists(
    previous: list[DriveInfo] | None,
    current: list[DriveInfo],
) -> bool:
    """Return ``True`` if the visible drive list changed between polls.

    Compares only the fields the GUI renders so we don't repaint the
    panel on every poll. Pure function — extracted to keep it testable
    without Flet.
    """
    if previous is None:
        return True
    visible_prev = [d for d in previous if d.is_present]
    visible_now = [d for d in current if d.is_present]
    if len(visible_prev) != len(visible_now):
        return True
    for a, b in zip(visible_prev, visible_now):
        if (a.index, a.device, a.has_disc, a.disc_label, a.state_label) != (
            b.index, b.device, b.has_disc, b.disc_label, b.state_label,
        ):
            return True
    return False


class DiscDetectionScreen:
    def __init__(self, app):
        self.app = app
        self._poll_stop: threading.Event | None = None
        self._poll_thread: threading.Thread | None = None
        self._user_picked: bool = False
        self._reading: bool = False
        self._last_drives: list[DriveInfo] | None = None

    # ------------------------------------------------------------------
    # build() — top-level dispatcher between "post-read results" and the
    # interactive scanning UI.
    # ------------------------------------------------------------------
    def build(self) -> ft.Control:
        # The former "results" step (Verify title + Search Metadata) is
        # gone -- Metadata Lookup now owns title editing and re-search
        # via its search bar + Rescan Disc button. This screen only
        # renders the interactive scanning panel; on successful read
        # we route straight through to the appropriate next screen.
        self._user_picked = False
        self._reading = False
        self._last_drives = None
        return self._build_scanning_view()

    # ------------------------------------------------------------------
    # Interactive scanning view.
    # ------------------------------------------------------------------
    def _build_scanning_view(self) -> ft.Control:
        # Stop any stale poller from a previous build (e.g. if the user
        # navigated back to this screen).
        self._stop_polling()

        self.preflight_text = ft.Text(
            "Checking makemkvcon\u2026",
            size=12, color=ft.Colors.GREY_500,
        )
        self.refresh_btn = ft.IconButton(
            icon=ft.Icons.REFRESH,
            tooltip="Rescan drives now",
            on_click=lambda _: self._trigger_poll_now(),
        )
        self.status_text = ft.Text("Scanning drives\u2026", size=14)
        self.spinner = ft.ProgressRing(width=20, height=20)
        self.drive_panel = ft.Column(spacing=8)
        self.error_panel = ft.Container(visible=False)

        body = ft.Column(
            [
                ft.Text(
                    "Insert a disc and pick the drive to read from. The list updates "
                    "automatically every few seconds.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                self.preflight_text,
                ft.Divider(height=10),
                ft.Row([self.spinner, self.status_text], spacing=10),
                self.drive_panel,
                self.error_panel,
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
        )

        self.content = ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("Disc Detection", size=24, weight=ft.FontWeight.BOLD),
                        ft.Container(expand=True),
                        self.refresh_btn,
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Container(content=body, expand=True),
                # Bottom footer row -- kept empty here so the global
                # Quit button injected by main.navigate() has a
                # canonical target and sits alongside any future
                # screen-specific buttons.
                ft.Row([]),
            ],
            spacing=10,
            expand=True,
        )

        # Run preflight + first scan + start poller in a background thread
        # so build() returns immediately.
        threading.Thread(target=self._initial_scan, daemon=True).start()
        return self.content

    # ------------------------------------------------------------------
    # Preflight + polling.
    # ------------------------------------------------------------------
    def _initial_scan(self) -> None:
        """Run preflight, do the first drive scan, then start the poller."""
        try:
            preflight = makemkv_preflight(self.app.state.get("makemkvcon"))
        except Exception as exc:  # defensive; preflight catches its own errors
            log.exception("makemkv preflight crashed: %s", exc)
            preflight = MakeMKVPreflight(exe=None, available=False, error=str(exc))

        self.app.state["makemkv_diag"] = {
            "exe": str(preflight.exe) if preflight.exe else "",
            "version": preflight.version,
            "available": preflight.available,
            "error": preflight.error,
        }

        if not preflight.available:
            self._show_preflight_failure(preflight)
            return

        self.preflight_text.value = (
            f"makemkvcon: {preflight.version or 'detected'}  \u2014  {preflight.exe}"
        )
        self.preflight_text.color = ft.Colors.GREY_400
        _safe_update(self.app.page)

        self._poll_once(initial=True)
        self._start_polling()

    def _start_polling(self) -> None:
        if self._poll_thread and self._poll_thread.is_alive():
            return
        self._poll_stop = threading.Event()
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            daemon=True,
            name="riplex-drive-poll",
        )
        self._poll_thread.start()

    def _stop_polling(self) -> None:
        if self._poll_stop is not None:
            self._poll_stop.set()
        self._poll_stop = None
        self._poll_thread = None

    def _poll_loop(self) -> None:
        stop = self._poll_stop
        assert stop is not None
        while not stop.wait(POLL_INTERVAL_S):
            if self._reading:
                continue
            try:
                self._poll_once(initial=False)
            except Exception:
                log.exception("drive poll iteration failed")

    def _trigger_poll_now(self) -> None:
        if self._reading:
            return
        threading.Thread(
            target=lambda: self._poll_once(initial=False),
            daemon=True,
        ).start()

    def _poll_once(self, *, initial: bool) -> None:
        try:
            mk = MakeMKV(self.app.state.get("makemkvcon"))
            drives = mk.drive_list()
        except MakeMKVError as exc:
            log.warning("makemkvcon refused to list drives (code %s): %s", exc.code, exc)
            self._show_error(
                "MakeMKV won\u2019t scan drives",
                f"makemkvcon reported: {exc}\n\n"
                "MakeMKV must be updated (or a valid registration key entered) "
                "before riplex can detect discs. The free beta key is refreshed "
                "monthly on the MakeMKV forum.",
                allow_retry=True,
                install_hint=True,
                key_hint=True,
            )
            return
        except Exception as exc:
            log.warning("drive_list failed: %s", exc)
            if initial:
                self._show_error(
                    "Couldn\u2019t list drives",
                    f"makemkvcon failed: {exc}",
                )
            return

        if not diff_drive_lists(self._last_drives, drives):
            return
        self._last_drives = drives
        self._render_drives(drives)
        self._maybe_auto_pick(drives)

    # ------------------------------------------------------------------
    # Rendering.
    # ------------------------------------------------------------------
    def _render_drives(self, drives: list[DriveInfo]) -> None:
        visible = [d for d in drives if d.is_present]

        self.spinner.visible = False
        self.error_panel.visible = False

        if not visible:
            self.status_text.value = (
                "No optical drives detected. Connect a drive and click Refresh."
            )
            self.status_text.color = ft.Colors.ORANGE
            self.drive_panel.controls.clear()
            _safe_update(self.app.page)
            return

        loaded_count = sum(1 for d in visible if d.has_disc)
        if loaded_count == 0:
            self.status_text.value = (
                f"{len(visible)} drive(s) detected. Insert a disc \u2014 the list "
                "refreshes every few seconds."
            )
            self.status_text.color = ft.Colors.GREY_400
        else:
            self.status_text.value = (
                f"{loaded_count} of {len(visible)} drive(s) have a disc. Pick one to read."
            )
            self.status_text.color = None

        self.drive_panel.controls = [self._build_drive_row(d) for d in visible]
        _safe_update(self.app.page)

    def _build_drive_row(self, drive: DriveInfo) -> ft.Control:
        if drive.has_disc:
            icon = ft.Icon(ft.Icons.ALBUM, color=ft.Colors.GREEN)
            status_color = ft.Colors.GREEN
            primary = ft.ElevatedButton(
                "Read disc",
                icon=ft.Icons.PLAY_ARROW,
                on_click=lambda _, d=drive: self._on_pick_drive(d),
            )
        else:
            icon = ft.Icon(ft.Icons.RADIO_BUTTON_UNCHECKED, color=ft.Colors.GREY_500)
            status_color = ft.Colors.GREY_500
            primary = ft.OutlinedButton(
                "Empty",
                icon=ft.Icons.EJECT,
                disabled=True,
            )

        device_label = drive.device or f"#{drive.index}"
        name_label = drive.name or "(unknown drive)"

        return ft.Container(
            content=ft.Row(
                [
                    icon,
                    ft.Column(
                        [
                            ft.Text(
                                f"{device_label}  \u2014  {name_label}",
                                size=13, weight=ft.FontWeight.BOLD,
                            ),
                            ft.Text(
                                drive.state_label or ("Disc loaded" if drive.has_disc else "Empty"),
                                size=12, color=status_color,
                            ),
                        ],
                        spacing=2, expand=True,
                    ),
                    primary,
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=10,
            # ``ft.Border.all`` (uppercase) is the cross-version form;
            # the lowercase ``ft.border`` module was removed in Flet 0.85.
            border=ft.Border.all(1, ft.Colors.GREY_800),
            border_radius=6,
        )

    # ------------------------------------------------------------------
    # Auto-pick + manual pick.
    # ------------------------------------------------------------------
    def _maybe_auto_pick(self, drives: list[DriveInfo]) -> None:
        if self._user_picked or self._reading:
            return
        loaded = [d for d in drives if d.is_present and d.has_disc]
        if len(loaded) != 1:
            return
        drive = loaded[0]
        log.info("auto-picking sole loaded drive %s (%s)", drive.index, drive.device)
        self._begin_read(drive)

    def _on_pick_drive(self, drive: DriveInfo) -> None:
        self._user_picked = True
        self._begin_read(drive)

    def _begin_read(self, drive: DriveInfo) -> None:
        if self._reading:
            return
        self._reading = True
        self._stop_polling()

        self.app.state["drive"] = drive
        self.error_panel.visible = False
        self.spinner.visible = True
        self.status_text.value = (
            f"Reading disc: {drive.disc_label or '(no label)'} ({drive.device})\u2026\n"
            "This can take up to a minute."
        )
        self.status_text.color = None
        self.drive_panel.controls.clear()
        _safe_update(self.app.page)

        threading.Thread(target=self._read_disc, args=(drive,), daemon=True).start()

    def _read_disc(self, drive: DriveInfo) -> None:
        try:
            print(
                f"[disc_detection] Reading disc info for drive {drive.index}\u2026",
                file=sys.stderr,
            )
            disc_info = run_disc_info(
                drive.index,
                makemkvcon=self.app.state.get("makemkvcon"),
            )
            print(
                f"[disc_detection] Got "
                f"{len(disc_info.titles) if disc_info else 0} titles",
                file=sys.stderr,
            )

            if disc_info is None or not disc_info.titles:
                self._reading = False
                self._show_error(
                    "No titles found on disc",
                    "Try ejecting and reinserting the disc, or pick a different drive.",
                    allow_retry=True,
                )
                return

            self.app.state["disc_info"] = disc_info
            parsed_title, parsed_season = parse_title_and_season(drive.disc_label)
            self.app.state["title"] = parsed_title or self._parse_volume_label(drive.disc_label)
            if parsed_season is not None:
                self.app.state["season_number"] = parsed_season
            else:
                self.app.state.pop("season_number", None)

            # Route straight into the next step -- no intermediate
            # "Verify title" screen. Metadata Lookup owns title editing
            # + re-search. Orchestrate resumes still short-circuit
            # here (TV -> season_select, movie -> disc_overview) so a
            # known session doesn't force an unnecessary TMDb round-trip.
            self._route_after_read()

        except Exception as exc:
            log.exception("disc read failed")
            self._reading = False
            self._show_error(
                "Couldn\u2019t read disc",
                str(exc),
                allow_retry=True,
            )

    # ------------------------------------------------------------------
    # Error panels.
    # ------------------------------------------------------------------
    def _show_preflight_failure(self, preflight: MakeMKVPreflight) -> None:
        self.spinner.visible = False
        self.preflight_text.value = (
            f"makemkvcon unavailable: {preflight.error}"
        )
        self.preflight_text.color = ft.Colors.RED
        self.status_text.value = (
            "Riplex can\u2019t talk to MakeMKV. Install or repair MakeMKV "
            "and click Refresh."
        )
        self.status_text.color = ft.Colors.RED
        self.drive_panel.controls.clear()
        self.error_panel.content = self._build_error_panel(
            "MakeMKV not available",
            preflight.error or "makemkvcon could not be invoked.",
            allow_retry=True,
            install_hint=True,
        )
        self.error_panel.visible = True
        _safe_update(self.app.page)

    def _show_error(
        self,
        title: str,
        detail: str,
        *,
        allow_retry: bool = True,
        install_hint: bool = False,
        key_hint: bool = False,
    ) -> None:
        self.spinner.visible = False
        self.status_text.value = title
        self.status_text.color = ft.Colors.RED
        self.drive_panel.controls.clear()
        self.error_panel.content = self._build_error_panel(
            title,
            detail,
            allow_retry=allow_retry,
            install_hint=install_hint,
            key_hint=key_hint,
        )
        self.error_panel.visible = True
        _safe_update(self.app.page)

    def _build_error_panel(
        self,
        title: str,
        detail: str,
        *,
        allow_retry: bool,
        install_hint: bool,
        key_hint: bool = False,
    ) -> ft.Control:
        children: list[ft.Control] = [
            ft.Row(
                [
                    ft.Icon(ft.Icons.ERROR_OUTLINE, color=ft.Colors.RED),
                    ft.Text(title, size=14, weight=ft.FontWeight.BOLD),
                ],
                spacing=8,
            ),
            ft.Text(detail, size=12, color=ft.Colors.GREY_300, selectable=True),
            ft.Text(
                "Debug logs are written to the riplex log directory and "
                "included automatically when you open a bug report.",
                size=11, color=ft.Colors.GREY_500,
            ),
        ]
        actions: list[ft.Control] = []
        if allow_retry:
            actions.append(
                ft.ElevatedButton(
                    "Retry",
                    icon=ft.Icons.REFRESH,
                    on_click=lambda _: self._on_retry(),
                )
            )
        if install_hint:
            actions.append(
                ft.TextButton(
                    "Download MakeMKV \u2197",
                    url="https://www.makemkv.com/download/",
                )
            )
        if key_hint:
            actions.append(
                ft.TextButton(
                    "Get beta key \u2197",
                    url="https://forum.makemkv.com/forum/viewtopic.php?t=1053",
                )
            )
        actions.append(
            ft.OutlinedButton(
                "Open bug report",
                icon=ft.Icons.BUG_REPORT,
                on_click=lambda _: self._open_bug_report(),
            )
        )
        children.append(ft.Row(actions, spacing=8, wrap=True))

        return ft.Container(
            content=ft.Column(children, spacing=8),
            padding=12,
            border=ft.Border.all(1, ft.Colors.RED_900),
            border_radius=6,
            bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.RED),
        )

    # ------------------------------------------------------------------
    # Misc handlers.
    # ------------------------------------------------------------------
    def _on_retry(self) -> None:
        self._reading = False
        self._user_picked = False
        self._last_drives = None
        self.error_panel.visible = False
        self.spinner.visible = True
        self.status_text.value = "Scanning drives\u2026"
        self.status_text.color = None
        _safe_update(self.app.page)
        threading.Thread(target=self._initial_scan, daemon=True).start()

    def _open_bug_report(self) -> None:
        import webbrowser
        from riplex_app.bug_report import build_bug_report_url

        url = build_bug_report_url(self.app.state)
        log.info("Opening bug report from disc_detection: %s", url)
        webbrowser.open(url)

    # ------------------------------------------------------------------
    # Helpers preserved from the previous implementation.
    # ------------------------------------------------------------------
    def _parse_volume_label(self, label: str) -> str:
        result = parse_volume_label(label)
        return result if result else label.replace("_", " ").strip().title()

    def _route_after_read(self) -> None:
        """Decide the next screen after a successful disc read.

        Orchestrate resumes short-circuit here so an in-progress
        session for this title doesn't force an unnecessary TMDb
        round-trip: TV titles route through ``season_select`` (so the
        user can pick a different season even if S1 is still in
        progress), movies go straight into ``disc_overview`` via the
        resume adapter. All other cases fall through to ``metadata``
        where the user can edit the title and re-search.
        """
        title = (self.app.state.get("title") or "").strip()

        if title and self.app.state.get("workflow") == "orchestrate":
            from riplex.manifest import find_existing_session

            session = find_existing_session(title)
            if session:
                log.info(
                    "Found existing session for '%s' (%d) \u2014 media_type=%s",
                    session.title, session.year, session.media_type,
                )
                if session.media_type == "tv":
                    self._prepare_tv_season_pick(session)
                    return
                self._resume_session(session)
                return

        async def _nav():
            self.app.navigate("metadata")

        self.app.page.run_task(_nav)

    def _prepare_tv_season_pick(self, session):
        """Preload just enough state for season_select to render, then
        navigate there. Full resume (dvdcompare film + discs) is
        deferred until the user picks a season on that screen.
        """
        from riplex.metadata.provider import MetadataSearchResult

        self.app.state["tmdb_match"] = MetadataSearchResult(
            source_id=session.source_id,
            title=session.title,
            year=session.year,
            media_type=session.media_type,
        )
        # season_number stays unset — season_select will prompt.
        self.app.state.pop("season_number", None)
        self.app.state.pop("release", None)
        self.app.state.pop("dvdcompare_discs", None)

        threading.Thread(
            target=self._fetch_show_detail_for_season_pick,
            args=(session,),
            daemon=True,
        ).start()

    def _fetch_show_detail_for_season_pick(self, session):
        """Fetch TMDb show_detail so season_select can list seasons,
        then navigate. show_detail is the same data the metadata
        screen fetches on the fresh flow (in background before nav to
        season_select); here we mirror that pattern for the resume
        entry point."""
        from riplex.resume import _fetch_show_detail

        source_id = session.source_id
        if source_id:
            try:
                detail = asyncio.run(_fetch_show_detail(source_id))
                if detail is not None:
                    self.app.state["show_detail"] = detail
            except Exception as exc:
                log.warning("Resume: show_detail prefetch failed: %s", exc)

        async def _nav():
            self.app.navigate("season_select")

        self.app.page.run_task(_nav)

    def _resume_session(self, session):
        from riplex.metadata.provider import MetadataSearchResult

        # source_id comes from the session marker written at
        # orchestrate start. Legacy sessions (or sessions started before
        # the marker carried source_id) leave it empty, which will
        # block organize until the user re-picks metadata — the rip
        # flow itself doesn't need source_id, only organize does.
        self.app.state["tmdb_match"] = MetadataSearchResult(
            source_id=session.source_id,
            title=session.title,
            year=session.year,
            media_type=session.media_type,
        )

        threading.Thread(
            target=self._fetch_dvdcompare_for_resume,
            args=(session,),
            daemon=True,
        ).start()

    def _fetch_dvdcompare_for_resume(self, session):
        """Rehydrate lookup state via the shared adapter and populate ``app.state``.

        Thin wrapper around :func:`perform_resume_fetch` so the resume
        thread has a consistent target across GUI screens (both this
        screen and ``season_select`` can start a resume without
        duplicating the adapter-to-state translation).
        """
        perform_resume_fetch(self.app, session)


def perform_resume_fetch(app, session) -> None:
    """Rehydrate lookup state via the shared adapter and populate ``app.state``.

    All network / matching / backfill logic lives in
    :func:`riplex.resume.resume_from_session`; this function's only
    job is to translate the returned :class:`~riplex.resume.ResumedLookup`
    into the ``app.state`` keys the downstream screens
    (disc_overview / selection / disc_swap) already read on the
    fresh-lookup path, then navigate to ``disc_overview``.

    Designed to be called from a background thread. Kept at module
    scope (not a screen method) so ``season_select`` can also start a
    resume when the user picks a season with an in-progress session.
    """
    from riplex.resume import resume_from_session

    disc_info = app.state.get("disc_info")
    try:
        result = asyncio.run(
            resume_from_session(session, disc_info=disc_info)
        )
    except Exception as exc:
        log.warning("Resume: adapter failed: %s", exc)
        app.state["release"] = None
        app.state["dvdcompare_discs"] = []

        async def _nav_fail():
            app.navigate("disc_overview")

        app.page.run_task(_nav_fail)
        return

    # Keep any TMDb rehydration the adapter did (legacy markers).
    if result.tmdb_match is not None:
        app.state["tmdb_match"] = result.tmdb_match

    app.state["release"] = result.release
    app.state["dvdcompare_discs"] = list(result.discs)
    app.state["primary_movie_needs_slot"] = result.primary_movie_needs_slot
    app.state["hidden_disc_numbers"] = list(result.hidden_disc_numbers)
    if result.movie_runtime:
        app.state["movie_runtime"] = result.movie_runtime

    if result.dvdcompare_film is not None:
        app.state["_dvdcompare_film"] = result.dvdcompare_film
    if result.dvdcompare_film_id:
        app.state["dvdcompare_film_id"] = result.dvdcompare_film_id
    if result.dvdcompare_film_title:
        app.state["dvdcompare_film_title"] = result.dvdcompare_film_title
    if result.season_number is not None and app.state.get("season_number") is None:
        app.state["season_number"] = result.season_number
    # ShowDetail lets the selection screen enrich rip-guide labels
    # with canonical S/E numbers. On fresh (non-resume) flows the
    # metadata screen fetches this in the background; resumes get
    # it via the adapter so both paths converge.
    if result.show_detail is not None:
        app.state["show_detail"] = result.show_detail

    if result.dvdcompare_error is not None:
        log.warning(
            "Resume: dvdcompare degraded (%s); user can edit release later",
            result.dvdcompare_error,
        )

    async def _nav():
        app.navigate("disc_overview")

    app.page.run_task(_nav)
