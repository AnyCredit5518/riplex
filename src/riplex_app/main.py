"""Riplex GUI - Flet-based companion app for riplex."""

import logging
import os
import sys
import threading
import traceback as tb_module
import webbrowser
from pathlib import Path

try:
    import flet as ft
except ModuleNotFoundError as exc:  # pragma: no cover — only triggers without [gui] extra
    if exc.name == "flet":
        sys.stderr.write(
            "\nriplex-ui requires the GUI dependencies, which are not installed.\n\n"
            "If you installed riplex with pipx, run:\n"
            "    pipx install --force 'riplex[gui]'\n"
            "or, to add the GUI to an existing install:\n"
            "    pipx inject riplex flet\n\n"
            "If you installed with pip, run:\n"
            "    pip install 'riplex[gui]'\n\n"
            "See https://github.com/AnyCredit5518/riplex#installation for details.\n"
        )
        sys.exit(1)
    raise

log = logging.getLogger("riplex_app")

from riplex_app.screens.welcome import WelcomeScreen
from riplex_app.screens.disc_detection import DiscDetectionScreen
from riplex_app.screens.metadata import MetadataScreen
from riplex_app.screens.season_select import SeasonSelectScreen
from riplex_app.screens.release import ReleaseScreen
from riplex_app.screens.selection import SelectionScreen
from riplex_app.screens.progress import ProgressScreen
from riplex_app.screens.done import DoneScreen
from riplex_app.screens.folder_picker import FolderPickerScreen
from riplex_app.screens.organize_preview import OrganizePreviewScreen
from riplex_app.screens.organize_done import OrganizeDoneScreen
from riplex_app.screens.disc_overview import DiscOverviewScreen
from riplex_app.screens.disc_swap import DiscSwapScreen
from riplex_app.screens.orchestrate_done import OrchestrateDoneScreen
from riplex_app.screens.update import UpdateScreen


