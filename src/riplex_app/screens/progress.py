"""Progress screen - shows rip progress for each title."""

import logging
import threading
import time
from pathlib import Path

import flet as ft

from riplex.disc.makemkv import run_rip, RipProgress, RipResult
from riplex.snapshot import copy_debug_log, get_debug_dir, save_rip_snapshot

log = logging.getLogger(__name__)


class ProgressScreen:
    def __init__(self, app):
        self.app = app
        self.cancelled = False

    def build(self) -> ft.Control:
        self.cancelled = False
        selected = self.app.state["selected_titles"]
        disc_info = self.app.state["disc_info"]
        titles = disc_info.titles if disc_info else []

        # Map index to title for display
        self.title_map = {t.index: t for t in titles}
        self.total_count = len(selected)
        self.completed_count = 0

        self.overall_text = ft.Text(
            f"Ripping 0/{self.total_count} titles...",
            size=16,
            weight=ft.FontWeight.BOLD,
        )
        self.current_title_text = ft.Text("Preparing...", size=14, color=ft.Colors.GREY_400)
        self.progress_bar = ft.ProgressBar(width=700, value=0)
        self.progress_detail = ft.Text("0%", size=12, color=ft.Colors.GREY_500)
        self.log = ft.ListView(spacing=4, height=250, auto_scroll=True)
        self.cancel_btn = ft.ElevatedButton(
            "Cancel",
            icon=ft.Icons.CANCEL,
            on_click=self._cancel,
            style=ft.ButtonStyle(bgcolor=ft.Colors.RED_700),
        )

        self.content = ft.Column(
            [
                ft.Text("Ripping", size=24, weight=ft.FontWeight.BOLD),
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
                self.progress_detail,
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
        threading.Thread(target=self._run_rips, daemon=True).start()

        return self.content

    def _run_rips(self):
        """Rip all selected titles sequentially."""
        selected = self.app.state["selected_titles"]
        output_dir = self.app.state["output_dir"]
        makemkvcon = self.app.state["makemkvcon"]
        drive = self.app.state["drive"]
        results: list[RipResult] = []

        for i, title_idx in enumerate(selected):
            if self.cancelled:
                self._log_message("Cancelled by user.", ft.Colors.ORANGE)
                break

            title = self.title_map.get(title_idx)
            title_name = title.name or title.filename if title else f"Title {title_idx}"
            size_gb = (title.size_bytes / (1024 ** 3)) if title else 0

            self.completed_count = i
            self.overall_text.value = f"Ripping {i + 1}/{self.total_count} titles..."
            self.current_title_text.value = f"Title #{title_idx}: {title_name} ({size_gb:.1f} GB)"
            self.progress_bar.value = 0
            self.progress_detail.value = "Starting..."
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
        self.app.state["rip_results"] = results
        self.overall_text.value = f"Complete: {sum(1 for r in results if r.success)}/{len(results)} successful"
        self.current_title_text.value = ""
        self.progress_bar.value = 1.0
        self.progress_detail.value = "100%"
        self.cancel_btn.visible = False
        self._update()

        # Write debug snapshots
        self._write_snapshots(results)

        # Brief pause then navigate to done
        time.sleep(1)
        self.app.navigate("done")

    def _write_snapshots(self, results: list[RipResult]):
        """Write debug snapshots to _riplex/ folder after rip."""
        output_dir = self.app.state.get("output_dir")
        if not output_dir:
            return
        try:
            debug_dir = get_debug_dir(Path(output_dir).parent)

            disc_info = self.app.state.get("disc_info")
            tmdb_match = self.app.state.get("tmdb_match")
            discs = self.app.state.get("dvdcompare_discs", [])

            canonical = tmdb_match.title if tmdb_match else ""
            year = tmdb_match.year if tmdb_match else None
            is_movie = getattr(tmdb_match, "media_type", "movie") != "tv"
            movie_runtime = getattr(tmdb_match, "runtime_seconds", None) if is_movie else None

            save_rip_snapshot(
                debug_dir, disc_info,
                canonical=canonical, year=year, is_movie=is_movie,
                movie_runtime=movie_runtime,
                discs=discs,
                ripped_titles=[r.title_index for r in results if r.success],
            )
            copy_debug_log(debug_dir)
            self.app.state["debug_dir"] = str(debug_dir)
            log.info("Wrote debug snapshots to %s", debug_dir)
        except Exception as exc:
            log.warning("Failed to write debug snapshots: %s", exc)

    def _on_progress(self, progress: RipProgress):
        """Callback from run_rip for progress updates."""
        if progress.total > 0:
            pct = progress.current / progress.total
            self.progress_bar.value = pct
            self.progress_detail.value = f"{pct * 100:.0f}%"
            self._update()

    def _log_message(self, message: str, color=None):
        """Append a message to the log."""
        self.log.controls.append(
            ft.Text(message, size=12, color=color or ft.Colors.GREY_300)
        )

    def _cancel(self, e):
        """Set cancel flag (rip in progress will finish current title)."""
        self.cancelled = True
        self.cancel_btn.disabled = True
        self.cancel_btn.text = "Cancelling..."
        self._update()

    def _update(self):
        """Safe page update."""
        try:
            self.app.page.update()
        except Exception:
            pass
