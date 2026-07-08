"""Tests for the GUI-side disc-detection helpers that don't require Flet."""

from unittest.mock import MagicMock

import pytest

from riplex.disc.makemkv import DriveInfo
from riplex_app.screens.disc_detection import DiscDetectionScreen, diff_drive_lists


def _drive(index=0, device="D:", has_disc=False, label="", state="Empty", present=True):
    return DriveInfo(
        index=index,
        name="Test Drive",
        disc_label=label,
        device=device,
        has_disc=has_disc,
        is_present=present,
        state_label=state,
    )


class TestDiffDriveLists:
    def test_first_poll_always_changed(self):
        assert diff_drive_lists(None, [_drive()]) is True

    def test_no_change(self):
        a = [_drive()]
        b = [_drive()]
        assert diff_drive_lists(a, b) is False

    def test_disc_inserted(self):
        a = [_drive()]
        b = [_drive(has_disc=True, label="MOVIE", state="Disc: MOVIE")]
        assert diff_drive_lists(a, b) is True

    def test_label_change(self):
        a = [_drive(has_disc=True, label="A", state="Disc: A")]
        b = [_drive(has_disc=True, label="B", state="Disc: B")]
        assert diff_drive_lists(a, b) is True

    def test_placeholder_slots_ignored(self):
        a = [_drive(), _drive(index=1, device="", present=False)]
        b = [_drive()]
        assert diff_drive_lists(a, b) is False

    def test_drive_count_change(self):
        a = [_drive()]
        b = [_drive(), _drive(index=1, device="E:")]
        assert diff_drive_lists(a, b) is True


class _FakeApp:
    """Bare-bones stand-in for the Flet app object used by
    ``DiscDetectionScreen`` when we only care about state writes."""

    def __init__(self):
        self.state: dict = {}
        self.page = MagicMock()
        # run_task takes a coroutine — accept and ignore it so the
        # navigate() call at the tail of _fetch_dvdcompare_for_resume
        # doesn't try to actually schedule anything.
        self.page.run_task = lambda _coro: None

    def navigate(self, *_a, **_kw):
        pass



class _FakeSession:
    def __init__(
        self, *, title="Psych", year=2006, media_type="tv",
        release_name="The Complete Series", disc_format="Blu-ray",
        source_id="tv:1447", season_number=None,
    ):
        self.title = title
        self.year = year
        self.media_type = media_type
        self.release_name = release_name
        self.disc_format = disc_format
        self.source_id = source_id
        self.season_number = season_number


class TestResumeStashesFilmMetadata:
    """`_fetch_dvdcompare_for_resume` must populate the same
    ``dvdcompare_film_*`` state keys that ``release.py`` sets on the
    non-resume path — otherwise ``build_season_labels`` gets
    ``film_title=None`` on resume and can't backfill the leading run
    with the season parsed from the film title.
    """

    def test_stashes_film_title_id_and_object(self, monkeypatch):
        # A dvdcompare release with a matching name so the resume
        # picks it directly.
        matching_release = MagicMock()
        matching_release.name = "The Complete Series"

        film = MagicMock()
        film.title = "Psych: Season 1 (TV) (Blu-ray)"
        film.film_id = 66231
        film.releases = [matching_release]

        # Fake DiscProvider whose _fetch_film_cached returns our film.
        class _FakeProvider:
            async def _fetch_film_cached(self, title, disc_format, *, year=None):
                return film

        # detect_disc_format is called only if session.disc_format is
        # missing — provide a no-op so the import still succeeds.
        def _fake_detect_disc_format(_info):
            return "Blu-ray"

        # _convert_release converts the release into a list of
        # PlannedDiscs; return an empty list to skip that machinery.
        def _fake_convert(_release):
            return []

        import riplex.disc.provider as provider_mod
        monkeypatch.setattr(provider_mod, "DiscProvider", _FakeProvider)
        monkeypatch.setattr(provider_mod, "_convert_release", _fake_convert)
        monkeypatch.setattr(
            provider_mod, "detect_disc_format", _fake_detect_disc_format,
        )

        app = _FakeApp()
        screen = DiscDetectionScreen(app)
        session = _FakeSession(release_name="The Complete Series")

        screen._fetch_dvdcompare_for_resume(session)

        # Non-resume path sets these three keys; resume must too.
        assert app.state.get("dvdcompare_film_title") == \
            "Psych: Season 1 (TV) (Blu-ray)"
        assert app.state.get("dvdcompare_film_id") == 66231
        assert app.state.get("_dvdcompare_film") is film

    def test_missing_film_title_leaves_state_untouched(self, monkeypatch):
        # A film object with no title / id should not blow up and
        # should not write the keys.
        film = MagicMock()
        film.title = None
        film.film_id = None
        film.releases = []

        class _FakeProvider:
            async def _fetch_film_cached(self, title, disc_format, *, year=None):
                return film

        import riplex.disc.provider as provider_mod
        monkeypatch.setattr(provider_mod, "DiscProvider", _FakeProvider)
        monkeypatch.setattr(provider_mod, "_convert_release", lambda _r: [])
        monkeypatch.setattr(
            provider_mod, "detect_disc_format", lambda _i: "Blu-ray",
        )

        app = _FakeApp()
        screen = DiscDetectionScreen(app)
        screen._fetch_dvdcompare_for_resume(_FakeSession())

        # _dvdcompare_film gets set unconditionally when the fetch
        # succeeds, but title / id keys must not be created from None.
        assert app.state.get("_dvdcompare_film") is film
        assert "dvdcompare_film_title" not in app.state
        assert "dvdcompare_film_id" not in app.state