class RiplexApp:
    """Main application controller managing wizard navigation."""

    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "riplex-ui"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.window.width = 900
        self.page.window.height = 650
        self.page.padding = 30

        # Shared state passed between screens
        self.state = {
            # Workflow
            "workflow": None,      # "orchestrate" | "organize"
            # Rip workflow
            "drive": None,        # DriveInfo
            "disc_info": None,    # DiscInfo
            "title": "",          # detected/overridden title
            "tmdb_match": None,   # selected TMDb result
            "movie_runtime": None,# TMDb movie runtime in seconds
            "show_detail": None,  # TMDb ShowDetail (for TV): full season/episode lists
            "release": None,      # selected dvdcompare release
            "selected_discs": [], # disc numbers to rip
            "selected_titles": [],# title indices to rip
            "output_dir": None,   # Path for rip output
            "rip_results": [],    # list of RipResult
            "makemkvcon": None,   # Path to exe
            # Orchestrate workflow
            "disc_queue": [],           # ordered list of disc numbers to rip
            "current_disc_idx": 0,      # index into disc_queue
            "ripped_discs": set(),      # disc numbers already ripped (from manifests)
            "all_rip_results": {},      # dict: disc_number -> list[RipResult]
            # Organize workflow
            "source_folder": None,  # Path — folder to organize
            "scanned": None,        # list[ScannedDisc] from scanner
            "organize_plan": None,  # OrganizePlan from build_organize_plan
            "organize_results": None,  # execution results
            "dvdcompare_discs": [],   # list[PlannedDisc]
        }

        self.screens = {
            "welcome": WelcomeScreen(self),
            "disc_detection": DiscDetectionScreen(self),
            "metadata": MetadataScreen(self),
            "season_select": SeasonSelectScreen(self),
            "release": ReleaseScreen(self),
            "selection": SelectionScreen(self),
            "progress": ProgressScreen(self),
            "done": DoneScreen(self),
            "folder_picker": FolderPickerScreen(self),
            "organize_preview": OrganizePreviewScreen(self),
            "organize_done": OrganizeDoneScreen(self),
            "disc_overview": DiscOverviewScreen(self),
            "disc_swap": DiscSwapScreen(self),
            "orchestrate_done": OrchestrateDoneScreen(self),
            "update": UpdateScreen(self),
        }

        self.navigate("welcome")

        # Install error handlers to surface a "Report Crash" dialog.
        self.page.on_error = self._on_page_error
        self._install_excepthooks()

    def navigate(self, screen_name: str):
        """Switch to a named screen."""
        log.info("navigate -> %s", screen_name)
        self._current_screen_name = screen_name
        self.page.controls.clear()
        screen = self.screens[screen_name]
        built = screen.build()
        # Every non-welcome screen gets a globally-injected Quit
        # button. We try to append it to the screen's own footer Row
        # so it sits alongside the screen-specific buttons; if the
        # screen doesn't end in a Row we fall back to wrapping the
        # built control so Quit anchors to the bottom regardless.
        if screen_name == "welcome":
            self.page.controls.append(built)
        else:
            quit_btn = ft.TextButton(
                "Quit",
                icon=ft.Icons.CLOSE,
                on_click=self._confirm_quit,
            )
            if _append_to_footer_row(built, quit_btn):
                # Successfully merged into the screen's existing footer
                # row -- ensure the root control still claims all
                # available vertical space so the footer stays anchored.
                try:
                    built.expand = True
                except AttributeError:
                    pass
                self.page.controls.append(built)
            else:
                try:
                    built.expand = True
                except AttributeError:
                    pass
                self.page.controls.append(
                    ft.Column(
                        [
                            built,
                            ft.Row(
                                [quit_btn],
                                alignment=ft.MainAxisAlignment.END,
                            ),
                        ],
                        spacing=0,
                        expand=True,
                    )
                )
        self.page.floating_action_button = ft.FloatingActionButton(
            icon=ft.Icons.BUG_REPORT,
            tooltip="Report a Bug",
            on_click=self._open_bug_report,
            mini=True,
            bgcolor=ft.Colors.GREY_800,
        )
        self.page.appbar = None
        self.page.update()

        # Kick off background checks on welcome screen
        if screen_name == "welcome":
            screen.check_for_updates()
            screen.check_connectivity()

    def _confirm_quit(self, _e):
        """Show a small confirmation dialog before dropping back to welcome.

        Guards against accidental clicks that would drop the user out
        of a mid-workflow session (they can still reach welcome via
        the confirm button).
        """
        def do_quit(_e):
            dialog.open = False
            self.page.update()
            self.navigate("welcome")

        def cancel(_e):
            dialog.open = False
            self.page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Return to Welcome?"),
            content=ft.Text(
                "This ends the current workflow and returns to the start. "
                "In-progress rips continue in the background."
            ),
            actions=[
                ft.TextButton("Cancel", on_click=cancel),
                ft.ElevatedButton("Return to Welcome", on_click=do_quit),
            ],
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _open_bug_report(self, e):
        """Open a pre-filled GitHub bug report in the browser."""
        from riplex_app.bug_report import build_bug_report_url

        url = build_bug_report_url(self.state)
        log.info("Opening bug report: %s", url)
        webbrowser.open(url)

    # ------------------------------------------------------------------
    # Crash handling
    # ------------------------------------------------------------------
    def _on_page_error(self, e):
        """Flet calls this for unhandled exceptions in event handlers."""
        # Flet passes ControlEvent with `data` containing the traceback string.
        traceback_text = getattr(e, "data", None) or str(e)
        # Best-effort parse of exception type/message from the last line.
        exc_type, exc_message = _parse_exception_summary(traceback_text)
        log.error("page.on_error: %s: %s", exc_type, exc_message)
        log.error("Traceback:\n%s", traceback_text)
        self._show_crash_dialog(exc_type, exc_message, traceback_text)

    def _install_excepthooks(self):
        """Install sys.excepthook + threading.excepthook to catch crashes."""
        prev_sys_hook = sys.excepthook
        prev_thread_hook = threading.excepthook

        def sys_hook(exc_type, exc_value, exc_tb):
            try:
                tb_text = "".join(tb_module.format_exception(exc_type, exc_value, exc_tb))
                log.error("Unhandled exception:\n%s", tb_text)
                self._show_crash_dialog(exc_type.__name__, str(exc_value), tb_text)
            finally:
                prev_sys_hook(exc_type, exc_value, exc_tb)

        def thread_hook(args):
            try:
                tb_text = "".join(
                    tb_module.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
                )
                log.error("Unhandled thread exception:\n%s", tb_text)
                self._show_crash_dialog(args.exc_type.__name__, str(args.exc_value), tb_text)
            finally:
                prev_thread_hook(args)

        sys.excepthook = sys_hook
        threading.excepthook = thread_hook

    def _show_crash_dialog(self, exc_type: str, exc_message: str, traceback_text: str):
        """Show a modal dialog offering to file a crash report."""
        from riplex_app.bug_report import build_crash_report_url
        from riplex_app.crash_dump import write_crash_dump

        last_screen = getattr(self, "_current_screen_name", None)

        # Write a dump file with traceback + state + log tail. Best-effort.
        dump_path: str | None = None
        try:
            dump = write_crash_dump(
                exc_type=exc_type,
                exc_message=exc_message,
                traceback_text=traceback_text,
                state=self.state,
                last_screen=last_screen,
            )
            dump_path = str(dump)
            log.error("Crash dump written: %s", dump_path)
        except Exception:
            log.exception("Failed to write crash dump")

        def report(_e):
            url = build_crash_report_url(
                self.state,
                exc_type=exc_type,
                exc_message=exc_message,
                traceback_text=traceback_text,
                last_screen=last_screen,
                dump_path=dump_path,
            )
            log.info("Opening crash report: %s", url)
            webbrowser.open(url)
            close(_e)

        def open_dump(_e):
            if not dump_path:
                return
            try:
                import os
                os.startfile(str(Path(dump_path).parent))  # type: ignore[attr-defined]
            except Exception:
                log.exception("Failed to open crash dump folder")

        def close(_e):
            dialog.open = False
            self.page.update()

        # Keep the visible traceback short; the full one goes to GitHub.
        preview = traceback_text.strip().splitlines()[-12:]
        preview_text = "\n".join(preview)

        content_children: list[ft.Control] = [
            ft.Text(f"{exc_type}: {exc_message}", selectable=True),
            ft.Container(height=10),
            ft.Text(
                "Help us fix this by filing a crash report. The traceback "
                "and version info will be pre-filled.",
                size=12,
            ),
        ]
        if dump_path:
            content_children.extend([
                ft.Container(height=6),
                ft.Text(
                    "A full crash dump (traceback + app state + recent logs) "
                    "was saved to:",
                    size=12,
                ),
                ft.Text(dump_path, size=11, selectable=True, font_family="Consolas"),
                ft.Text(
                    "Please attach this file to the GitHub issue.",
                    size=12,
                    italic=True,
                ),
            ])
        content_children.extend([
            ft.Container(height=10),
            ft.Container(
                content=ft.Text(preview_text, size=11, selectable=True, font_family="Consolas"),
                bgcolor=ft.Colors.BLACK26,
                padding=10,
                border_radius=4,
            ),
        ])

        actions: list[ft.Control] = [ft.TextButton("Dismiss", on_click=close)]
        if dump_path:
            actions.append(
                ft.TextButton("Show Dump Folder", icon=ft.Icons.FOLDER_OPEN, on_click=open_dump)
            )
        actions.append(
            ft.FilledButton(
                "Report Crash",
                icon=ft.Icons.BUG_REPORT,
                on_click=report,
            )
        )

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                [
                    ft.Icon(ft.Icons.ERROR, color=ft.Colors.RED_400),
                    ft.Text("riplex crashed"),
                ],
                spacing=10,
            ),
            content=ft.Column(
                content_children,
                tight=True,
                width=600,
                scroll=ft.ScrollMode.AUTO,
            ),
            actions=actions,
        )
        try:
            # ``show_dialog`` exists in Flet 0.84+ and is the only form that
            # survives the rename to remove ``page.open()`` in 0.85+.
            self.page.show_dialog(dialog)
        except Exception:  # pragma: no cover — last-ditch fallback
            log.exception("Failed to show crash dialog")


