"""Selection screen - choose which titles to rip from the disc."""

import logging

import flet as ft

from riplex.config import get_rip_output
from riplex.disc.analysis import (
    analyze_disc,
    build_season_labels,
    detect_bonus_films,
    format_seconds,
    group_for_disc,
)
from riplex.disc.makemkv import DiscTitle

log = logging.getLogger(__name__)


def _format_size(size_bytes: int) -> str:
    """Format bytes as GB."""
    gb = size_bytes / (1024 ** 3)
    return f"{gb:.1f} GB"


class SelectionScreen:
    def __init__(self, app):
        self.app = app
        self.checkboxes: list[ft.Checkbox] = []

    def build(self) -> ft.Control:
        disc_info = self.app.state["disc_info"]
        top_tmdb_match = self.app.state["tmdb_match"]
        dvdcompare_discs = self.app.state.get("dvdcompare_discs", [])
        titles = disc_info.titles if disc_info else []

        # In orchestrate mode, use the explicit disc number from the queue
        orchestrate_disc_num = self.app.state.get("_orchestrate_disc_number")

        # Multi-work releases: swap in the per-group match so header,
        # rip output folder, and analyze_disc all reflect the work this
        # disc actually belongs to (Psych disc 1 → TV series match, not
        # the film group's match).
        disc_groups = self.app.state.get("disc_groups", []) or []
        current_group = group_for_disc(disc_groups, orchestrate_disc_num)
        tmdb_match = top_tmdb_match
        if current_group and current_group.tmdb_match is not None:
            tmdb_match = current_group.tmdb_match
        self._effective_tmdb_match = tmdb_match
        self._current_group = current_group

        # Debug: log release context
        log.info("=== Selection Screen ===")
        log.info("Volume label: %s", disc_info.disc_name if disc_info else None)
        log.info("dvdcompare_discs: %d discs in release", len(dvdcompare_discs))
        for d in dvdcompare_discs:
            ep_count = len(d.episodes) if hasattr(d, 'episodes') else 0
            ex_count = len(d.extras) if hasattr(d, 'extras') else 0
            log.info("  Disc %d: %d episodes, %d extras, format=%s",
                     d.number, ep_count, ex_count, getattr(d, 'disc_format', None))
        log.info("Live disc: %d titles", len(titles))
        if current_group:
            log.info("Current group: %s (kind=%s) match=%s",
                     current_group.label, current_group.kind,
                     getattr(tmdb_match, "title", None))

        # Build classification data from dvdcompare
        is_movie = tmdb_match.media_type == "movie" if tmdb_match else True
        # movie_runtime only applies to the top-level match; a per-group
        # TV match should ignore it. Film-group per-slot discs also
        # ignore it (detect_bonus_films handles those).
        if current_group and tmdb_match is not top_tmdb_match:
            movie_runtime = None
        else:
            movie_runtime = self.app.state.get("movie_runtime")

        # Use shared analyze_disc — same logic as CLI rip and orchestrate
        analysis = analyze_disc(
            disc_info, dvdcompare_discs,
            disc_number=orchestrate_disc_num,
            is_movie=is_movie,
            movie_runtime=movie_runtime,
        )
        self._analysis = analysis  # store for _start_rip
        rippable_indices = {t.index for t in analysis.rippable_titles}
        classifications = analysis.classifications

        log.info("Detected disc number: %s", analysis.disc_number)
        log.info("dvd_entries: %d, total_episode_runtime: %s, episode_count: %d",
                 len(analysis.dvd_entries), format_seconds(analysis.total_episode_runtime),
                 analysis.episode_count)
        for name, runtime, etype in analysis.dvd_entries:
            log.info("  %s: %s (%s)", etype, name, format_seconds(runtime))

        log.info("is_movie=%s, movie_runtime=%s", is_movie, format_seconds(movie_runtime) if movie_runtime else None)
        log.info("%d/%d titles recommended for rip:", len(rippable_indices), len(titles))
        for t in titles:
            marker = "RIP " if t.index in rippable_indices else "SKIP"
            log.info("  [%s] #%2d  %8s  %.1f GB  %s  %s",
                     marker, t.index, format_seconds(t.duration_seconds),
                     t.size_bytes/(1024**3), t.resolution, classifications[t.index])

        recommended_titles = [t.index for t in analysis.rippable_titles]
        debug_dir = self._save_selection_snapshot(recommended_titles, phase="selection")

        self.checkboxes = []
        title_rows = []

        for t in titles:
            is_recommended = t.index in rippable_indices
            classification = classifications.get(t.index, "")
            cb = ft.Checkbox(
                value=is_recommended,
                data=t.index,
            )
            self.checkboxes.append(cb)

            rec_badge = ft.Container(
                ft.Text("RIP", size=10, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                bgcolor=ft.Colors.GREEN_700,
                border_radius=4,
                padding=ft.Padding(left=6, top=2, right=6, bottom=2),
                visible=is_recommended,
            )
            skip_badge = ft.Container(
                ft.Text("SKIP", size=10, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                bgcolor=ft.Colors.RED_700,
                border_radius=4,
                padding=ft.Padding(left=6, top=2, right=6, bottom=2),
                visible=not is_recommended,
            )

            # Use classification as the display name (comes from dvdcompare matching)
            display_name = classification or t.filename or f"Title {t.index}"

            row = ft.Row(
                [
                    cb,
                    ft.Text(f"#{t.index}", width=30, size=12, color=ft.Colors.GREY_500),
                    ft.Text(format_seconds(t.duration_seconds), width=70, size=12),
                    ft.Text(_format_size(t.size_bytes), width=70, size=12),
                    ft.Text(t.resolution, width=90, size=12),
                    rec_badge,
                    skip_badge,
                    ft.Text(display_name, size=12, color=ft.Colors.GREY_300, expand=True),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
            title_rows.append(row)

        # Summary
        total_selected = sum(1 for cb in self.checkboxes if cb.value)
        total_size = sum(
            titles[i].size_bytes
            for i, cb in enumerate(self.checkboxes)
            if cb.value
        )

        self.summary_text = ft.Text(
            f"{total_selected} titles selected ({_format_size(total_size)})",
            size=14,
            weight=ft.FontWeight.BOLD,
        )

        # Header row
        header = ft.Row(
            [
                ft.Container(width=48),  # checkbox space
                ft.Text("#", width=30, size=11, color=ft.Colors.GREY_500, weight=ft.FontWeight.BOLD),
                ft.Text("Duration", width=70, size=11, color=ft.Colors.GREY_500, weight=ft.FontWeight.BOLD),
                ft.Text("Size", width=70, size=11, color=ft.Colors.GREY_500, weight=ft.FontWeight.BOLD),
                ft.Text("Resolution", width=90, size=11, color=ft.Colors.GREY_500, weight=ft.FontWeight.BOLD),
                ft.Text("", width=50),
                ft.Text("Name", size=11, color=ft.Colors.GREY_500, weight=ft.FontWeight.BOLD, expand=True),
            ],
            spacing=8,
        )

        # Wire up checkboxes to update summary
        for cb in self.checkboxes:
            cb.on_change = self._update_summary

        match_label = ""
        if tmdb_match:
            year_str = f" ({tmdb_match.year})" if tmdb_match.year else ""
            match_label = f"{tmdb_match.title}{year_str}"

        back_target = "disc_overview" if self.app.state.get("workflow") == "orchestrate" else "metadata"
        back_btn = ft.TextButton("Back", on_click=lambda _: self.app.navigate(back_target))
        start_btn = ft.ElevatedButton(
            "Start Rip",
            icon=ft.Icons.PLAY_ARROW,
            on_click=self._start_rip,
            style=ft.ButtonStyle(
                padding=ft.Padding(left=30, top=15, right=30, bottom=15),
                bgcolor=ft.Colors.GREEN_700,
            ),
        )

        # Disc number indicator for orchestrate mode
        disc_label = ""
        if self.app.state.get("workflow") == "orchestrate" and orchestrate_disc_num:
            disc_queue = self.app.state.get("disc_queue", [])
            queue_pos = disc_queue.index(orchestrate_disc_num) + 1 if orchestrate_disc_num in disc_queue else 0
            disc_label = f"Disc {orchestrate_disc_num} ({queue_pos}/{len(disc_queue)})"

        # Season chip (e.g. "Season 1, Disc 2") when the release page
        # groups discs by season — same chip we show on Disc Overview
        # and Insert Next Disc.
        season_label = ""
        if dvdcompare_discs and orchestrate_disc_num:
            season_label = build_season_labels(
                dvdcompare_discs,
                film_title=self.app.state.get("dvdcompare_film_title"),
            ).get(orchestrate_disc_num, "")

        disc_row_children: list[ft.Control] = []
        if disc_label:
            disc_row_children.append(
                ft.Text(disc_label, size=13, color=ft.Colors.BLUE_400,
                        weight=ft.FontWeight.BOLD),
            )
        if season_label:
            disc_row_children.append(ft.Container(
                ft.Text(season_label, size=11,
                        color=ft.Colors.LIGHT_BLUE_200,
                        weight=ft.FontWeight.BOLD),
                bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.LIGHT_BLUE_400),
                border_radius=4,
                padding=ft.Padding(left=6, top=2, right=6, bottom=2),
            ))
        disc_row = ft.Row(
            disc_row_children, spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ) if disc_row_children else ft.Container()

        # Detect multiple feature-length films on this disc (e.g. box-set
        # movie collections like Psych disc 31 with 3 TV-movie sequels).
        disc_num_for_films = orchestrate_disc_num or analysis.disc_number
        current_discs = (
            [d for d in dvdcompare_discs if d.number == disc_num_for_films]
            if disc_num_for_films else list(dvdcompare_discs)
        )
        bonus_films: list = []
        for d in current_discs:
            bonus_films.extend(detect_bonus_films(d))
        bonus_films_section = self._build_bonus_films_section(bonus_films)

        return ft.Column(
            [
                ft.Text("Select Titles to Rip", size=24, weight=ft.FontWeight.BOLD),
                ft.Text(match_label, size=14, color=ft.Colors.GREY_400) if match_label else ft.Container(),
                disc_row,
                ft.Text(
                    "Titles marked RIP are recommended based on dvdcompare data and "
                    "duration matching. Uncheck any you don't want. Titles marked SKIP "
                    "are duplicates, play-alls, or very short clips.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                bonus_films_section,
                ft.Text(
                    f"Debug files: {debug_dir}",
                    size=12,
                    color=ft.Colors.GREY_600,
                ) if debug_dir else ft.Container(),
                ft.Divider(height=20),
                header,
                ft.Column(title_rows, spacing=4, scroll=ft.ScrollMode.AUTO, expand=True),
                ft.Divider(height=10),
                self.summary_text,
                ft.Container(height=10),
                ft.Row([back_btn, start_btn]),
            ],
            spacing=10,
            expand=True,
        )

    def _update_summary(self, e):
        """Update the summary text when checkboxes change."""
        disc_info = self.app.state["disc_info"]
        titles = disc_info.titles if disc_info else []
        total_selected = sum(1 for cb in self.checkboxes if cb.value)
        total_size = sum(
            titles[i].size_bytes
            for i, cb in enumerate(self.checkboxes)
            if cb.value and i < len(titles)
        )
        self.summary_text.value = f"{total_selected} titles selected ({_format_size(total_size)})"
        self.app.page.update()

    def _build_bonus_films_section(self, bonus_films: list) -> ft.Control:
        """Render an alert card listing multiple feature-length films on this disc."""
        if not bonus_films:
            return ft.Container()
        rows = [
            ft.Row(
                [
                    ft.Icon(ft.Icons.MOVIE, size=16, color=ft.Colors.AMBER_300),
                    ft.Text(
                        f"{film.title}"
                        + (f"  ({format_seconds(film.runtime_seconds)})"
                           if film.runtime_seconds else ""),
                        size=13, color=ft.Colors.AMBER_100,
                    ),
                ],
                spacing=6,
            )
            for film in bonus_films
        ]
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.WARNING_AMBER, color=ft.Colors.AMBER_400),
                            ft.Text(
                                f"Multi-film disc detected — {len(bonus_films)} feature-length film(s)",
                                size=14, weight=ft.FontWeight.BOLD,
                                color=ft.Colors.AMBER_300,
                            ),
                        ],
                        spacing=8,
                    ),
                    *rows,
                    ft.Text(
                        "Per-film organization (separate Plex folders) is not yet "
                        "wired up. For now all rips land in one disc folder — move them "
                        "manually after ripping.",
                        size=12, color=ft.Colors.GREY_400,
                    ),
                ],
                spacing=4,
            ),
            padding=12,
            border=ft.Border.all(1, ft.Colors.AMBER_700),
            border_radius=6,
            bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.AMBER_700),
        )

    def _start_rip(self, e):
        """Collect selected titles and proceed to rip."""
        selected = [cb.data for cb in self.checkboxes if cb.value]
        if not selected:
            return

        self.app.state["selected_titles"] = selected

        output_dir = self._build_output_dir()
        self.app.state["output_dir"] = output_dir

        # Save early snapshot at selection phase (before rip starts)
        self._save_selection_snapshot(selected, phase="selection")

        self.app.navigate("progress")

    def _build_output_dir(self):
        """Build the per-disc rip output directory for the current selection.

        Prefers the current disc's DiscGroup match over the top-level
        state["tmdb_match"] so multi-work releases (e.g. Psych TV series
        + bonus films disc) rip each work under its own folder.
        """
        tmdb_match = getattr(self, "_effective_tmdb_match", None) \
            or self.app.state.get("tmdb_match")
        if tmdb_match:
            from riplex.manifest import build_rip_path

            disc_num = self._analysis.disc_number if hasattr(self, "_analysis") else None
            return build_rip_path(tmdb_match.title, tmdb_match.year or 0, disc_number=disc_num)

        from pathlib import Path

        rip_output = get_rip_output()
        return Path(rip_output) / self.app.state["title"]

    def _debug_root_for_output_dir(self, output_dir):
        """Return the title-level root whose ``_riplex`` folder holds debug files."""
        if output_dir.name.lower().startswith("disc "):
            return output_dir.parent
        return output_dir

    def _save_selection_snapshot(self, selected_titles: list[int], *, phase: str):
        """Save snapshot with disc info and metadata before rip starts."""
        from pathlib import Path
        from riplex.snapshot import get_debug_dir, save_rip_manifest, save_rip_snapshot

        try:
            output_dir = Path(self._build_output_dir())
            debug_dir = get_debug_dir(self._debug_root_for_output_dir(output_dir))
            disc_info = self.app.state.get("disc_info")
            tmdb_match = getattr(self, "_effective_tmdb_match", None) \
                or self.app.state.get("tmdb_match")
            discs = self.app.state.get("dvdcompare_discs", [])
            release = self.app.state.get("release")
            analysis = getattr(self, "_analysis", None)

            canonical = tmdb_match.title if tmdb_match else ""
            year = tmdb_match.year if tmdb_match else None
            is_movie = getattr(tmdb_match, "media_type", "movie") != "tv"
            if tmdb_match is not self.app.state.get("tmdb_match"):
                # Per-group match: TV series should not carry the
                # top-level (film) movie_runtime through.
                movie_runtime = None if not is_movie else self.app.state.get("movie_runtime")
            else:
                movie_runtime = self.app.state.get("movie_runtime")

            save_rip_snapshot(
                debug_dir, disc_info,
                canonical=canonical, year=year, is_movie=is_movie,
                movie_runtime=movie_runtime,
                release_name=release.name if release else "",
                discs=discs,
                selected_titles=selected_titles,
                rippable_titles=[t.index for t in analysis.rippable_titles] if analysis else [],
                classifications=analysis.classifications if analysis else {},
                phase=phase,
            )
            save_rip_manifest(
                debug_dir,
                self._build_selection_manifest(
                    disc_info=disc_info,
                    canonical=canonical,
                    year=year,
                    is_movie=is_movie,
                    release_name=release.name if release else "",
                    selected_titles=selected_titles,
                    analysis=analysis,
                ),
            )
            self.app.state["debug_dir"] = str(debug_dir)
            log.info("Wrote selection snapshot to %s", debug_dir)
            return str(debug_dir)
        except Exception as exc:
            log.warning("Failed to write selection snapshot: %s", exc)
            return ""

    def _build_selection_manifest(
        self,
        *,
        disc_info,
        canonical: str,
        year: int | None,
        is_movie: bool,
        release_name: str,
        selected_titles: list[int],
        analysis,
    ) -> dict:
        """Build a debug-only manifest from the current selection table."""
        selected_set = set(selected_titles)
        rippable_set = {t.index for t in analysis.rippable_titles} if analysis else set()
        classifications = analysis.classifications if analysis else {}
        return {
            "phase": "selection",
            "title": canonical,
            "year": year,
            "type": "movie" if is_movie else "tv",
            "disc_number": analysis.disc_number if analysis else None,
            "disc_label": disc_info.disc_name if disc_info else "",
            "release": release_name,
            "files": [
                {
                    "filename": t.filename,
                    "title_index": t.index,
                    "duration": t.duration_seconds,
                    "resolution": t.resolution,
                    "size_bytes": t.size_bytes,
                    "classification": classifications.get(t.index, ""),
                    "recommended": t.index in rippable_set,
                    "selected": t.index in selected_set,
                    "playlist": t.playlist,
                    "segment_count": t.segment_count,
                    "segment_map": t.segment_map,
                    "stream_count": t.stream_count,
                    "audio_tracks": list(t.audio_tracks or []),
                    "subtitle_tracks": list(t.subtitle_tracks or []),
                }
                for t in (disc_info.titles if disc_info else [])
            ],
        }
