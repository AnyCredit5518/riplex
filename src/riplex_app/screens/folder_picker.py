"""Folder picker screen - select and scan a folder of MKV rips."""

import logging
import re
import threading
from pathlib import Path

import flet as ft

log = logging.getLogger(__name__)

from riplex.config import get_rip_output
from riplex.detect import TitleGroup, detect_format, detect_organize_layout
from riplex.manifest import build_scanned_from_manifests
from riplex.scanner import scan_folder
from riplex.snapshot import load_organized_marker
from riplex.title import infer_title_from_scanned, parse_season_number


_SEASON_ONLY_FOLDER_RE = re.compile(r"^Season\s+\d+$", re.IGNORECASE)


def _read_title_and_season_from_manifests(
    folder: Path,
) -> tuple[str | None, int | None, str | None]:
    """Return ``(title, season, media_type)`` from this folder's rip manifests.

    Each disc subfolder's ``_rip_manifest.json`` carries the canonical
    title and media type set at rip time; the season isn't stored
    directly, but the enclosing folder's name is (via ``build_rip_path``).
    ``media_type`` is ``"tv"``, ``"movie"``, or ``None`` when unknown.
    Returns ``(None, None, None)`` for organize sources that weren't
    produced by riplex.
    """
    import json as _json

    for sub in sorted(folder.iterdir() if folder.exists() else []):
        if not sub.is_dir():
            continue
        manifest_path = sub / "_rip_manifest.json"
        if not manifest_path.exists():
            continue
        try:
            data = _json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        title = (data.get("title") or "").strip() or None
        media_type = data.get("type") if data.get("type") in ("tv", "movie") else None
        season: int | None = None
        if media_type == "tv":
            # Nested layout puts rips at ``<title>/Season NN/Disc N``;
            # legacy flat layout writes to ``<title>/Disc N`` and the
            # season isn't recoverable from the manifest alone. Try
            # the source folder's name first, then its parent's, to
            # cover both cases regardless of which level the user
            # selected in the picker.
            season = (
                parse_season_number(folder.name)
                or parse_season_number(folder.parent.name if folder.parent else "")
            )
        return title, season, media_type
    return None, None, None