def _parse_exception_summary(traceback_text: str) -> tuple[str, str]:
    """Extract exception type and message from the last line of a traceback."""
    last_line = ""
    for line in reversed(traceback_text.strip().splitlines()):
        if line.strip():
            last_line = line.strip()
            break
    if ":" in last_line:
        exc_type, _, exc_message = last_line.partition(":")
        return exc_type.strip(), exc_message.strip()
    return last_line or "Exception", ""


def _button_label(control) -> str | None:
    """Return a button's visible label across Flet versions.

    Flet 0.85 stores a ``TextButton('Quit')`` label under ``.content``
    (a plain str), while other button flavors / older versions use
    ``.text``. We normalize both so the Quit-dedup below is reliable.
    """
    for attr in ("text", "content"):
        val = getattr(control, attr, None)
        if isinstance(val, str):
            return val
    return None


def _tree_has_quit(control) -> bool:
    """True if any Row in ``control``'s subtree already holds a Quit button.

    Terminal screens (``done``, ``orchestrate_done``) bake in their own
    Quit-to-close-app button, which may not live in the very last footer
    row. We scan the whole tree so the globally-injected Quit is skipped
    wherever the local one sits, avoiding a confusing double-Quit.
    """
    if isinstance(control, ft.Row):
        for existing in control.controls or []:
            if _button_label(existing) == "Quit":
                return True
    children = getattr(control, "controls", None) or []
    return any(_tree_has_quit(child) for child in children)


