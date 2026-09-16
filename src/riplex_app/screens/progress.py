"""Progress screen - shows rip progress for each title."""

from dataclasses import dataclass
import logging
import threading
import time
from pathlib import Path
from typing import Any

import flet as ft

from riplex.disc.makemkv import run_rip, RipProgress, RipResult
from riplex.rip_outcome import summarize_rip_results
from riplex.snapshot import copy_debug_log, get_debug_dir, save_rip_snapshot
from riplex_app.background import (
    ScreenLease,
    capture_screen_lease,
    operations_for,
    screen_lease_is_current,
    start_background_once,
)
from riplex_app.crash_dump import get_log_path
from riplex_app.keep_awake import keep_awake

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RipJob:
    lease: ScreenLease
    workflow: str | None
    selected_titles: tuple[int, ...]
    output_dir: Any
    makemkvcon: Any
    drive: Any
    disc_info: Any
    tmdb_match: Any
    dvdcompare_discs: tuple[Any, ...]
    movie_runtime: int | None
    disc_number: int | None
    release: Any
    show_detail: Any
    dvdcompare_film_title: str | None
    episode_carryover: tuple[Any, ...]
    dvdcompare_film_id: int | None
    season_number: int | None
    disc_queue: tuple[int, ...]
    current_disc_idx: int
    all_rip_results: dict[Any, list[RipResult]]
    ripped_discs: frozenset[Any]


def _format_eta(seconds: int) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    if seconds < 0:
        return "..."
    if seconds >= 3600:
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}"
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


