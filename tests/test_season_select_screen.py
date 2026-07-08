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


@pytest.fixture(autouse=True)
def _isolate_from_real_sessions(monkeypatch):
    """Prevent the picker's in-progress scan from touching the dev
    machine's real rip root during tests. Individual tests that want
    to observe find_existing_session calls override this fixture by
    monkey-patching again with their own stub."""
    monkeypatch.setattr(
        "riplex.manifest.find_existing_session",
        lambda *_a, **_kw: None,
    )


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
        # Only seasons 1, 2, 3 are offered (no "0").
        assert set(screen._season_meta.keys()) == {1, 2, 3}
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
        labels = [meta["label"] for meta in screen._season_meta.values()]
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


class TestOrchestrateResumeOnPick:
    """When workflow=orchestrate and a session exists for the picked
    (title, season), season_select must start a full resume instead
    of walking the fresh release-picker flow. Handles both entry
    points (disc_detection prep -> season_select and back-navigation
    from release)."""

    def test_resumes_matching_session_and_skips_release(self, monkeypatch):
        # A fake session for (Psych, season 2) that find_existing_session
        # will return when queried with season_number=2.
        fake_session = SimpleNamespace(
            title="Psych", year=2006, media_type="tv",
            source_id="tv:1447", season_number=2,
        )

        seen: list[tuple[str, int | None]] = []
        def _fake_find(title, *, season_number=None):
            seen.append((title, season_number))
            return fake_session if season_number == 2 else None

        monkeypatch.setattr(
            "riplex.manifest.find_existing_session", _fake_find,
        )

        # Prevent the resume thread from actually running the adapter.
        started: list = []

        class _FakeThread:
            def __init__(self, *, target, args, daemon):
                started.append((target, args))

            def start(self):
                pass

        import riplex_app.screens.season_select as ss_mod
        monkeypatch.setattr(ss_mod.threading, "Thread", _FakeThread)

        app = _App({
            "workflow": "orchestrate",
            "title": "Psych",
            "tmdb_match": _tmdb_match(),
            "show_detail": _show_detail_multi_season(),
        })
        screen = SeasonSelectScreen(app)
        screen.build()
        screen._radio_group.value = "2"
        screen._on_next(None)

        assert app.state["season_number"] == 2
        # Resume kicked off; no navigation to release.
        assert app.navigated_to == []
        assert len(started) == 1
        target, args = started[0]
        # Second arg is the session; verify it's the exact object we
        # returned from find_existing_session.
        assert args[1] is fake_session
        # The picker's in-progress scan calls find_existing_session
        # once per non-special season during build(), and _on_next
        # calls it once more for the picked season. What matters is
        # that the picked season's query happened.
        assert ("Psych", 2) in seen

    def test_no_matching_session_falls_through_to_release(self, monkeypatch):
        monkeypatch.setattr(
            "riplex.manifest.find_existing_session",
            lambda _t, **_kw: None,
        )
        app = _App({
            "workflow": "orchestrate",
            "title": "Psych",
            "tmdb_match": _tmdb_match(),
            "show_detail": _show_detail_multi_season(),
        })
        screen = SeasonSelectScreen(app)
        screen.build()
        screen._radio_group.value = "3"
        screen._on_next(None)

        assert app.state["season_number"] == 3
        assert app.navigated_to == ["release"]

    def test_fresh_workflow_does_not_start_resume(self, monkeypatch):
        # Fresh (non-orchestrate) rip flow should never start a resume
        # even if a session happens to exist for the picked season --
        # the user asked for a fresh flow. (The in-progress scan may
        # still call find_existing_session to render hints; that's a
        # display concern separate from resume routing.)
        session = SimpleNamespace(
            title="Psych", year=2006, media_type="tv",
            source_id="tv:1447", season_number=1,
            ripped_discs=set(), works=[],
        )
        monkeypatch.setattr(
            "riplex.manifest.find_existing_session",
            lambda *_a, **_kw: session,
        )

        started: list = []
        class _FakeThread:
            def __init__(self, *, target, args, daemon):
                started.append((target, args))
            def start(self):
                pass
        import riplex_app.screens.season_select as ss_mod
        monkeypatch.setattr(ss_mod.threading, "Thread", _FakeThread)

        app = _App({
            # workflow deliberately unset -- fresh rip flow
            "title": "Psych",
            "tmdb_match": _tmdb_match(),
            "show_detail": _show_detail_multi_season(),
        })
        screen = SeasonSelectScreen(app)
        screen.build()
        screen._radio_group.value = "1"
        screen._on_next(None)

        assert app.navigated_to == ["release"]
        assert started == []