class TestPrepareTvSeasonPick:
    """TV orchestrate resumes route through season_select rather than
    jumping straight to disc_overview. This lets the user pick a
    different season (e.g. inserted a Season 4 disc while a Season 1
    rip is still in progress under the same title root)."""

    def test_sets_tmdb_match_without_season_and_kicks_off_show_detail(
        self, monkeypatch,
    ):
        # Prevent the background thread from actually running — the
        # start() call is enough to verify wiring, and running it would
        # make a live TMDb call via _fetch_show_detail_for_season_pick.
        started = {"count": 0}

        class _FakeThread:
            def __init__(self, *, target, args, daemon):
                started["count"] += 1
                self.target = target
                self.args = args

            def start(self):
                pass

        import riplex_app.screens.disc_detection as dd_mod
        monkeypatch.setattr(dd_mod.threading, "Thread", _FakeThread)

        app = _FakeApp()
        # Pre-seed old state that must be cleared so the user gets a
        # fresh season picker.
        app.state["season_number"] = 1
        app.state["release"] = object()
        app.state["dvdcompare_discs"] = ["stale"]

        screen = DiscDetectionScreen(app)
        # _prepare_tv_season_pick no longer touches any UI widgets —
        # it just seeds state and kicks off the show_detail thread,
        # so no MagicMock stubs are needed.

        session = _FakeSession(
            title="Psych", year=2006, media_type="tv",
            source_id="tv:1447", season_number=1,
        )
        screen._prepare_tv_season_pick(session)

        # tmdb_match derived from the session; season_number cleared.
        tmdb = app.state["tmdb_match"]
        assert tmdb.source_id == "tv:1447"
        assert tmdb.title == "Psych"
        assert tmdb.media_type == "tv"
        assert "season_number" not in app.state
        assert app.state.get("release") is None
        assert app.state.get("dvdcompare_discs") is None
        assert started["count"] == 1

    def test_search_routes_tv_session_via_season_pick(self, monkeypatch):
        # Route the resume through _prepare_tv_season_pick rather than
        # the movie-style _resume_session so the user can disambiguate
        # multiple in-progress seasons.
        session = _FakeSession(
            title="Psych", media_type="tv", source_id="tv:1447",
        )
        monkeypatch.setattr(
            "riplex.manifest.find_existing_session",
            lambda _title, **_kw: session,
        )

        app = _FakeApp()
        app.state["workflow"] = "orchestrate"
        app.state["title"] = "Psych"
        screen = DiscDetectionScreen(app)

        prep_calls: list = []
        resume_calls: list = []
        monkeypatch.setattr(
            screen, "_prepare_tv_season_pick",
            lambda s: prep_calls.append(s),
        )
        monkeypatch.setattr(
            screen, "_resume_session",
            lambda s: resume_calls.append(s),
        )

        screen._route_after_read()

        assert prep_calls == [session]
        assert resume_calls == []

    def test_search_routes_movie_session_via_direct_resume(self, monkeypatch):
        # Movies have no season ambiguity, so they should still jump
        # straight to the resume flow (no extra picker screen).
        session = _FakeSession(
            title="Some Movie", media_type="movie",
            source_id="movie:1", season_number=None,
        )
        monkeypatch.setattr(
            "riplex.manifest.find_existing_session",
            lambda _title, **_kw: session,
        )

        app = _FakeApp()
        app.state["workflow"] = "orchestrate"
        app.state["title"] = "Some Movie"
        screen = DiscDetectionScreen(app)

        prep_calls: list = []
        resume_calls: list = []
        monkeypatch.setattr(
            screen, "_prepare_tv_season_pick",
            lambda s: prep_calls.append(s),
        )
        monkeypatch.setattr(
            screen, "_resume_session",
            lambda s: resume_calls.append(s),
        )

        screen._route_after_read()

        assert resume_calls == [session]
        assert prep_calls == []

