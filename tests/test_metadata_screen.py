from unittest.mock import MagicMock

from riplex.metadata.provider import MetadataSearchResult
from riplex_app.screens.metadata import MetadataScreen


class _App:
    def __init__(self, state):
        self.state = state
        self.navigated_to = None
        self.navigation_calls: list[str] = []
        self.page = MagicMock()

    def navigate(self, screen):
        self.navigated_to = screen
        self.navigation_calls.append(screen)


class _RadioGroup:
    def __init__(self, value):
        self.value = value


def _result(title, media_type="tv", year=2000):
    return MetadataSearchResult(
        source_id=f"{media_type}:1",
        title=title,
        year=year,
        media_type=media_type,
        overview="",
        popularity=1.0,
    )


def test_loading_build_starts_one_search_worker(monkeypatch):
    started: list = []

    class _DeferredThread:
        def __init__(self, *, target, daemon, name=None, args=()):
            started.append((target, args))

        def start(self):
            pass

    monkeypatch.setattr("riplex_app.background.threading.Thread", _DeferredThread)
    app = _App({"title": "Psych"})
    screen = MetadataScreen(app)

    screen.build()
    screen.build()

    assert len(started) == 1


def test_search_button_submits_client_side_title_edit():
    app = _App({"title": "2fast2furious Upk1 Global"})
    screen = MetadataScreen(app)
    screen._build_error_view("2fast2furious Upk1 Global", "No results found")

    assert screen._search_field.on_change is not None
    screen._search_field.on_change(
        MagicMock(control=MagicMock(value="2 Fast 2 Furious")),
    )
    screen._on_search_click(None)

    assert app.state["title"] == "2 Fast 2 Furious"
    assert app.navigation_calls == ["metadata"]


def test_empty_results_clear_stale_submission_before_manual_search():
    app = _App({"title": "Fftokyodrift Uhd Upk75"})
    screen = MetadataScreen(app)
    screen._submitting = True
    screen.tmdb_results = []

    screen._build_results_view("Fftokyodrift Uhd Upk75")
    screen._search_field.on_change(
        MagicMock(control=MagicMock(value="The Fast and the Furious: Tokyo Drift")),
    )
    screen._on_search_click(None)

    assert app.state["title"] == "The Fast and the Furious: Tokyo Drift"
    assert app.navigation_calls == ["metadata"]


def test_late_search_completion_does_not_restore_metadata(monkeypatch):
    workers: list = []

    class _DeferredThread:
        def __init__(self, *, target, daemon, name=None, args=()):
            workers.append(target)

        def start(self):
            pass

    class _Provider:
        def __init__(self, _api_key):
            pass

        async def search(self, _title):
            return [_result("Psych")]

        async def close(self):
            pass

    monkeypatch.setattr("riplex_app.background.threading.Thread", _DeferredThread)
    monkeypatch.setattr("riplex_app.screens.metadata.get_api_key", lambda: "key")
    monkeypatch.setattr("riplex_app.screens.metadata.TmdbProvider", _Provider)
    app = _App({"title": "Psych"})
    app._current_screen_name = "metadata"
    app._navigation_epoch = 2
    screen = MetadataScreen(app)
    screen.build()

    app._current_screen_name = "disc_detection"
    app._navigation_epoch += 1
    workers[0]()

    assert "_tmdb_results" not in app.state
    assert app.navigation_calls == []


def test_old_show_detail_does_not_overwrite_new_selection(monkeypatch):
    old_detail = object()

    class _Provider:
        def __init__(self, _api_key):
            pass

        async def get_show_detail(self, _source_id, *, include_specials):
            return old_detail

        async def close(self):
            pass

    monkeypatch.setattr("riplex_app.screens.metadata.get_api_key", lambda: "key")
    monkeypatch.setattr("riplex_app.screens.metadata.TmdbProvider", _Provider)
    current_detail = object()
    app = _App({
        "tmdb_match": _result("New Show"),
        "show_detail": current_detail,
    })
    screen = MetadataScreen(app)

    screen._fetch_show_detail("tv:old")

    assert app.state["show_detail"] is current_detail


