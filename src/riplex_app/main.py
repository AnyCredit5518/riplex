"""Riplex GUI - Flet-based companion app for riplex."""

import logging

import flet as ft

log = logging.getLogger("riplex_app")

from riplex_app.screens.welcome import WelcomeScreen
from riplex_app.screens.disc_detection import DiscDetectionScreen
from riplex_app.screens.metadata import MetadataScreen
from riplex_app.screens.release import ReleaseScreen
from riplex_app.screens.selection import SelectionScreen
from riplex_app.screens.progress import ProgressScreen
from riplex_app.screens.done import DoneScreen
from riplex_app.screens.folder_picker import FolderPickerScreen
from riplex_app.screens.organize_preview import OrganizePreviewScreen
from riplex_app.screens.organize_done import OrganizeDoneScreen


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
            "workflow": "rip",    # "rip" | "organize"
            # Rip workflow
            "drive": None,        # DriveInfo
            "disc_info": None,    # DiscInfo
            "title": "",          # detected/overridden title
            "tmdb_match": None,   # selected TMDb result
            "movie_runtime": None,# TMDb movie runtime in seconds
            "release": None,      # selected dvdcompare release
            "selected_discs": [], # disc numbers to rip
            "selected_titles": [],# title indices to rip
            "output_dir": None,   # Path for rip output
            "rip_results": [],    # list of RipResult
            "makemkvcon": None,   # Path to exe
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
            "release": ReleaseScreen(self),
            "selection": SelectionScreen(self),
            "progress": ProgressScreen(self),
            "done": DoneScreen(self),
            "folder_picker": FolderPickerScreen(self),
            "organize_preview": OrganizePreviewScreen(self),
            "organize_done": OrganizeDoneScreen(self),
        }

        self.navigate("welcome")

    def navigate(self, screen_name: str):
        """Switch to a named screen."""
        log.info("navigate -> %s", screen_name)
        self.page.controls.clear()
        screen = self.screens[screen_name]
        self.page.controls.append(screen.build())
        self.page.update()


def main():
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    ft.app(target=RiplexApp)


if __name__ == "__main__":
    main()