def _append_to_footer_row(control, button) -> bool:
    """Append ``button`` to the footer ``Row`` of ``control`` if there is one.

    Screens generally end with a footer ``Row`` of navigation buttons.
    We only look at the *last* child of a Column tree so the injected
    Quit button lands in the true bottom footer rather than a header
    row that happens to also be a Row. Returns ``True`` on success so
    ``navigate`` can fall back to wrapping when a screen's build
    doesn't fit this shape.

    If the built tree already contains a control labelled "Quit"
    (some terminal screens like ``done`` and ``orchestrate_done``
    bake in a local Quit-to-close-app button), we skip injection to
    avoid a confusing double-Quit.
    """
    if _tree_has_quit(control):
        return True  # skip injection, but treat as handled
    return _append_to_last_row(control, button)


def _append_to_last_row(control, button) -> bool:
    """Append ``button`` to the last descendant ``Row`` of ``control``."""
    if not isinstance(control, ft.Column):
        return False
    children = control.controls or []
    if not children:
        return False
    last = children[-1]
    if isinstance(last, ft.Row):
        last.controls.append(button)
        return True
    return _append_to_last_row(last, button)


def _configure_tls_certificates(env=None):
    """Point urllib/ssl at certifi before Flet's first-launch download."""
    if env is None:
        env = os.environ
    try:
        import certifi
    except Exception:  # pragma: no cover - certifi is an explicit dependency.
        return None

    cert_path = certifi.where()
    env.setdefault("SSL_CERT_FILE", cert_path)
    env.setdefault("REQUESTS_CA_BUNDLE", cert_path)
    return cert_path


def _configure_flet_view_path(env=None, bundle_root=None, platform=None):
    """Point Flet at a bundled desktop client when one is packaged."""
    if env is None:
        env = os.environ
    if env.get("FLET_VIEW_PATH"):
        return env["FLET_VIEW_PATH"]

    if bundle_root is None:
        bundle_root = getattr(sys, "_MEIPASS", None)
    if not bundle_root:
        return None

    if platform is None:
        platform = sys.platform

    client_dir = Path(bundle_root) / "flet_client"
    if platform.startswith("win"):
        ready = (client_dir / "flet.exe").is_file()
    elif platform == "darwin":
        ready = any(client_dir.glob("*.app"))
    else:
        ready = (client_dir / "flet").is_file()

    if not ready:
        return None

    env["FLET_VIEW_PATH"] = str(client_dir)
    return str(client_dir)


def main():
    _configure_tls_certificates()
    _configure_flet_view_path()

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    # Write riplex_app logs to a file (Flet debug noise drowns the console)
    from riplex_app.crash_dump import get_log_path

    app_logger = logging.getLogger("riplex_app")
    lib_logger = logging.getLogger("riplex")
    log_path = get_log_path()
    fh = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s [%(name)s] %(message)s", datefmt="%H:%M:%S"))
    app_logger.addHandler(fh)
    lib_logger.addHandler(fh)
    lib_logger.setLevel(logging.DEBUG)
    app_logger.info("Log file: %s", log_path)
    ft.app(target=RiplexApp)


if __name__ == "__main__":
    main()