def test_detail_submission_disables_and_rejects_search(monkeypatch):
    started: list = []

    class _DeferredThread:
        def __init__(self, *, target, daemon, name=None, args=()):
            started.append((target, args))

        def start(self):
            pass

    monkeypatch.setattr("riplex_app.background.threading.Thread", _DeferredThread)
    app = _App({"title": "Psych"})
    screen = MetadataScreen(app)
    screen.tmdb_results = [_result("Psych")]
    screen._build_results_view("Psych")

    screen._next(None)
    screen._search_field.value = "Monk"
    screen._on_search_click(None)

    assert len(started) == 1
    assert app.state["title"] == "Psych"
    assert app.navigation_calls == ["season_select"]
    assert screen._search_field.disabled
    assert screen._search_button.disabled


def test_old_show_detail_does_not_overwrite_new_same_id_selection(monkeypatch):
    workers: list = []
    old_detail = object()
    new_detail = object()
    old_match = _result("Psych")
    new_match = _result("Psych")

    class _DeferredThread:
        def __init__(self, *, target, daemon, name=None, args=()):
            self.target = target
            workers.append(self)

        def start(self):
            pass

    app = _App({"title": "Psych"})

    class _Provider:
        def __init__(self, _api_key):
            pass

        async def get_show_detail(self, _source_id, *, include_specials):
            app.state["tmdb_match"] = new_match
            app.state["show_detail"] = new_detail
            return old_detail

        async def close(self):
            pass

    monkeypatch.setattr("riplex_app.background.threading.Thread", _DeferredThread)
    monkeypatch.setattr("riplex_app.screens.metadata.get_api_key", lambda: "key")
    monkeypatch.setattr("riplex_app.screens.metadata.TmdbProvider", _Provider)
    screen = MetadataScreen(app)
    screen.tmdb_results = [old_match]
    screen._build_results_view("Psych")

    screen._next(None)
    workers[-1].target()

    assert app.state["tmdb_match"] is new_match
    assert app.state["show_detail"] is new_detail


class TestMetadataNextClearsStaleDvdcompare:
    def test_new_match_clears_previous_release_and_discs(self):
        # Simulate stale dvdcompare selection left over from a prior film in
        # the same app session (e.g. just finished "The Last Reef").
        app = _App({
            "title": "The Patriot",
            "release": object(),
            "dvdcompare_discs": [object(), object()],
            "_dvdcompare_film": object(),
            "_dvdcompare_error": "stale error",
            "dvdcompare_title_override": "The Last Reef",
        })
        screen = MetadataScreen(app)
        screen.tmdb_results = [_result("The Patriot")]
        screen.radio_group = _RadioGroup("0")

        screen._next(None)

        # The freshly chosen film must not inherit the previous film's discs.
        assert app.state["release"] is None
        assert app.state["dvdcompare_discs"] == []
        assert "_dvdcompare_film" not in app.state
        assert "_dvdcompare_error" not in app.state
        assert "dvdcompare_title_override" not in app.state
        assert app.state["tmdb_match"].title == "The Patriot"
        # A TV match routes through season_select so the dvdcompare query
        # can be biased with ": Season N" before the release picker runs.
        assert app.navigated_to == "season_select"

    def test_duplicate_next_starts_one_detail_worker_and_shows_busy_state(
        self, monkeypatch,
    ):
        started: list = []

        class _DeferredThread:
            def __init__(self, *, target, daemon, name=None, args=()):
                started.append((target, args))

            def start(self):
                pass

        monkeypatch.setattr(
            "riplex_app.background.threading.Thread",
            _DeferredThread,
        )
        app = _App({"title": "Psych"})
        screen = MetadataScreen(app)
        screen.tmdb_results = [_result("Psych")]
        screen._build_results_view("Psych")

        screen._next(None)
        screen._next(None)

        assert len(started) == 1
        assert app.navigation_calls == ["season_select"]
        assert screen.radio_group.disabled
        assert screen._next_button.disabled
        assert screen._busy_status.visible
