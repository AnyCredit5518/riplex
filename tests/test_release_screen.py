from types import SimpleNamespace
from unittest.mock import MagicMock

from riplex_app.background import capture_screen_lease
from riplex_app.screens.release import ReleaseScreen


class _Release:
    name = "Empty Release"


class _App:
    def __init__(self, state):
        self.state = state
        self.navigated_to = None
        self.navigation_calls: list[str] = []
        self.page = MagicMock()

    def navigate(self, screen):
        self.navigated_to = screen
        self.navigation_calls.append(screen)


def test_loading_build_starts_one_lookup_worker(monkeypatch):
    started: list = []

    class _DeferredThread:
        def __init__(self, *, target, daemon, name=None, args=()):
            started.append((target, args))

        def start(self):
            pass

    monkeypatch.setattr("riplex_app.background.threading.Thread", _DeferredThread)
    app = _App({"title": "Psych", "workflow": "rip"})
    screen = ReleaseScreen(app)

    screen.build()
    screen.build()

    assert len(started) == 1


def test_late_lookup_completion_does_not_restore_release(monkeypatch):
    workers: list = []

    class _DeferredThread:
        def __init__(self, *, target, daemon, name=None, args=()):
            workers.append(target)

        def start(self):
            pass

    film = SimpleNamespace(title="Psych", film_id=1, releases=[])

    class _Provider:
        async def fetch_film(self, _title, _format, *, year=None):
            return film

    monkeypatch.setattr("riplex_app.background.threading.Thread", _DeferredThread)
    monkeypatch.setattr("riplex_app.screens.release.DiscProvider", _Provider)
    app = _App({"title": "Psych", "workflow": "rip"})
    app._current_screen_name = "release"
    app._navigation_epoch = 5
    screen = ReleaseScreen(app)
    screen.build()

    app._current_screen_name = "metadata"
    app._navigation_epoch += 1
    workers[0]()

    assert "_dvdcompare_film" not in app.state
    assert app.navigation_calls == []


def test_late_manual_override_lookup_is_not_persisted(monkeypatch):
    cache_writes = []
    provider_calls = []
    film = SimpleNamespace(title="Old Movie", film_id=42, releases=[])
    new_film = SimpleNamespace(title="New Movie", film_id=84, releases=[])
    app = _App({
        "title": "Old Movie",
        "workflow": "rip",
        "_dvdcompare_film_id_override": 42,
    })
    app._current_screen_name = "release"
    app._navigation_epoch = 5

    class _Provider:
        async def fetch_film_by_id(self, film_id):
            provider_calls.append(("id", film_id))
            if len(provider_calls) == 1:
                app.state["title"] = "New Movie"
                app._current_screen_name = "metadata"
                app._navigation_epoch = 6
            return film

        async def fetch_film(self, title, _format, *, year=None):
            provider_calls.append(("title", title))
            return new_film

    monkeypatch.setattr("riplex_app.screens.release.DiscProvider", _Provider)
    monkeypatch.setattr(
        "riplex_app.screens.release._cache.cache_set",
        lambda *args: cache_writes.append(args),
    )
    screen = ReleaseScreen(app)
    monkeypatch.setattr(screen, "_load_persisted_override", lambda: None)
    lease = capture_screen_lease(app)

    screen._lookup_dvdcompare("Old Movie", lease)
    app._current_screen_name = "release"
    app._navigation_epoch = 7
    screen._lookup_dvdcompare("New Movie", capture_screen_lease(app))

    assert cache_writes == []
    assert "_dvdcompare_film_id_override" not in app.state
    assert provider_calls == [("id", 42), ("title", "New Movie")]


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

    def test_empty_converted_release_stays_on_release_screen(self, monkeypatch):
        app = _App({"workflow": "orchestrate"})
        screen = ReleaseScreen(app)
        monkeypatch.setattr("riplex_app.screens.release._convert_release", lambda _release: [])

        screen._use_release(_Release())

        assert app.state["release"] is None
        assert app.state["dvdcompare_discs"] == []
        assert "did not contain usable disc data" in app.state["_dvdcompare_error"]
        assert app.navigated_to == "release"

    def test_failed_release_conversion_stays_on_release_screen(self, monkeypatch):
        app = _App({"workflow": "orchestrate"})
        screen = ReleaseScreen(app)

        def fail(_release):
            raise ValueError("bad release")

        monkeypatch.setattr("riplex_app.screens.release._convert_release", fail)

        screen._use_release(_Release())

        assert app.state["release"] is None
        assert app.state["dvdcompare_discs"] == []
        assert "bad release" in app.state["_dvdcompare_error"]
        assert app.navigated_to == "release"


class _Film:
    def __init__(self, title, film_id=42):
        self.title = title
        self.film_id = film_id


class TestReleaseFilmHeading:
    def test_uses_film_comparison_title(self):
        app = _App({})
        screen = ReleaseScreen(app)
        screen.film_comparison = _Film("Psych: Season 1 (TV) (Blu-ray)")

        controls = screen._build_film_heading()

        texts = [c.value for c in controls]
        assert "Psych: Season 1 (TV) (Blu-ray)" in texts
        assert "Disc Release" in texts  # kept as smaller label

    def test_falls_back_to_state_stashed_title(self):
        app = _App({"dvdcompare_film_title": "Psych: Complete Series"})
        screen = ReleaseScreen(app)
        screen.film_comparison = None

        controls = screen._build_film_heading()

        texts = [c.value for c in controls]
        assert "Psych: Complete Series" in texts

    def test_no_film_falls_back_to_plain_heading(self):
        app = _App({})
        screen = ReleaseScreen(app)
        screen.film_comparison = None

        controls = screen._build_film_heading()

        assert len(controls) == 1
        assert controls[0].value == "Disc Release"

    def test_prefers_in_memory_film_over_stashed_title(self):
        app = _App({"dvdcompare_film_title": "stale stashed"})
        screen = ReleaseScreen(app)
        screen.film_comparison = _Film("fresh in-memory")

        controls = screen._build_film_heading()

        texts = [c.value for c in controls]
        assert "fresh in-memory" in texts
        assert "stale stashed" not in texts


