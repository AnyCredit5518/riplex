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
        # Already-read state: navigation came back here after a successful
        # background read. Show the title-confirmation form.
        disc_read_done = self.app.state.pop("_disc_read_done", False)
        drive = self.app.state.get("drive")
        disc_info = self.app.state.get("disc_info")
        if disc_read_done and disc_info and drive:
            return self._build_results_view(drive, disc_info)

        # Normal flow: render the interactive scanning panel.
        self._user_picked = False
        self._reading = False
        self._last_drives = None
        return self._build_scanning_view()

    # ------------------------------------------------------------------
    # Results view (after a successful disc read).
    # ------------------------------------------------------------------
    def _build_results_view(self, drive: DriveInfo, disc_info) -> ft.Control:
        title = self.app.state.get("title", "")
        n_titles = len(disc_info.titles)
        total_size = sum(t.size_bytes for t in disc_info.titles) / (1024 ** 3)

        self.title_field = ft.TextField(
            label="Title",
            hint_text="Auto-detected from disc label",
            value=title,
            width=500,
        )
        self.search_btn = ft.ElevatedButton(
            "Search Metadata",
            icon=ft.Icons.SEARCH,
            on_click=self._search,
            style=ft.ButtonStyle(padding=ft.Padding(left=30, top=15, right=30, bottom=15)),
        )
        self.back_btn = ft.TextButton("Back", on_click=lambda _: self.app.navigate("welcome"))

        return ft.Column(
            [
                ft.Text("Disc Detection", size=24, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "Your disc has been read. Verify the title below and edit it if "
                    "the auto-detected name is wrong, then search for metadata.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                ft.Divider(height=20),
                ft.Row([
                    ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN),
                    ft.Text(
                        f"Found: {drive.disc_label} ({drive.device})",
                        size=14, color=ft.Colors.GREEN,
                    ),
                ], spacing=10),
                ft.Text(
                    f"{n_titles} titles, {total_size:.1f} GB total",
                    size=12, color=ft.Colors.GREY_400,
                ),
                ft.Container(height=10),
                self.title_field,
                ft.Container(expand=True),
                ft.Row([self.back_btn, self.search_btn]),
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

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
        self.back_btn = ft.TextButton("Back", on_click=lambda _: self._on_back())

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
                ft.Container(expand=True),
                ft.Row([self.back_btn]),
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
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
            self.app.state["_disc_read_done"] = True

            async def _nav():
                self.app.navigate("disc_detection")

            self.app.page.run_task(_nav)

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

    def _on_back(self) -> None:
        self._stop_polling()
        self.app.navigate("welcome")

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

    def _search(self, e):
        title = self.title_field.value.strip()
        if not title:
            self.title_field.error_text = "Enter a title"
            self.app.page.update()
            return
        self.app.state["title"] = title

        if self.app.state.get("workflow") == "orchestrate":
            from riplex.manifest import find_existing_session

            session = find_existing_session(title)
            if session:
                log.info(
                    "Found existing session for '%s' (%d) — resuming",
                    session.title, session.year,
                )
                self._resume_session(session)
                return

        self.app.navigate("metadata")

    def _resume_session(self, session):
        from riplex.metadata.provider import MetadataSearchResult

        self.app.state["tmdb_match"] = MetadataSearchResult(
            source_id="",
            title=session.title,
            year=session.year,
            media_type=session.media_type,
        )

        self.search_btn.disabled = True
        self.search_btn.text = "Resuming session..."
        self.app.page.update()

        threading.Thread(
            target=self._fetch_dvdcompare_for_resume,
            args=(session,),
            daemon=True,
        ).start()

    def _fetch_dvdcompare_for_resume(self, session):
        from riplex.disc.provider import DiscProvider, _convert_release, detect_disc_format

        disc_format = session.disc_format
        if not disc_format:
            disc_info = self.app.state.get("disc_info")
            if disc_info:
                disc_format = detect_disc_format(disc_info)

        try:
            provider = DiscProvider()
            film = asyncio.run(
                provider._fetch_film_cached(session.title, disc_format, year=session.year)
            )
            release = None
            if session.release_name and film.releases:
                release = next(
                    (r for r in film.releases
                     if r.name == session.release_name),
                    None,
                )
            if release is None and film.releases:
                release = film.releases[0]

            if release:
                self.app.state["release"] = release
                try:
                    discs = _convert_release(release)
                    self.app.state["dvdcompare_discs"] = discs
                except Exception:
                    self.app.state["dvdcompare_discs"] = []
            else:
                self.app.state["release"] = None
                self.app.state["dvdcompare_discs"] = []

            # Mirror the state that release.py sets on the non-resume
            # path so downstream screens (disc_overview / selection /
            # disc_swap) see the same signals. In particular
            # ``dvdcompare_film_title`` feeds ``build_season_labels``
            # so it can backfill the leading untitled run with the
            # season parsed from the film title (e.g. Psych: Season 1
            # -> leading discs get a "Season 1, Disc N" chip).
            if film is not None:
                self.app.state["_dvdcompare_film"] = film
                if getattr(film, "film_id", None):
                    self.app.state["dvdcompare_film_id"] = film.film_id
                if getattr(film, "title", None):
                    self.app.state["dvdcompare_film_title"] = film.title

            log.info(
                "Resume: dvdcompare loaded, %d discs, release=%s, film=%r (fid=%s)",
                len(self.app.state.get("dvdcompare_discs", [])),
                session.release_name,
                getattr(film, "title", None) if film is not None else None,
                getattr(film, "film_id", None) if film is not None else None,
            )

        except Exception as exc:
            log.warning("Resume: dvdcompare lookup failed: %s", exc)
            self.app.state["release"] = None
            self.app.state["dvdcompare_discs"] = []

        async def _nav():
            self.app.navigate("disc_overview")

        self.app.page.run_task(_nav)
