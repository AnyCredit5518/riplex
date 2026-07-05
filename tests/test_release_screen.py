from riplex_app.screens.release import ReleaseScreen


class _Release:
    name = "Empty Release"


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