class _TmdbMatch:
    def __init__(self, media_type="tv"):
        self.media_type = media_type


class TestBackfillSeasonNumberFromFilmTitle:
    """When the physical disc's volume label ("PSYCH") doesn't include
    a season, the release screen must still populate
    ``state["season_number"]`` from the dvdcompare film title
    ("Psych: Season 1 (TV) (DVD)") so the rip layout nests under
    ``Season NN`` and future seasons of the same show don't collide
    on ``Disc N``."""

    def test_infers_season_from_film_title(self):
        from riplex_app.screens.release import (
            _backfill_season_number_from_film_title,
        )

        state = {"tmdb_match": _TmdbMatch(media_type="tv")}
        _backfill_season_number_from_film_title(
            state, _Film("Psych: Season 1 (TV) (DVD)"),
        )
        assert state["season_number"] == 1

    def test_leaves_existing_season_untouched(self):
        from riplex_app.screens.release import (
            _backfill_season_number_from_film_title,
        )

        state = {
            "tmdb_match": _TmdbMatch(media_type="tv"),
            "season_number": 3,
        }
        _backfill_season_number_from_film_title(
            state, _Film("Psych: Season 1 (TV) (DVD)"),
        )
        assert state["season_number"] == 3

    def test_no_op_for_movie_match(self):
        from riplex_app.screens.release import (
            _backfill_season_number_from_film_title,
        )

        state = {"tmdb_match": _TmdbMatch(media_type="movie")}
        _backfill_season_number_from_film_title(
            state, _Film("Blade Runner Season 2 Edition"),
        )
        assert "season_number" not in state

    def test_no_op_for_complete_series_title(self):
        from riplex_app.screens.release import (
            _backfill_season_number_from_film_title,
        )

        state = {"tmdb_match": _TmdbMatch(media_type="tv")}
        _backfill_season_number_from_film_title(
            state, _Film("Psych: Complete Series (TV) (Blu-ray)"),
        )
        assert "season_number" not in state

    def test_no_op_when_film_is_none(self):
        from riplex_app.screens.release import (
            _backfill_season_number_from_film_title,
        )

        state = {"tmdb_match": _TmdbMatch(media_type="tv")}
        _backfill_season_number_from_film_title(state, None)
        assert "season_number" not in state


class TestUseReleaseSeasonFilter:
    """The release picker must enforce the "one season at a time"
    invariant: even if the user picks a boxset release covering
    multiple seasons, ``dvdcompare_discs`` gets filtered down to the
    picked season before disc_overview sees it."""

    def _boxset_discs(self):
        from riplex.models import PlannedDisc

        def _d(n, title=""):
            return PlannedDisc(number=n, disc_format="Blu-ray", title=title)

        return (
            [_d(n, title="Season 1") for n in range(1, 5)]
            + [_d(n, title="Season 2") for n in range(5, 9)]
            + [_d(9)]  # bonus disc, untitled
        )

    def test_tv_boxset_filters_to_picked_season(self, monkeypatch):
        discs = self._boxset_discs()
        monkeypatch.setattr(
            "riplex_app.screens.release._convert_release",
            lambda _release: discs,
        )

        app = _App({
            "workflow": "orchestrate",
            "tmdb_match": _TmdbMatch(media_type="tv"),
            "season_number": 2,
            "_dvdcompare_film": _Film("Psych (TV) (Blu-ray)"),
        })
        screen = ReleaseScreen(app)
        screen._use_release(_Release())

        got = app.state["dvdcompare_discs"]
        assert [d.number for d in got] == [5, 6, 7, 8]

    def test_movie_release_bypasses_filter(self, monkeypatch):
        # Even with a season_number lingering in state (shouldn't
        # happen for movies but be defensive), a movie tmdb_match
        # skips the filter entirely.
        from riplex.models import PlannedDisc
        movie_discs = [PlannedDisc(number=1, disc_format="Blu-ray")]
        monkeypatch.setattr(
            "riplex_app.screens.release._convert_release",
            lambda _release: movie_discs,
        )

        app = _App({
            "workflow": "orchestrate",
            "tmdb_match": _TmdbMatch(media_type="movie"),
            "season_number": 2,  # bogus, must not cause filtering
            "_dvdcompare_film": _Film("Batman Begins"),
        })
        screen = ReleaseScreen(app)
        screen._use_release(_Release())

        assert app.state["dvdcompare_discs"] == movie_discs

    def test_no_season_number_bypasses_filter(self, monkeypatch):
        # TV rip where the season is genuinely unknown (mini-series
        # style): filter is a no-op, whole release passes through.
        discs = self._boxset_discs()
        monkeypatch.setattr(
            "riplex_app.screens.release._convert_release",
            lambda _release: discs,
        )

        app = _App({
            "workflow": "orchestrate",
            "tmdb_match": _TmdbMatch(media_type="tv"),
            # season_number deliberately unset
            "_dvdcompare_film": _Film("Planet Earth II"),
        })
        screen = ReleaseScreen(app)
        screen._use_release(_Release())

        assert app.state["dvdcompare_discs"] == discs