class FolderPickerScreen:
    def __init__(self, app):
        self.app = app

    def build(self) -> ft.Control:
        batch_groups = self.app.state.pop("_batch_groups", None)
        if batch_groups is not None:
            return self._build_batch_groups_view(batch_groups)

        # Check for scan results from background thread
        scan_result = self.app.state.pop("_scan_result", None)
        if scan_result is not None:
            return self._build_results_view(scan_result)

        scan_error = self.app.state.pop("_scan_error", None)
        if scan_error:
            return self._build_error_view(scan_error)

        # If we already have scanned data (e.g. navigating back from metadata),
        # go straight to the results view without rescanning.
        existing_scanned = self.app.state.get("scanned")
        if existing_scanned:
            return self._build_results_view(existing_scanned)

        # Initial view: folder selection
        self.folder_field = ft.TextField(
            label="Folder path",
            hint_text=r"e.g. D:\Rips\My Movie (2024)",
            expand=True,
            on_submit=self._scan,
        )

        return ft.Column(
            [
                ft.Text("Organize Rips", size=24, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "Select a folder containing MKV rips. This can be a single folder "
                    "of MKV files or a multi-disc layout with Disc 1, Disc 2 subfolders.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                ft.Divider(height=20),
                ft.Row(
                    [
                        self.folder_field,
                        ft.IconButton(
                            ft.Icons.FOLDER_OPEN,
                            on_click=self._browse,
                            tooltip="Browse",
                        ),
                    ],
                    spacing=8,
                ),
                ft.Container(expand=True),
                ft.Row([
                    ft.TextButton("Back", on_click=lambda _: self.app.navigate("welcome")),
                    ft.ElevatedButton(
                        "Scan",
                        icon=ft.Icons.SEARCH,
                        on_click=self._scan,
                        style=ft.ButtonStyle(padding=ft.Padding(left=30, top=15, right=30, bottom=15)),
                    ),
                ]),
            ],
            spacing=10,
            expand=True,
        )

    def _browse(self, e):
        """Open native folder picker dialog via tkinter."""
        log.debug("_browse clicked")

        def _pick():
            try:
                import tkinter as tk
                from tkinter import filedialog
            except ModuleNotFoundError:
                log.warning("tkinter not available; user must type path manually")
                self.folder_field.hint_text = "Type the path manually (brew install python-tk@3.12 to enable folder picker)"
                self.app.page.update()
                return

            try:
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                initial = get_rip_output() or ""
                log.debug("opening askdirectory, initial=%r", initial)
                path = filedialog.askdirectory(
                    title="Select MKV rip folder",
                    initialdir=initial or None,
                )
                root.destroy()
                log.debug("askdirectory returned %r", path)
                if path:
                    self.folder_field.value = path
                    self.app.page.update()
                    log.debug("folder_field updated to %r", path)
            except Exception:
                log.exception("_browse error")

        threading.Thread(target=_pick, daemon=True).start()

    def _scan(self, e):
        """Validate folder and start scanning."""
        path = self.folder_field.value.strip() if self.folder_field.value else ""
        if not path or not Path(path).is_dir():
            self.folder_field.error_text = "Please select a valid folder."
            self.folder_field.update()
            return
        self.folder_field.error_text = None

        folder = Path(path)
        self.app.state["source_folder"] = folder

        layout = detect_organize_layout(folder)
        if layout.mode == "batch":
            self.app.state["_batch_groups"] = layout.groups
            self.app.navigate("folder_picker")
            return
        if layout.mode == "empty":
            self.folder_field.error_text = "No MKV files found in that folder."
            self.folder_field.update()
            return

        # Fast path: if every disc subfolder has a _rip_manifest.json,
        # load metadata from the manifest instead of running ffprobe.
        if self._has_complete_manifests(folder):
            log.info("loading scan from rip manifests in %s", folder)
            try:
                scanned = build_scanned_from_manifests(folder)
            except Exception as exc:
                log.exception("manifest load failed; falling back to ffprobe")
                scanned = None
            if scanned:
                self.app.state["_scan_from_manifest"] = True
                self.app.state["_scan_result"] = scanned
                self.app.navigate("folder_picker")
                return

        self.app.state["_scan_from_manifest"] = False
        self._start_ffprobe_scan(folder)

    def _has_complete_manifests(self, folder: Path) -> bool:
        subfolders_with_mkvs = [
            c for c in folder.iterdir()
            if c.is_dir() and any(c.glob("*.mkv"))
        ]
        if not subfolders_with_mkvs:
            return False
        return all((c / "_rip_manifest.json").exists() for c in subfolders_with_mkvs)

    def _rescan_with_ffprobe(self, e):
        """User clicked the 'Rescan with ffprobe' banner button."""
        folder = self.app.state.get("source_folder")
        if not folder:
            return
        # Clear any cached scan and force a fresh ffprobe scan.
        self.app.state.pop("scanned", None)
        self.app.state.pop("_scan_result", None)
        self.app.state["_scan_from_manifest"] = False
        self._start_ffprobe_scan(folder)

    def _start_ffprobe_scan(self, folder: Path):
        # Show scanning state with progress
        self._progress_text = ft.Text("Discovering files...", size=14)
        self._progress_bar = ft.ProgressBar(width=400)
        self._progress_detail = ft.Text("", size=12, color=ft.Colors.GREY_500)

        self.app.page.controls.clear()
        self.app.page.controls.append(
            ft.Column(
                [
                    ft.Text("Organize Rips", size=24, weight=ft.FontWeight.BOLD),
                    ft.Divider(height=20),
                    self._progress_text,
                    self._progress_bar,
                    self._progress_detail,
                    ft.Container(expand=True),
                    ft.TextButton("Back", on_click=lambda _: self.app.navigate("welcome")),
                ],
                spacing=10,
                expand=True,
            )
        )
        self.app.page.update()

        threading.Thread(target=self._do_scan, args=(folder,), daemon=True).start()

    def _do_scan(self, folder: Path):
        """Run ffprobe scan in background."""
        log.info("scanning %s", folder)

        def _on_discover(total: int):
            log.debug("scan discovered %d file(s)", total)

            async def _update():
                self._progress_text.value = f"Probing file 1 of {total}..."
                self._progress_bar.value = 0
                self._progress_detail.value = "This can take a moment for large files"
                self.app.page.update()

            self.app.page.run_task(_update)

        def _on_progress(current: int, total: int, filename: str):
            log.debug("scan progress %d/%d %s", current, total, filename)

            async def _update():
                self._progress_text.value = f"Probing file {current} of {total}..."
                self._progress_bar.value = current / total if total else 0
                self._progress_detail.value = filename
                self.app.page.update()

            self.app.page.run_task(_update)

        try:
            scanned = scan_folder(folder, on_progress=_on_progress, on_discover=_on_discover)
            log.info("scan complete: %d disc(s)", len(scanned))
            self.app.state["_scan_result"] = scanned
        except Exception as exc:
            log.exception("scan failed")
            self.app.state["_scan_error"] = str(exc)

        async def _nav():
            self.app.navigate("folder_picker")

        self.app.page.run_task(_nav)

    def _build_batch_groups_view(self, groups: list[TitleGroup]) -> ft.Control:
        rows: list[ft.Control] = []
        for group in groups:
            label = group.title
            if group.season_number is not None:
                label = f"{label} Season {group.season_number}"
            folder_list = ", ".join(folder.name for folder in group.folders)
            rows.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(label, size=14, weight=ft.FontWeight.BOLD),
                            ft.Text(folder_list, size=12, color=ft.Colors.GREY_500),
                            ft.Row(
                                [
                                    ft.ElevatedButton(
                                        "Open",
                                        icon=ft.Icons.ARROW_FORWARD,
                                        on_click=lambda _, g=group: self._open_group(g),
                                    )
                                ]
                            ),
                        ],
                        spacing=6,
                    ),
                    padding=12,
                    border=ft.Border.all(1, ft.Colors.GREY_800),
                    border_radius=8,
                )
            )

        return ft.Column(
            [
                ft.Text("Organize Rips", size=24, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "This folder contains multiple organize groups. Pick the one you want to process.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                ft.Divider(height=20),
                ft.Column(rows, spacing=10, scroll=ft.ScrollMode.AUTO),
                ft.Container(expand=True),
                ft.TextButton("Back", on_click=lambda _: self.app.navigate("welcome")),
            ],
            spacing=10,
            expand=True,
        )

    def _open_group(self, group: TitleGroup) -> None:
        if len(group.folders) != 1:
            # Multi-folder groups still need a shared library batch scanner.
            self.app.state["_scan_error"] = (
                "This organize group spans multiple folders. Pick a season folder directly for now."
            )
            self.app.navigate("folder_picker")
            return
        folder = group.folders[0]
        self.app.state["source_folder"] = folder
        self.app.state["title"] = group.title
        if group.season_number is not None:
            self.app.state["season_number"] = group.season_number
        else:
            self.app.state.pop("season_number", None)

        if self._has_complete_manifests(folder):
            try:
                scanned = build_scanned_from_manifests(folder)
            except Exception:
                log.exception("manifest load failed; falling back to ffprobe")
                scanned = None
            if scanned:
                self.app.state["_scan_from_manifest"] = True
                self.app.state["_scan_result"] = scanned
                self.app.navigate("folder_picker")
                return

        self.app.state["_scan_from_manifest"] = False
        self._start_ffprobe_scan(folder)

    def _build_results_view(self, scanned) -> ft.Control:
        """Show scan results and let user confirm/edit title."""
        self.app.state["scanned"] = scanned

        total_files = sum(len(d.files) for d in scanned)
        disc_format = detect_format(scanned) or "unknown"

        # Check for organized marker
        marker = load_organized_marker(self.app.state["source_folder"])
        marker_banner = []
        if marker:
            when = marker.organized_at[:10] if marker.organized_at else "unknown date"
            marker_banner = [
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.INFO_OUTLINE, color=ft.Colors.AMBER_400, size=18),
                        ft.Text(
                            f"This folder was already organized on {when} "
                            f"as \"{marker.title}\". Continue anyway?",
                            size=13,
                            color=ft.Colors.AMBER_400,
                        ),
                    ], spacing=8),
                    bgcolor=ft.Colors.with_opacity(0.1, ft.Colors.AMBER),
                    padding=12,
                    border_radius=8,
                ),
            ]

        # Banner shown when the scan came from rip manifests (instant load).
        manifest_banner = []
        if self.app.state.get("_scan_from_manifest"):
            manifest_banner = [
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.BOLT, color=ft.Colors.GREEN_400, size=18),
                        ft.Text(
                            "Loaded instantly from rip manifests (no ffprobe needed).",
                            size=13,
                            color=ft.Colors.GREEN_400,
                            expand=True,
                        ),
                        ft.TextButton(
                            "Rescan with ffprobe",
                            icon=ft.Icons.REFRESH,
                            on_click=self._rescan_with_ffprobe,
                        ),
                    ], spacing=8),
                    bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.GREEN),
                    padding=12,
                    border_radius=8,
                ),
            ]

        # Build disc summary rows
        disc_rows = []
        for d in scanned:
            has_4k = any(f.max_width >= 3840 for f in d.files)
            res_label = "4K" if has_4k else "1080p"
            disc_rows.append(
                ft.Text(f"  {d.folder_name}/  ({len(d.files)} files, {res_label})", size=13)
            )

        # Infer title from folder name or MKV tags. When the folder
        # holds riplex-produced rips, the ``_rip_manifest.json`` files
        # each carry the canonical show/movie title and (for TV) the
        # season number — trust those over folder-name heuristics
        # because they're what the rip step actually recorded.
        source_folder: Path = self.app.state["source_folder"]
        manifest_title, manifest_season, manifest_type = _read_title_and_season_from_manifests(source_folder)
        if manifest_title:
            inferred = manifest_title
        else:
            inferred = infer_title_from_scanned(scanned)
            if not inferred:
                # Walk up past a leading ``Season NN`` folder — a user
                # who points at ``Psych (2006)/Season 01/`` should still
                # get ``Psych`` as the detected title, not ``Season 01``.
                folder_name = source_folder.name
                if _SEASON_ONLY_FOLDER_RE.match(folder_name) and source_folder.parent:
                    folder_name = source_folder.parent.name
                m = re.match(r"^(.+?)\s*\(\d{4}\)$", folder_name)
                inferred = m.group(1).strip() if m else folder_name

        self.title_field = ft.TextField(
            label="Title",
            value=inferred,
            width=500,
        )
        if manifest_season is not None:
            inferred_season = manifest_season
        else:
            inferred_season = (
                parse_season_number(source_folder.name)
                or parse_season_number(source_folder.parent.name if source_folder.parent else "")
            )
        self.season_field = ft.TextField(
            label="Season number",
            value=str(inferred_season) if inferred_season is not None else "",
            width=240,
            hint_text="e.g. 6",
            helper_text="Leave blank for movies.",
        )

        # Source-of-truth hint for the title/season block. When the
        # values came from a rip manifest we're confident; otherwise
        # they're best-guess from folder/MKV heuristics.
        if manifest_title:
            detection_hint = ft.Row([
                ft.Icon(ft.Icons.VERIFIED_OUTLINED, color=ft.Colors.GREEN_400, size=16),
                ft.Text("From rip manifest", size=12, color=ft.Colors.GREEN_400),
            ], spacing=6)
        else:
            detection_hint = ft.Row([
                ft.Icon(ft.Icons.EDIT_NOTE, color=ft.Colors.AMBER_400, size=16),
                ft.Text(
                    "Guessed from folder name — please verify",
                    size=12,
                    color=ft.Colors.AMBER_400,
                ),
            ], spacing=6)

        # Media-type badge for the disc summary. Only shown when we
        # know it (manifest-backed rips); otherwise TMDb decides later.
        type_label = {"tv": "TV", "movie": "Movie"}.get(manifest_type or "", "")
        summary_suffix = f", {type_label}" if type_label else ""

        # Movies never take a season — hide the field entirely when
        # the manifest says movie. Non-manifest sources keep the field
        # visible because we don't know the type yet.
        show_season_field = manifest_type != "movie"

        return ft.Column(
            [
                ft.Text("Organize Rips", size=24, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "Review the scan results below. Confirm or edit the title, "
                    "then proceed to look up metadata.",
                    size=13,
                    color=ft.Colors.GREY_500,
                ),
                ft.Divider(height=20),
                *manifest_banner,
                *marker_banner,
                ft.Text(
                    f"Scanned {len(scanned)} disc{'s' if len(scanned) != 1 else ''}, "
                    f"{total_files} files ({disc_format}{summary_suffix})",
                    size=14,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Column(disc_rows, spacing=2),
                ft.Container(height=10),
                detection_hint,
                ft.Text("Detected title:", size=14),
                self.title_field,
                *(
                    [ft.Text("Season number:", size=14), self.season_field]
                    if show_season_field
                    else []
                ),
                ft.Container(expand=True),
                ft.Row([
                    ft.TextButton("Back", on_click=lambda _: self.app.navigate("welcome")),
                    ft.ElevatedButton(
                        "Next",
                        icon=ft.Icons.ARROW_FORWARD,
                        on_click=self._next,
                        style=ft.ButtonStyle(padding=ft.Padding(left=30, top=15, right=30, bottom=15)),
                    ),
                ]),
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def _build_error_view(self, error: str) -> ft.Control:
        """Show scan error."""
        return ft.Column(
            [
                ft.Text("Organize Rips", size=24, weight=ft.FontWeight.BOLD),
                ft.Divider(height=20),
                ft.Text(f"Scan failed: {error}", size=14, color=ft.Colors.ORANGE),
                ft.Container(expand=True),
                ft.TextButton("Back", on_click=lambda _: self.app.navigate("welcome")),
            ],
            spacing=10,
            expand=True,
        )

    def _next(self, e):
        """Store title and proceed to metadata lookup."""
        title = self.title_field.value.strip()
        if not title:
            self.title_field.error_text = "Title is required."
            self.title_field.update()
            return
        season_text = self.season_field.value.strip() if self.season_field.value else ""
        if season_text:
            if not season_text.isdigit() or int(season_text) < 0:
                self.season_field.error_text = "Enter a valid season number."
                self.season_field.update()
                return
            self.app.state["season_number"] = int(season_text)
            self.season_field.error_text = None
        else:
            self.app.state.pop("season_number", None)
        self.app.state["title"] = title
        self.app.navigate("metadata")