class ProgressScreen:
    def __init__(self, app):
        self.app = app
        self._cancel_event = threading.Event()

    def _capture_rip_job(self) -> RipJob:
        state = self.app.state
        return RipJob(
            lease=capture_screen_lease(self.app),
            workflow=state.get("workflow"),
            selected_titles=tuple(state.get("selected_titles") or ()),
            output_dir=state.get("output_dir"),
            makemkvcon=state.get("makemkvcon"),
            drive=state.get("drive"),
            disc_info=state.get("disc_info"),
            tmdb_match=state.get("tmdb_match"),
            dvdcompare_discs=tuple(state.get("dvdcompare_discs") or ()),
            movie_runtime=state.get("movie_runtime"),
            disc_number=state.get("_orchestrate_disc_number"),
            release=state.get("release"),
            show_detail=state.get("show_detail"),
            dvdcompare_film_title=state.get("dvdcompare_film_title"),
            episode_carryover=tuple(state.get("episode_carryover") or ()),
            dvdcompare_film_id=state.get("dvdcompare_film_id"),
            season_number=state.get("season_number"),
            disc_queue=tuple(state.get("disc_queue") or ()),
            current_disc_idx=state.get("current_disc_idx", 0),
            all_rip_results=dict(state.get("all_rip_results") or {}),
            ripped_discs=frozenset(state.get("ripped_discs") or ()),
        )

    def build(self) -> ft.Control:
        if operations_for(self.app).is_active("rip") and hasattr(self, "content"):
            return self.content

        self._cancel_event.clear()
        selected = self.app.state["selected_titles"]
        disc_info = self.app.state["disc_info"]
        titles = disc_info.titles if disc_info else []

        # Map index to title for display
        self.title_map = {t.index: t for t in titles}
        self.total_count = len(selected)
        self.completed_count = 0

        self._rip_start_time = 0.0
        self._last_pct = -1
        self._current_title_bytes = 0

        self.overall_text = ft.Text(
            f"Ripping 0/{self.total_count} titles...",
            size=16,
            weight=ft.FontWeight.BOLD,
        )
        self.current_title_text = ft.Text("Preparing...", size=14, color=ft.Colors.GREY_400)
        self.progress_bar = ft.ProgressBar(width=700, value=0)
        self.progress_pct = ft.Text("0%", size=12, weight=ft.FontWeight.BOLD)
        self.progress_size = ft.Text("", size=12, color=ft.Colors.GREY_400)
        self.progress_speed = ft.Text("", size=12, color=ft.Colors.GREY_400)
        self.progress_eta = ft.Text("", size=12, color=ft.Colors.GREY_400)
        self.log = ft.ListView(spacing=4, height=200, auto_scroll=True)
        self.cancel_btn = ft.ElevatedButton(
            "Stop Ripping",
            icon=ft.Icons.STOP,
            on_click=self._cancel,
            style=ft.ButtonStyle(bgcolor=ft.Colors.RED_700),
        )

        # Disc indicator for orchestrate mode
        disc_indicator = ft.Container()
        if self.app.state.get("workflow") == "orchestrate":
            disc_num = self.app.state.get("_orchestrate_disc_number")
            disc_queue = self.app.state.get("disc_queue", [])
            if disc_num and disc_queue:
                queue_pos = disc_queue.index(disc_num) + 1 if disc_num in disc_queue else 0
                disc_indicator = ft.Text(
                    f"Disc {disc_num} ({queue_pos}/{len(disc_queue)})",
                    size=13, color=ft.Colors.BLUE_400, weight=ft.FontWeight.BOLD,
                )

        self.content = ft.Column(
            [
                ft.Text("Ripping", size=24, weight=ft.FontWeight.BOLD),
                disc_indicator,
                ft.Text(
                    "MakeMKV is ripping the selected titles. This can take a while "
                    "depending on disc size and drive speed. Do not eject the disc.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                ft.Divider(height=20),
                self.overall_text,
                self.current_title_text,
                ft.Container(height=10),
                self.progress_bar,
                ft.Row(
                    [
                        self.progress_pct,
                        self.progress_size,
                        self.progress_speed,
                        self.progress_eta,
                    ],
                    spacing=20,
                ),
                ft.Container(height=20),
                ft.Text("Log", size=14, weight=ft.FontWeight.BOLD),
                self.log,
                ft.Container(height=10),
                self.cancel_btn,
            ],
            spacing=10,
            expand=True,
        )

        # Start ripping in background
        self._rip_job = self._capture_rip_job()
        start_background_once(
            self.app,
            "rip",
            self._run_rips,
            args=(self._rip_job,),
        )

        return self.content

    def _run_rips(self, job: RipJob | None = None):
        """Rip all selected titles sequentially."""
        with keep_awake("ripping titles"):
            self._run_rips_inner(job)

    def _run_rips_inner(self, job: RipJob | None = None):
        job = job or getattr(self, "_rip_job", None) or self._capture_rip_job()
        selected = job.selected_titles
        output_dir = job.output_dir
        makemkvcon = job.makemkvcon
        drive = job.drive
        results: list[RipResult] = []

        for i, title_idx in enumerate(selected):
            if self._cancel_event.is_set():
                self._log_message("Stopped by user.", ft.Colors.ORANGE)
                break

            title = self.title_map.get(title_idx)
            title_name = title.name or title.filename if title else f"Title {title_idx}"
            size_gb = (title.size_bytes / (1024 ** 3)) if title else 0

            self.completed_count = i
            self.overall_text.value = f"Ripping {i + 1}/{self.total_count} titles..."
            self.current_title_text.value = f"Title #{title_idx}: {title_name} ({size_gb:.1f} GB)"
            self.progress_bar.value = 0
            self.progress_pct.value = "0%"
            self.progress_size.value = f"0.0/{size_gb:.1f} GB"
            self.progress_speed.value = ""
            self.progress_eta.value = ""
            self._rip_start_time = time.monotonic()
            self._last_pct = -1
            self._current_title_bytes = title.size_bytes if title else 0
            self._log_message(f"Starting title #{title_idx}: {title_name}")
            self._update()

            start_time = time.time()
            try:
                result = run_rip(
                    drive.index,
                    title_idx,
                    output_dir,
                    makemkvcon=makemkvcon,
                    progress_callback=self._on_progress,
                    cancel_event=self._cancel_event,
                )
                results.append(result)
                elapsed = time.time() - start_time
                elapsed_str = f"{int(elapsed // 60)}:{int(elapsed % 60):02d}"

                if result.success:
                    self._log_message(
                        f"Done: {result.output_file} ({elapsed_str})",
                        ft.Colors.GREEN,
                    )
                else:
                    self._log_message(
                        f"FAILED: {result.error_message}",
                        ft.Colors.RED,
                    )
            except Exception as exc:
                self._log_message(f"Error: {exc}", ft.Colors.RED)
                results.append(RipResult(
                    title_index=title_idx,
                    success=False,
                    output_file="",
                    error_message=str(exc),
                ))

        # Done
        cancelled = self._cancel_event.is_set()
        if screen_lease_is_current(self.app, job.lease):
            self.app.state["rip_results"] = results
            if cancelled:
                self.overall_text.value = "Cancelled."
            else:
                self.overall_text.value = (
                    f"Complete: {sum(1 for r in results if r.success)}/{len(results)} successful"
                )
            self.current_title_text.value = ""
            self.progress_bar.value = 1.0
            self.progress_pct.value = "100%"
            self.progress_size.value = ""
            self.progress_speed.value = ""
            self.progress_eta.value = ""
            self.cancel_btn.visible = False
            self._update()

        # Cancelled: do NOT mark this disc ripped, write a manifest (which
        # would flag it as completed for resume), auto-eject, or advance the
        # queue. Return to this disc's Insert Disc screen so the user can
        # retry, skip, or eject — they aborted on purpose and may want any of
        # those. (Non-orchestrate rips just show the results summary.)
        if cancelled:
            if not screen_lease_is_current(self.app, job.lease):
                return
            self._log_message(
                "Rip cancelled. Returning to disc options — retry, skip, or eject.",
                ft.Colors.ORANGE,
            )
            self._update()
            target = (
                "disc_swap"
                if job.workflow == "orchestrate"
                else "done"
            )

            async def _nav_cancel():
                if screen_lease_is_current(self.app, job.lease):
                    self.app.navigate(target)

            self.app.page.run_task(_nav_cancel)
            return

        # Write debug snapshots
        self._write_snapshots(results, job)

        # Write rip manifest (for orchestrate resume support)
        self._write_manifest(results, job)

        if not screen_lease_is_current(self.app, job.lease):
            log.info("Finished an abandoned rip without changing the active workflow")
            return

        # Auto-eject the finished disc so the user can swap discs (or knows
        # the rip is done) without reaching for the drive.
        self._auto_eject(results, job)

        if not screen_lease_is_current(self.app, job.lease):
            return

        # Brief pause then navigate
        time.sleep(1)

        # Navigation must run on the Flet event loop, not this bg thread,
        # or the client won't receive the new screen until the next OS event
        # (e.g. the user moving the window). See _update() note.
        if not screen_lease_is_current(self.app, job.lease):
            return
        if job.workflow == "orchestrate":
            async def _nav_next():
                if screen_lease_is_current(self.app, job.lease):
                    self._advance_orchestrate(results, job)
            self.app.page.run_task(_nav_next)
        else:
            async def _nav_done():
                if screen_lease_is_current(self.app, job.lease):
                    self.app.navigate("done")
            self.app.page.run_task(_nav_done)

    def _write_snapshots(
        self,
        results: list[RipResult],
        job: RipJob | None = None,
    ):
        """Write debug snapshots to _riplex/ folder after rip."""
        output_dir = job.output_dir if job is not None else self.app.state.get("output_dir")
        if not output_dir:
            return
        try:
            debug_dir = get_debug_dir(Path(output_dir).parent)

            disc_info = job.disc_info if job is not None else self.app.state.get("disc_info")
            tmdb_match = job.tmdb_match if job is not None else self.app.state.get("tmdb_match")
            discs = job.dvdcompare_discs if job is not None else self.app.state.get("dvdcompare_discs", [])

            canonical = tmdb_match.title if tmdb_match else ""
            year = tmdb_match.year if tmdb_match else None
            is_movie = getattr(tmdb_match, "media_type", "movie") != "tv"
            movie_runtime = getattr(tmdb_match, "runtime_seconds", None) if is_movie else None

            save_rip_snapshot(
                debug_dir, disc_info,
                canonical=canonical, year=year, is_movie=is_movie,
                movie_runtime=movie_runtime,
                discs=discs,
                selected_titles=(
                    job.selected_titles
                    if job is not None
                    else self.app.state.get("selected_titles", [])
                ),
                ripped_titles=[r.title_index for r in results if r.success],
                phase="complete",
            )
            copy_debug_log(debug_dir, get_log_path())
            if job is None or screen_lease_is_current(self.app, job.lease):
                self.app.state["debug_dir"] = str(debug_dir)
            log.info("Wrote debug snapshots to %s", debug_dir)
        except Exception as exc:
            log.warning("Failed to write debug snapshots: %s", exc)

    def _write_manifest(
        self,
        results: list[RipResult],
        job: RipJob | None = None,
    ):
        """Write a rip manifest for resume support."""
        from riplex.manifest import build_rip_manifest, write_manifest

        output_dir = job.output_dir if job is not None else self.app.state.get("output_dir")
        disc_info = job.disc_info if job is not None else self.app.state.get("disc_info")
        tmdb_match = job.tmdb_match if job is not None else self.app.state.get("tmdb_match")
        if not output_dir or not disc_info or not tmdb_match:
            return

        succeeded = [r for r in results if r.success]
        if not succeeded:
            return

        try:
            canonical = tmdb_match.title
            year = tmdb_match.year or 0
            is_movie = getattr(tmdb_match, "media_type", "movie") != "tv"
            movie_runtime = job.movie_runtime if job is not None else self.app.state.get("movie_runtime")
            disc_number = job.disc_number if job is not None else self.app.state.get("_orchestrate_disc_number")
            drive = job.drive if job is not None else self.app.state.get("drive")
            volume_label = drive.disc_label if drive else ""
            release = job.release if job is not None else self.app.state.get("release")
            release_name = release.name if release else ""

            # Get analysis data for classification
            from riplex.disc.provider import detect_disc_format
            disc_format = detect_disc_format(disc_info) if disc_info else None

            # Get dvd_entries info from the analysis stored during selection
            dvdcompare_discs = (
                job.dvdcompare_discs
                if job is not None
                else self.app.state.get("dvdcompare_discs", [])
            )
            from riplex.disc.analysis import (
                analyze_disc,
                collect_tmdb_episodes_for_disc,
            )
            tmdb_episodes = [] if is_movie else collect_tmdb_episodes_for_disc(
                job.show_detail if job is not None else self.app.state.get("show_detail"),
                dvdcompare_discs,
                disc_number,
                film_title=(
                    job.dvdcompare_film_title
                    if job is not None
                    else self.app.state.get("dvdcompare_film_title")
                ),
            )
            analysis = analyze_disc(
                disc_info, dvdcompare_discs,
                disc_number=disc_number,
                is_movie=is_movie,
                movie_runtime=movie_runtime,
                tmdb_episodes=tmdb_episodes,
                episode_carryover=(
                    job.episode_carryover
                    if job is not None
                    else self.app.state.get("episode_carryover") or []
                ),
            )

            manifest = build_rip_manifest(
                canonical=canonical,
                year=year,
                is_movie=is_movie,
                disc_number=disc_number,
                volume_label=volume_label,
                disc_format=disc_format,
                release_name=release_name,
                disc_info=disc_info,
                rip_results=results,
                dvd_entries=analysis.dvd_entries,
                movie_runtime=movie_runtime,
                total_episode_runtime=analysis.total_episode_runtime,
                episode_count=analysis.episode_count,
                tmdb_source_id=getattr(tmdb_match, "source_id", None),
                dvdcompare_film_id=(
                    job.dvdcompare_film_id
                    if job is not None
                    else self.app.state.get("dvdcompare_film_id")
                ),
                dvdcompare_release_name=(release.name if release else None),
                season_number=(
                    job.season_number
                    if job is not None
                    else self.app.state.get("season_number")
                ),
                episode_carryover=analysis.next_episode_carryover,
            )
            manifest_path = write_manifest(Path(output_dir), manifest)
            if job is None or screen_lease_is_current(self.app, job.lease):
                self.app.state["episode_carryover"] = analysis.next_episode_carryover
            log.info("Wrote rip manifest: %s", manifest_path)
        except Exception as exc:
            log.warning("Failed to write rip manifest: %s", exc)

    def _auto_eject(
        self,
        results: list[RipResult],
        job: RipJob | None = None,
    ):
        """Eject the disc once ripping finishes, unless disabled in config.

        Best-effort: a failed eject is logged and surfaced in the activity
        log but never blocks the flow. Skipped when the user cancelled or no
        title actually ripped (so a failed disc can be retried without a
        manual reload).
        """
        from riplex.config import get_auto_eject
        from riplex.disc.makemkv import eject_disc

        if not get_auto_eject():
            return
        if self._cancel_event.is_set():
            return
        if not summarize_rip_results(results).has_successes:
            return

        drive = job.drive if job is not None else self.app.state.get("drive")
        device = getattr(drive, "device", None)
        if not device:
            return

        try:
            eject_disc(device)
            log.info("Auto-ejected %s", device)
            self._log_message(f"Ejected {device}.", ft.Colors.GREEN)
        except Exception as exc:
            log.warning("Auto-eject failed for %s: %s", device, exc)
            self._log_message(f"Auto-eject failed: {exc}", ft.Colors.ORANGE)

    def _advance_orchestrate(
        self,
        results: list[RipResult],
        job: RipJob | None = None,
    ):
        """In orchestrate mode, store results and advance to next disc or finish."""
        if job is not None and not screen_lease_is_current(self.app, job.lease):
            return

        disc_number = job.disc_number if job is not None else self.app.state.get("_orchestrate_disc_number")
        disc_queue = list(job.disc_queue) if job is not None else self.app.state.get("disc_queue", [])
        current_idx = job.current_disc_idx if job is not None else self.app.state.get("current_disc_idx", 0)

        # Store results for this disc
        all_results = (
            dict(job.all_rip_results)
            if job is not None
            else dict(self.app.state.get("all_rip_results", {}))
        )
        all_results[disc_number] = results
        self.app.state["all_rip_results"] = all_results

        outcome = summarize_rip_results(results)
        if outcome.all_failed:
            errors = list(dict.fromkeys(
                result.error_message for result in results if result.error_message
            ))
            detail = "; ".join(errors) or "No selected title was ripped."
            self.app.state["_rip_failure"] = (
                f"Disc {disc_number} was not ripped: {detail}"
            )
            self.app.navigate("disc_swap")
            return

        self.app.state.pop("_rip_failure", None)

        # Track as ripped
        ripped = (
            set(job.ripped_discs)
            if job is not None
            else set(self.app.state.get("ripped_discs", set()))
        )
        if outcome.has_successes:
            ripped.add(disc_number)
        self.app.state["ripped_discs"] = ripped

        # Advance to next disc
        next_idx = current_idx + 1
        if next_idx < len(disc_queue):
            self.app.state["current_disc_idx"] = next_idx
            next_disc = disc_queue[next_idx]
            self.app.state["_orchestrate_disc_number"] = next_disc
            # Always route through disc_swap so the user confirms via
            # Scan that the drive really contains the next disc — even
            # if we think it's already loaded. The swap screen's scan
            # step verifies this and warns on mismatch.
            self.app.navigate("disc_swap")
        else:
            # All discs done
            self.app.navigate("orchestrate_done")

    def _on_progress(self, progress: RipProgress):
        """Callback from run_rip for progress updates."""
        if progress.max_val <= 0:
            return
        pct = progress.current * 100 // progress.max_val
        if pct == self._last_pct:
            return  # avoid excessive UI updates
        self._last_pct = pct

        self.progress_bar.value = pct / 100
        self.progress_pct.value = f"{pct}%"

        total_bytes = self._current_title_bytes
        if total_bytes > 0:
            done_bytes = total_bytes * pct // 100
            done_gb = done_bytes / (1024 ** 3)
            total_gb = total_bytes / (1024 ** 3)
            self.progress_size.value = f"{done_gb:.1f}/{total_gb:.1f} GB"

            elapsed = time.monotonic() - self._rip_start_time
            if elapsed > 1:
                speed_mbs = (done_bytes / (1024 ** 2)) / elapsed
                self.progress_speed.value = f"{speed_mbs:.0f} MB/s"
                if pct > 0 and speed_mbs > 0:
                    remaining_bytes = total_bytes - done_bytes
                    eta_secs = int(remaining_bytes / (speed_mbs * 1024 * 1024))
                    self.progress_eta.value = f"ETA {_format_eta(eta_secs)}"
                else:
                    self.progress_eta.value = "ETA ..."
            else:
                self.progress_speed.value = ""
                self.progress_eta.value = "ETA ..."

        self._update()

    def _log_message(self, message: str, color=None):
        """Append a message to the log."""
        self.log.controls.append(
            ft.Text(message, size=12, color=color or ft.Colors.GREY_300)
        )

    def _cancel(self, e):
        """Signal cancellation — terminates the active makemkvcon process."""
        self._cancel_event.set()
        self.cancel_btn.disabled = True
        self.cancel_btn.text = "Stopping..."
        self._update()

    def _update(self):
        """Push a page update from a background thread.

        page.update() called directly from a non-loop thread mutates state but
        doesn't flush to the Flutter client until something else wakes the
        event loop (e.g. the user moves the window). Scheduling via
        page.run_task() runs the update on Flet's own loop via
        asyncio.run_coroutine_threadsafe, which does trigger the flush.
        """
        async def _do_update():
            self.app.page.update()
        try:
            self.app.page.run_task(_do_update)
        except Exception:
            pass