class TestInProgressHints:
    """Hint annotations and default-selection bias driven by
    ``find_existing_session`` results."""

    def test_default_is_season_1_when_no_sessions(self, monkeypatch):
        monkeypatch.setattr(
            "riplex.manifest.find_existing_session",
            lambda *_a, **_kw: None,
        )
        app = _App({
            "title": "Psych",
            "tmdb_match": _tmdb_match(),
            "show_detail": _show_detail_multi_season(),
        })
        screen = SeasonSelectScreen(app)
        screen.build()
        assert screen._radio_group.value == "1"
        # No hints at all when no seasons are in progress.
        hints = [meta["hint"] for meta in screen._season_meta.values()]
        assert all(h is None for h in hints)

    def test_default_biases_to_first_in_progress_season(self, monkeypatch):
        # Only Season 2 has a session; picker should default to it
        # instead of Season 1 (which is otherwise the default).
        session_s2 = SimpleNamespace(
            title="Psych", year=2006, media_type="tv",
            source_id="tv:1447", season_number=2,
            ripped_discs={1, 2},
            works=[SimpleNamespace(season_number=2, disc_numbers=[1, 2, 3, 4])],
        )

        def _fake_find(_title, *, season_number=None):
            if season_number == 2:
                return session_s2
            return None

        monkeypatch.setattr(
            "riplex.manifest.find_existing_session", _fake_find,
        )

        app = _App({
            "title": "Psych",
            "tmdb_match": _tmdb_match(),
            "show_detail": _show_detail_multi_season(),
        })
        screen = SeasonSelectScreen(app)
        screen.build()

        assert screen._radio_group.value == "2"
        # Season 2 has an in-progress hint with the ripped/total breakdown.
        s2_hint = screen._season_meta[2]["hint"]
        assert s2_hint is not None
        assert "in progress" in s2_hint
        assert "2/4 discs ripped" in s2_hint
        # Season 1 has no hint.
        assert screen._season_meta[1]["hint"] is None

    def test_multiple_in_progress_seasons_pick_first_in_tmdb_order(
        self, monkeypatch,
    ):
        # Both Season 2 and Season 3 in progress; default = Season 2
        # (first in the TMDb-ordered non-special list).
        def _session(season, ripped, total):
            return SimpleNamespace(
                title="Psych", year=2006, media_type="tv",
                source_id="tv:1447", season_number=season,
                ripped_discs=set(range(1, ripped + 1)),
                works=[SimpleNamespace(
                    season_number=season,
                    disc_numbers=list(range(1, total + 1)),
                )],
            )

        def _fake_find(_title, *, season_number=None):
            if season_number == 2:
                return _session(2, 1, 4)
            if season_number == 3:
                return _session(3, 3, 4)
            return None

        monkeypatch.setattr(
            "riplex.manifest.find_existing_session", _fake_find,
        )

        app = _App({
            "title": "Psych",
            "tmdb_match": _tmdb_match(),
            "show_detail": _show_detail_multi_season(),
        })
        screen = SeasonSelectScreen(app)
        screen.build()

        # Default = earliest in-progress season.
        assert screen._radio_group.value == "2"
        # Both seasons render an in-progress hint.
        assert "in progress" in screen._season_meta[2]["hint"]
        assert "in progress" in screen._season_meta[3]["hint"]
        # Season 1 (untouched) has no hint.
        assert screen._season_meta[1]["hint"] is None


    def test_scan_failure_is_non_fatal(self, monkeypatch):
        # A filesystem error during the scan must not block picker
        # rendering; the picker degrades to no-hints, Season 1 default.
        def _raise(*_a, **_kw):
            raise OSError("disk offline")

        monkeypatch.setattr(
            "riplex.manifest.find_existing_session", _raise,
        )

        app = _App({
            "title": "Psych",
            "tmdb_match": _tmdb_match(),
            "show_detail": _show_detail_multi_season(),
        })
        screen = SeasonSelectScreen(app)
        screen.build()

        assert screen._radio_group.value == "1"

