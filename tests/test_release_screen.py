from riplex_app.screens.release import ReleaseScreen


class _App:
    def __init__(self, state):
        self.state = state
        self.navigated_to = None

    def navigate(self, screen):
        self.navigated_to = screen


class TestReleaseSkipRouting:
    def test_rip_workflow_continues_to_selection(self):
        app = _App({"workflow": "rip"})
        screen = ReleaseScreen(app)

        screen._skip(None)

        assert app.state["dvdcompare_discs"] == []
        assert app.navigated_to == "selection"

    def test_orchestrate_with_release_uses_disc_overview(self):
        app = _App({"workflow": "orchestrate"})
        screen = ReleaseScreen(app)

        assert screen._next_screen == "disc_overview"

    def test_orchestrate_without_dvdcompare_starts_single_disc_selection(self):
        app = _App({"workflow": "orchestrate"})
        screen = ReleaseScreen(app)

        screen._skip(None)

        assert app.state["dvdcompare_discs"] == []
        assert app.state["_orchestrate_disc_number"] == 1
        assert app.state["disc_queue"] == [1]
        assert app.state["current_disc_idx"] == 0
        assert app.state["all_rip_results"] == {}
        assert app.navigated_to == "selection"