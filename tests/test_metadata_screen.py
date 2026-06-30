from riplex.metadata.provider import MetadataSearchResult
from riplex_app.screens.metadata import MetadataScreen


class _App:
    def __init__(self, state):
        self.state = state
        self.navigated_to = None

    def navigate(self, screen):
        self.navigated_to = screen


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
        # A TV match navigates straight to the release lookup.
        assert app.navigated_to == "release"
