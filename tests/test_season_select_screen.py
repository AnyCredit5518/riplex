"""Tests for the SeasonSelectScreen auto-skip and picker paths."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from riplex.metadata.provider import (
    EpisodeMetadata,
    SeasonMetadata,
    ShowDetail,
)
from riplex_app.screens.season_select import SeasonSelectScreen


class _App:
    """Minimal stand-in for the Flet app object.

    Records navigation targets and drives the ``run_task``-based
    "navigate on next tick" path synchronously so tests can assert
    the final navigate target without spinning an event loop.
    """

    def __init__(self, state):
        self.state = state
        self.navigated_to: list[str] = []
        self._current_screen_name = "season_select"
        self.page = MagicMock()

        def _run_task(coro_or_fn):
            # Flet's page.run_task accepts either an async function or
            # a coroutine. Normalize by calling it if callable, then
            # drain the coroutine synchronously so tests can assert
            # navigation without an event loop.
            coro = coro_or_fn() if callable(coro_or_fn) else coro_or_fn
            try:
                coro.send(None)
            except StopIteration:
                pass
            except Exception:
                coro.close()

        self.page.run_task = _run_task

    def navigate(self, screen):
        self.navigated_to.append(screen)
        self._current_screen_name = screen


def _show_detail_multi_season() -> ShowDetail:
    """Psych-like: 3 real seasons plus Season 0 specials."""
    return ShowDetail(
        source_id="tv:1447",
        title="Psych",
        year=2006,
        seasons=[
            SeasonMetadata(season_number=0, episodes=[], name="Specials"),
            SeasonMetadata(
                season_number=1,
                episodes=[EpisodeMetadata(season_number=1, episode_number=1, title="Pilot")],
                name="Season 1",
            ),
            SeasonMetadata(
                season_number=2,
                episodes=[
                    EpisodeMetadata(season_number=2, episode_number=1, title="A"),
                    EpisodeMetadata(season_number=2, episode_number=2, title="B"),
                ],
                name="Season 2",
            ),
            SeasonMetadata(season_number=3, episodes=[], name="Season 3"),
        ],
    )


def _show_detail_miniseries() -> ShowDetail:
    """Planet Earth II-like: Season 0 Specials + one Miniseries season."""
    return ShowDetail(
        source_id="tv:68595",
        title="Planet Earth II",
        year=2016,
        seasons=[
            SeasonMetadata(season_number=0, episodes=[], name="Specials"),
            SeasonMetadata(
                season_number=1,
                episodes=[
                    EpisodeMetadata(season_number=1, episode_number=i, title=f"E{i}")
                    for i in range(1, 7)
                ],
                name="Miniseries",
            ),
        ],
    )


def _tmdb_match(media_type="tv"):
    return SimpleNamespace(
        source_id="tv:1447",
        title="Psych",
        year=2006,
        media_type=media_type,
    )


class TestAutoSkip:
    def test_skips_when_season_number_already_set(self):
        """Volume label PSYCH_S2_D1 already set season_number=2, folder
        picker parsed it out of "Season 02" — either way we skip."""
        app = _App({
            "season_number": 2,
            "tmdb_match": _tmdb_match(),
            "show_detail": _show_detail_multi_season(),
        })
        screen = SeasonSelectScreen(app)
        screen.build()
        assert app.navigated_to == ["release"]
        # Preserved -- we did NOT stomp on it.
        assert app.state["season_number"] == 2

    def test_skips_for_movie_match(self):
        app = _App({
            "tmdb_match": _tmdb_match(media_type="movie"),
        })
        screen = SeasonSelectScreen(app)
        screen.build()
        assert app.navigated_to == ["release"]
        assert app.state.get("season_number") is None

    def test_skips_when_no_tmdb_match(self):
        app = _App({})
        screen = SeasonSelectScreen(app)
        screen.build()
        assert app.navigated_to == ["release"]

    def test_skips_for_miniseries(self):
        """Planet Earth II: single non-special season -> auto-skip and
        do NOT set season_number (dvdcompare gets bare title)."""
        app = _App({
            "tmdb_match": _tmdb_match(),
            "show_detail": _show_detail_miniseries(),
        })
        screen = SeasonSelectScreen(app)
        screen.build()
        assert app.navigated_to == ["release"]
        assert app.state.get("season_number") is None, (
            "mini-series must not set season_number -- dvdcompare "
            "matches mini-series films by bare title"
        )


class TestPicker:
    def test_renders_only_non_special_seasons(self):
        """Season 0 (Specials) is filtered out of the choices; the plan
        still keeps it for extras routing at organize time."""
        app = _App({
            "tmdb_match": _tmdb_match(),
            "show_detail": _show_detail_multi_season(),
        })
        screen = SeasonSelectScreen(app)
        screen.build()
        # Not navigated yet -- we're on the picker.
        assert app.navigated_to == []
        # Radio values contain only 1, 2, 3 (no "0").
        radio_values = {r.value for r in screen._radio_group.content.controls}
        assert radio_values == {"1", "2", "3"}
        # Default is the first non-special season (season 1).
        assert screen._radio_group.value == "1"

    def test_next_writes_picked_season_and_navigates(self):
        app = _App({
            "tmdb_match": _tmdb_match(),
            "show_detail": _show_detail_multi_season(),
            "release": object(),  # stale from a prior forward-back cycle
            "dvdcompare_discs": [object()],
            "_dvdcompare_film": object(),
        })
        screen = SeasonSelectScreen(app)
        screen.build()
        screen._radio_group.value = "2"
        screen._on_next(None)

        assert app.state["season_number"] == 2
        assert app.navigated_to == ["release"]
        # Any stale dvdcompare state gets cleared -- else back-then-forward
        # from release would re-use the old film's discs.
        assert app.state["release"] is None
        assert app.state["dvdcompare_discs"] == []
        assert "_dvdcompare_film" not in app.state

    def test_next_ignores_click_before_selection(self):
        """Defensive: if radio_group somehow has no value we no-op
        instead of crashing on int(None)."""
        app = _App({
            "tmdb_match": _tmdb_match(),
            "show_detail": _show_detail_multi_season(),
        })
        screen = SeasonSelectScreen(app)
        screen.build()
        screen._radio_group.value = None
        screen._on_next(None)
        assert app.navigated_to == []
        assert app.state.get("season_number") is None

    def test_back_returns_to_metadata(self):
        app = _App({
            "tmdb_match": _tmdb_match(),
            "show_detail": _show_detail_multi_season(),
        })
        screen = SeasonSelectScreen(app)
        screen.build()
        screen._on_back(None)
        assert app.navigated_to == ["metadata"]

    def test_season_name_appears_when_differs_from_default_label(self):
        """When TMDb's season name is something other than "Season N"
        (e.g. "Miniseries"), show it as a suffix so the user has that
        context."""
        # Craft a 2-season show where season 1's name is "Volume One".
        detail = ShowDetail(
            source_id="tv:1",
            title="Show",
            year=2020,
            seasons=[
                SeasonMetadata(season_number=0, episodes=[]),
                SeasonMetadata(season_number=1, episodes=[], name="Volume One"),
                SeasonMetadata(season_number=2, episodes=[], name="Season 2"),
            ],
        )
        app = _App({
            "tmdb_match": _tmdb_match(),
            "show_detail": detail,
        })
        screen = SeasonSelectScreen(app)
        screen.build()
        labels = [r.label for r in screen._radio_group.content.controls]
        assert any("Volume One" in lbl for lbl in labels)
        # "Season 2 (Season 2)" would be silly -- we suppress the
        # redundant suffix.
        assert not any("Season 2 (Season 2)" in lbl for lbl in labels)


class TestLoadingState:
    def test_shows_spinner_when_show_detail_not_ready(self):
        """Metadata screen fires show_detail fetch in the background
        right before navigating here; if the user beats the network
        we render a spinner and poll."""
        app = _App({"tmdb_match": _tmdb_match()})  # no show_detail yet
        screen = SeasonSelectScreen(app)
        result = screen.build()
        # No navigation happened -- we're waiting.
        assert app.navigated_to == []
        # Not asserting exact UI structure; just that we produced a Column
        # and did not raise. (A ProgressRing lives inside.)
        assert result is not None
