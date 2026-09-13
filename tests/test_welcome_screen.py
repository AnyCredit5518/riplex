from types import SimpleNamespace

import flet as ft

from riplex.disc.provider import DvdcompareConnectivity
from riplex_app.screens.welcome import WelcomeScreen, has_complete_config, should_show_setup


class TestHasCompleteConfig:
    def test_requires_api_key_output_root_and_rip_output(self):
        assert has_complete_config({}) is False
        assert has_complete_config({"tmdb_api_key": "key"}) is False
        assert has_complete_config({"tmdb_api_key": "key", "output_root": "E:/Media"}) is False
        assert has_complete_config({
            "tmdb_api_key": "key",
            "output_root": "E:/Media",
            "rip_output": "E:/Media/_MakeMKV",
        }) is True

    def test_archive_root_is_optional(self):
        assert has_complete_config({
            "tmdb_api_key": "key",
            "output_root": "E:/Media",
            "rip_output": "E:/Media/_MakeMKV",
            "archive_root": "",
        }) is True


class TestShouldShowSetup:
    def test_shows_setup_for_incomplete_config(self):
        assert should_show_setup({"tmdb_api_key": "key"}, {}) is True

    def test_hides_setup_for_complete_config(self):
        config = {
            "tmdb_api_key": "key",
            "output_root": "E:/Media",
            "rip_output": "E:/Media/_MakeMKV",
        }
        assert should_show_setup(config, {}) is False

    def test_can_force_show_setup_for_editing(self):
        config = {
            "tmdb_api_key": "key",
            "output_root": "E:/Media",
            "rip_output": "E:/Media/_MakeMKV",
        }
        assert should_show_setup(config, {"_show_setup": True}) is True


class TestConnectivityDisplay:
    @staticmethod
    def _screen():
        screen = WelcomeScreen.__new__(WelcomeScreen)
        screen._tmdb_status_icon = ft.Icon(ft.Icons.HOURGLASS_EMPTY)
        screen._tmdb_status_text = ft.Text()
        screen._dvdc_status_icon = ft.Icon(ft.Icons.HOURGLASS_EMPTY)
        screen._dvdc_status_text = ft.Text()
        return screen

    def test_https_is_available(self):
        screen = self._screen()

        screen._apply_connectivity(
            True,
            DvdcompareConnectivity(transport="https"),
        )

        assert screen._dvdc_status_icon.icon == ft.Icons.CHECK_CIRCLE
        assert screen._dvdc_status_icon.color == ft.Colors.GREEN
        assert screen._dvdc_status_text.value == "dvdcompare.net"

    def test_http_fallback_is_available_but_degraded(self):
        screen = self._screen()

        screen._apply_connectivity(
            True,
            DvdcompareConnectivity(transport="http"),
        )

        assert screen._dvdc_status_icon.icon == ft.Icons.WARNING
        assert screen._dvdc_status_icon.color == ft.Colors.ORANGE
        assert screen._dvdc_status_text.color == ft.Colors.ORANGE
        assert screen._dvdc_status_text.value == "dvdcompare.net (degraded)"

    def test_failure_is_unreachable(self):
        screen = self._screen()

        screen._apply_connectivity(
            True,
            DvdcompareConnectivity(transport=None, error="ConnectError: offline"),
        )

        assert screen._dvdc_status_icon.icon == ft.Icons.ERROR
        assert screen._dvdc_status_icon.color == ft.Colors.RED
        assert screen._dvdc_status_text.color == ft.Colors.RED
        assert screen._dvdc_status_text.value == "dvdcompare.net (unreachable)"

    def test_cached_connectivity_is_reused_without_probing(self, monkeypatch):
        import riplex_app.screens.welcome as welcome

        cached = DvdcompareConnectivity(transport="http")
        screen = WelcomeScreen(
            SimpleNamespace(
                state={
                    "_connectivity_tmdb": True,
                    "_connectivity_dvdc": cached,
                }
            )
        )
        applied = []
        screen._apply_connectivity = lambda tmdb, dvdc: applied.append((tmdb, dvdc))

        async def _unexpected_probe():
            raise AssertionError("cached connectivity should avoid a new probe")

        monkeypatch.setattr(welcome, "probe_dvdcompare_connectivity", _unexpected_probe)

        screen.check_connectivity()

        assert applied == [(True, cached)]