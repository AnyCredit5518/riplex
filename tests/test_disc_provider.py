"""Tests for disc_provider conversion logic."""

import pytest

from dvdcompare.models import Disc, Feature, FilmComparison, Release

from riplex.disc.provider import _clean_feature_type, _convert_film


class TestCleanFeatureType:
    def test_strips_parenthetical_annotations(self):
        assert _clean_feature_type("featurettes (with Play All)  (1080p)") == "featurettes"

    def test_simple_type_unchanged(self):
        assert _clean_feature_type("documentary") == "documentary"

    def test_hyphenated_type_unchanged(self):
        assert _clean_feature_type("behind-the-scenes montage") == "behind-the-scenes montage"

    def test_empty_string(self):
        assert _clean_feature_type("") == ""


def _oppenheimer_film():
    """Minimal Oppenheimer-like FilmComparison for testing."""
    return FilmComparison(
        title="Oppenheimer",
        year=2023,
        format="Blu-ray 4K",
        film_id=66397,
        releases=[
            Release(
                name="Blu-ray ALL America - Universal Pictures",
                year=2023,
                discs=[
                    Disc(number=1, format="Blu-ray 4K", is_film=True),
                    Disc(number=2, format="Blu-ray", is_film=True),
                    Disc(
                        number=3,
                        format="Blu-ray",
                        features=[
                            Feature(
                                title="To End All War",
                                runtime_seconds=87 * 60 + 18,
                                feature_type="documentary",
                                year=2023,
                            ),
                            Feature(
                                title="The Story of Our Time",
                                runtime_seconds=72 * 60 + 25,
                                is_play_all=True,
                                children=[
                                    Feature(title="Now I Am Become Death", runtime_seconds=7 * 60 + 17),
                                    Feature(title="The Luminaries", runtime_seconds=12 * 60 + 2),
                                ],
                            ),
                            Feature(title="Innovations in Film", runtime_seconds=8 * 60 + 21, feature_type="featurette"),
                        ],
                    ),
                ],
            ),
            Release(
                name="Blu-ray ALL Japan - Universal Pictures",
                year=2024,
                discs=[
                    Disc(number=1, format="Blu-ray 4K", is_film=True),
                ],
            ),
        ],
    )


def _planet_earth_film():
    """Minimal Planet Earth III-like FilmComparison for testing."""
    return FilmComparison(
        title="Planet Earth III (TV)",
        year=2023,
        format="Blu-ray 4K",
        film_id=67210,
        releases=[
            Release(
                name="Blu-ray ALL America - BBC",
                year=2024,
                discs=[
                    Disc(
                        number=1,
                        format="Blu-ray 4K",
                        features=[
                            Feature(
                                title="Episodes",
                                runtime_seconds=154 * 60 + 35,
                                is_play_all=True,
                                children=[
                                    Feature(title="Coasts", runtime_seconds=52 * 60 + 21),
                                    Feature(title="Ocean", runtime_seconds=52 * 60 + 30),
                                    Feature(title="Deserts & Grasslands", runtime_seconds=49 * 60 + 43),
                                ],
                            ),
                        ],
                    ),
                    Disc(
                        number=3,
                        format="Blu-ray 4K",
                        features=[
                            Feature(
                                title="Episodes",
                                runtime_seconds=105 * 60 + 46,
                                is_play_all=True,
                                children=[
                                    Feature(title="Human", runtime_seconds=51 * 60 + 49),
                                    Feature(title="Heroes", runtime_seconds=53 * 60 + 56),
                                ],
                            ),
                            Feature(
                                title="Making of Planet Earth III",
                                runtime_seconds=54 * 60 + 15,
                                feature_type="behind-the-scenes montage",
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


class TestConvertFilmOppenheimer:
    def test_disc_count(self):
        discs = _convert_film(_oppenheimer_film())
        assert len(discs) == 3

    def test_disc_one_is_film(self):
        discs = _convert_film(_oppenheimer_film())
        assert discs[0].number == 1
        assert discs[0].disc_format == "Blu-ray 4K"
        assert discs[0].is_film is True
        assert discs[0].episodes == []
        assert discs[0].extras == []

    def test_disc_three_extras(self):
        discs = _convert_film(_oppenheimer_film())
        d = discs[2]
        assert d.number == 3
        assert d.is_film is False
        # "To End All War" and "Innovations" are extras, "Story of Our Time" children are episodes
        # Play-all parent also added as extra for duration matching
        assert len(d.extras) == 3
        assert d.extras[0].title == "To End All War"
        assert d.extras[0].runtime_seconds == 87 * 60 + 18
        assert d.extras[0].feature_type == "documentary"
        assert d.extras[1].title == "The Story of Our Time: Play All"
        assert d.extras[2].title == "Innovations in Film"

    def test_disc_three_play_all_children_become_episodes(self):
        discs = _convert_film(_oppenheimer_film())
        d = discs[2]
        assert len(d.episodes) == 2
        assert d.episodes[0].title == "Now I Am Become Death"
        assert d.episodes[0].runtime_seconds == 7 * 60 + 17
        assert d.episodes[1].title == "The Luminaries"

    def test_release_selector_by_keyword(self):
        discs = _convert_film(_oppenheimer_film(), "japan")
        assert len(discs) == 1
        assert discs[0].is_film is True


class TestConvertFilmPlanetEarth:
    def test_disc_count(self):
        discs = _convert_film(_planet_earth_film())
        assert len(discs) == 2

    def test_disc_one_episodes(self):
        discs = _convert_film(_planet_earth_film())
        d = discs[0]
        assert d.number == 1
        assert len(d.episodes) == 3
        assert d.episodes[0].title == "Coasts"
        assert d.episodes[1].title == "Ocean"
        assert d.episodes[2].title == "Deserts & Grasslands"
        # Play-all parent added as extra for duration matching
        assert len(d.extras) == 1
        assert d.extras[0].title == "Episodes: Play All"

    def test_disc_three_mixed(self):
        discs = _convert_film(_planet_earth_film())
        d = discs[1]  # second in our fixture (disc 3)
        assert d.number == 3
        assert len(d.episodes) == 2
        assert d.episodes[0].title == "Human"
        assert d.episodes[1].title == "Heroes"
        assert len(d.extras) == 2
        assert d.extras[0].title == "Episodes: Play All"
        assert d.extras[1].title == "Making of Planet Earth III"
        assert d.extras[1].feature_type == "behind-the-scenes montage"


class TestConvertFilmEdgeCases:
    def test_no_releases(self):
        film = FilmComparison(title="Empty", releases=[])
        assert _convert_film(film) == []

    def test_release_not_found_raises(self):
        film = _oppenheimer_film()
        with pytest.raises(LookupError):
            _convert_film(film, "nonexistent")

    def test_feature_pointer_fid_propagates_to_planned_extra(self):
        # dvdcompare Complete-Series pages hyperlink each bonus film's
        # title to its own film.php page; the scraper surfaces that as
        # ``Feature.pointer_fid``. The converter must thread it onto
        # ``PlannedExtra.pointer_fid`` so ``group_release_discs`` can
        # split the bonus-films disc into its own group.
        film = FilmComparison(
            title="Psych: Season 1 (TV)",
            year=2006,
            format="Blu-ray",
            film_id=66231,
            releases=[
                Release(
                    name="Blu-ray ALL America - Universal Pictures",
                    year=2020,
                    discs=[
                        Disc(
                            number=31,
                            format="",
                            is_film=False,
                            features=[
                                Feature(
                                    title="Psych: The Movie",
                                    runtime_seconds=88 * 60 + 10,
                                    pointer_fid=66239,
                                ),
                                Feature(
                                    title="Psych 2: Lassie Come Home",
                                    runtime_seconds=88 * 60 + 30,
                                    pointer_fid=66240,
                                ),
                                Feature(
                                    title="Psych 3: This Is Gus",
                                    runtime_seconds=96 * 60 + 22,
                                    pointer_fid=66241,
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )
        discs = _convert_film(film)
        assert len(discs) == 1
        d = discs[0]
        # Linked features must not be misclassified as episodes even
        # though the disc lacks ``is_film`` and the runtimes exceed the
        # 600s standalone-episode threshold.
        assert d.episodes == []
        assert len(d.extras) == 3
        assert [e.pointer_fid for e in d.extras] == [66239, 66240, 66241]
        assert [e.title for e in d.extras] == [
            "Psych: The Movie",
            "Psych 2: Lassie Come Home",
            "Psych 3: This Is Gus",
        ]


class TestBoxsetWithQuotedTitleDiscs:
    """Boxset releases where the scraper now splits inline quoted-title
    DISC headers into separate physical discs (e.g. BTTF 40th Anniversary)."""

    def test_each_physical_disc_becomes_a_planned_disc(self):
        # Mirrors what dvdcompare-scraper >= 0.1.15 produces for boxsets
        # that previously glued multiple physical discs into one entry.
        film = FilmComparison(
            title="Back to the Future",
            year=1985,
            format="Blu-ray 4K",
            releases=[
                Release(
                    name="40th Anniversary Trilogy",
                    year=2025,
                    discs=[
                        Disc(number=1, format="Blu-ray 4K",
                             title="Back to the Future", is_film=True),
                        Disc(number=2, format="Blu-ray",
                             title="Back to the Future", is_film=True),
                        Disc(number=3, format="Blu-ray 4K",
                             title="Back to the Future Part II", is_film=True),
                        Disc(number=4, format="Blu-ray",
                             title="Back to the Future Part II", is_film=True),
                        Disc(number=5, format="Blu-ray 4K",
                             title="Back to the Future Part III", is_film=True),
                        Disc(number=6, format="Blu-ray",
                             title="Back to the Future Part III", is_film=True),
                        Disc(number=7, format="", is_film=False,
                             features=[Feature(title="Bonus", runtime_seconds=600)]),
                        Disc(number=8, format="", is_film=False,
                             features=[Feature(title="40th Anniversary Bonus",
                                               runtime_seconds=1200)]),
                    ],
                ),
            ],
        )

        planned = _convert_film(film)
        assert len(planned) == 8
        assert [d.number for d in planned] == [1, 2, 3, 4, 5, 6, 7, 8]
        assert planned[0].disc_format == "Blu-ray 4K"
        assert planned[0].is_film is True
        assert planned[5].disc_format == "Blu-ray"
        assert planned[5].is_film is True
        assert planned[6].is_film is False
        assert planned[7].is_film is False

class TestFilmUrl:
    def test_film_url_int(self):
        from riplex.disc.provider import film_url
        assert film_url(55540) == "https://www.dvdcompare.net/comparisons/film.php?fid=55540"

    def test_film_url_str(self):
        from riplex.disc.provider import film_url
        assert film_url("55540") == "https://www.dvdcompare.net/comparisons/film.php?fid=55540"


class TestParseFilmId:
    def test_bare_digits(self):
        from riplex.disc.provider import parse_film_id
        assert parse_film_id("55540") == 55540

    def test_full_url(self):
        from riplex.disc.provider import parse_film_id
        assert parse_film_id("https://www.dvdcompare.net/comparisons/film.php?fid=55540") == 55540

    def test_url_with_anchor(self):
        from riplex.disc.provider import parse_film_id
        assert parse_film_id("https://www.dvdcompare.net/comparisons/film.php?fid=55540#2") == 55540

    def test_query_fragment(self):
        from riplex.disc.provider import parse_film_id
        assert parse_film_id("fid=12345") == 12345

    def test_whitespace_stripped(self):
        from riplex.disc.provider import parse_film_id
        assert parse_film_id("  55540  ") == 55540

    def test_garbage_returns_none(self):
        from riplex.disc.provider import parse_film_id
        assert parse_film_id("not a film id") is None

    def test_empty_returns_none(self):
        from riplex.disc.provider import parse_film_id
        assert parse_film_id("") is None

    def test_whitespace_only_returns_none(self):
        from riplex.disc.provider import parse_film_id
        assert parse_film_id("   ") is None


class TestTitleLead:
    """Coverage for the dvdcompare title-lead normalizer used to filter
    search results before ranking."""

    def test_bare_query(self):
        from riplex.disc.provider import _title_lead
        assert _title_lead("Psych") == "psych"

    def test_strips_year_and_format(self):
        from riplex.disc.provider import _title_lead
        raw = "Psych: Season 1 (TV) (Blu-ray)\t\t\t\t(2006-2007)"
        assert _title_lead(raw) == "psych: season 1"

    def test_strips_year_range_slash(self):
        from riplex.disc.provider import _title_lead
        raw = "Blood of Ghastly Horror\t\t\t\t(1964/1971)"
        assert _title_lead(raw) == "blood of ghastly horror"

    def test_strips_aka_alias(self):
        from riplex.disc.provider import _title_lead
        raw = "Psych:9 AKA Psych 9 (Blu-ray)\t\t\t\t(2010)"
        assert _title_lead(raw) == "psych:9"

    def test_strips_multiple_annotations(self):
        from riplex.disc.provider import _title_lead
        raw = "American Psycho (Blu-ray 4K)\t\t\t\t(2000)"
        assert _title_lead(raw) == "american psycho"

    def test_empty(self):
        from riplex.disc.provider import _title_lead
        assert _title_lead("") == ""


class TestTitleMatchesQuery:
    """The lead-match check that filters dvdcompare search results."""

    def test_exact_match(self):
        from riplex.disc.provider import _title_matches_query
        assert _title_matches_query("Psych\t\t(2020)", "psych")

    def test_matches_before_colon(self):
        from riplex.disc.provider import _title_matches_query
        raw = "Psych: Season 1 (TV) (Blu-ray)\t\t(2006-2007)"
        assert _title_matches_query(raw, "psych")

    def test_rejects_superstring(self):
        from riplex.disc.provider import _title_matches_query
        assert not _title_matches_query("Psycho\t\t(1960)", "psych")
        assert not _title_matches_query(
            "American Psycho (Blu-ray)\t\t(2000)", "psych",
        )

    def test_rejects_hyphen_extension(self):
        from riplex.disc.provider import _title_matches_query
        assert not _title_matches_query("Psych-Out\t\t(1968)", "psych")

    def test_rejects_numeric_sequel(self):
        from riplex.disc.provider import _title_matches_query
        raw = "Psych 2: Lassie Come Home (TV) (Blu-ray)\t\t(2020)"
        assert not _title_matches_query(raw, "psych")

    def test_empty_query_returns_false(self):
        from riplex.disc.provider import _title_matches_query
        assert not _title_matches_query("Psych\t\t(2020)", "")


class TestResultHasFormat:
    """Format matching from either sr.disc_format or the raw title text."""

    class _Fake:
        def __init__(self, title, disc_format=None):
            self.title = title
            self.disc_format = disc_format

    def test_disc_format_field_matches(self):
        from riplex.disc.provider import _result_has_format
        sr = self._Fake("Something (Blu-ray)\t(2010)", disc_format="Blu-ray")
        assert _result_has_format(sr, "blu-ray")

    def test_falls_back_to_title_text(self):
        """Scraper often leaves disc_format=None even when title says '(Blu-ray)'."""
        from riplex.disc.provider import _result_has_format
        sr = self._Fake(
            "Psych: Season 1 (TV) (Blu-ray)\t(2006-2007)",
            disc_format=None,
        )
        assert _result_has_format(sr, "blu-ray")

    def test_blu_ray_does_not_match_blu_ray_4k(self):
        from riplex.disc.provider import _result_has_format
        sr = self._Fake(
            "Something (Blu-ray 4K)\t(2020)", disc_format=None,
        )
        assert not _result_has_format(sr, "blu-ray")

    def test_no_format_marker_returns_false(self):
        from riplex.disc.provider import _result_has_format
        sr = self._Fake("Something Else\t(1999)", disc_format=None)
        assert not _result_has_format(sr, "blu-ray")

    def test_empty_query_returns_false(self):
        from riplex.disc.provider import _result_has_format
        sr = self._Fake("Something (Blu-ray)\t(2010)", disc_format="Blu-ray")
        assert not _result_has_format(sr, "")


class TestFindFilmPreferFormat:
    """End-to-end coverage of _find_film_prefer_format ranking with mocked I/O."""

    @pytest.fixture
    def patch_scraper(self, monkeypatch):
        """Patch search / get_film_by_url in riplex.disc.provider."""
        from dvdcompare.models import SearchResult
        from riplex.disc import provider as prov

        calls = {"picked_url": None}

        async def _fake_search(_query):
            return self._psych_search_results(SearchResult)

        async def _fake_get_film_by_url(url, resolve_pointers=True):
            calls["picked_url"] = url
            return FilmComparison(title="mock", releases=[])

        monkeypatch.setattr(prov, "search", _fake_search)
        monkeypatch.setattr(prov, "get_film_by_url", _fake_get_film_by_url)
        return calls

    @staticmethod
    def _psych_search_results(SearchResult):
        """Alphabetically-ordered results matching a real dvdcompare 'Psych' search."""
        return [
            SearchResult(
                title="American Psycho\t\t\t\t(2000)",
                url="https://www.dvdcompare.net/comparisons/film.php?fid=53",
                year=2000,
            ),
            SearchResult(
                title="American Psycho (Blu-ray)\t\t\t\t(2000)",
                url="https://www.dvdcompare.net/comparisons/film.php?fid=10676",
                year=2000,
                disc_format="Blu-ray",
            ),
            SearchResult(
                title="Psych 2: Lassie Come Home (TV) (Blu-ray)\t\t\t\t(2020)",
                url="https://www.dvdcompare.net/comparisons/film.php?fid=66240",
                year=2020,
                disc_format="Blu-ray",
            ),
            SearchResult(
                title="Psych: Season 1 (TV)\t\t\t\t(2006-2007)",
                url="https://www.dvdcompare.net/comparisons/film.php?fid=17560",
            ),
            SearchResult(
                title="Psych: Season 1 (TV) (Blu-ray)\t\t\t\t(2006-2007)",
                url="https://www.dvdcompare.net/comparisons/film.php?fid=66231",
            ),
            SearchResult(
                title="Psych: Season 2 (TV) (Blu-ray)\t\t\t\t(2007-2008)",
                url="https://www.dvdcompare.net/comparisons/film.php?fid=66232",
            ),
            SearchResult(
                title="Psycho\t\t\t\t(1960)",
                url="https://www.dvdcompare.net/comparisons/film.php?fid=1",
                year=1960,
            ),
        ]

    def test_prefers_title_match_over_alphabetical_format_match(self, patch_scraper):
        """Regression: 'Psych' + Blu-ray must NOT pick 'American Psycho (Blu-ray)'."""
        import asyncio
        from riplex.disc.provider import _find_film_prefer_format

        asyncio.run(_find_film_prefer_format("Psych", "Blu-ray", None))
        picked = patch_scraper["picked_url"]
        assert "fid=66231" in picked, f"expected Psych S1 BD, got {picked}"

    def test_picks_correct_season_when_year_matches(self, patch_scraper):
        """When a year is supplied and a title-matching result has that exact year,
        prefer it over any earlier title-matching result."""
        import asyncio
        from dvdcompare.models import SearchResult
        from riplex.disc import provider as prov

        # Override search: give Season 2 a specific year so tier 1 (title+format+year) fires.
        async def _fake_search(_q):
            return [
                SearchResult(
                    title="Psych: Season 1 (TV) (Blu-ray)\t\t\t\t(2006-2007)",
                    url="https://www.dvdcompare.net/comparisons/film.php?fid=66231",
                    year=None,
                ),
                SearchResult(
                    title="Psych: Season 2 (TV) (Blu-ray)\t\t\t\t(2007-2008)",
                    url="https://www.dvdcompare.net/comparisons/film.php?fid=66232",
                    year=2007,
                    disc_format="Blu-ray",
                ),
            ]

        import pytest as _pytest
        monkeypatch = _pytest.MonkeyPatch()
        monkeypatch.setattr(prov, "search", _fake_search)
        try:
            from riplex.disc.provider import _find_film_prefer_format
            asyncio.run(_find_film_prefer_format("Psych", "Blu-ray", 2007))
        finally:
            monkeypatch.undo()
        picked = patch_scraper["picked_url"]
        assert "fid=66232" in picked

    def test_falls_back_to_format_heuristic_when_no_title_match(
        self, monkeypatch,
    ):
        """If no result title-lead matches (weird query), we still return something."""
        import asyncio
        from dvdcompare.models import SearchResult
        from riplex.disc import provider as prov

        calls = {"picked_url": None}

        async def _fake_search(_q):
            return [
                SearchResult(
                    title="Totally Different Film (DVD)\t\t\t\t(2001)",
                    url="https://www.dvdcompare.net/comparisons/film.php?fid=999",
                    year=2001,
                    disc_format="DVD",
                ),
                SearchResult(
                    title="Totally Different Film (Blu-ray)\t\t\t\t(2001)",
                    url="https://www.dvdcompare.net/comparisons/film.php?fid=1000",
                    year=2001,
                    disc_format="Blu-ray",
                ),
            ]

        async def _fake_get_film_by_url(url, resolve_pointers=True):
            calls["picked_url"] = url
            return FilmComparison(title="mock", releases=[])

        monkeypatch.setattr(prov, "search", _fake_search)
        monkeypatch.setattr(prov, "get_film_by_url", _fake_get_film_by_url)

        from riplex.disc.provider import _find_film_prefer_format
        asyncio.run(_find_film_prefer_format("Psych", "Blu-ray", None))
        assert "fid=1000" in calls["picked_url"]

    def test_raises_on_no_results(self, monkeypatch):
        import asyncio
        from riplex.disc import provider as prov

        async def _fake_search(_q):
            return []

        monkeypatch.setattr(prov, "search", _fake_search)
        from riplex.disc.provider import _find_film_prefer_format

        with pytest.raises(LookupError):
            asyncio.run(_find_film_prefer_format("Nonexistent", "Blu-ray", None))


class TestStripDvdcompareAnnotations:
    """``strip_dvdcompare_annotations`` trims trailing format / year markers.

    The helper is used by the Disc Overview auto-fill worker before it
    queries TMDb — dvdcompare film titles include markers like ``(TV)``
    or ``(Blu-ray)`` which TMDb titles never carry, so leaving them in
    forces zero-result searches.
    """

    def test_strips_tv_marker(self):
        from riplex.disc.provider import strip_dvdcompare_annotations
        assert strip_dvdcompare_annotations("Psych: The Movie (TV)") == "Psych: The Movie"

    def test_strips_blu_ray_marker(self):
        from riplex.disc.provider import strip_dvdcompare_annotations
        assert strip_dvdcompare_annotations("Blade Runner (Blu-ray)") == "Blade Runner"

    def test_strips_blu_ray_4k_marker(self):
        from riplex.disc.provider import strip_dvdcompare_annotations
        assert strip_dvdcompare_annotations("Blade Runner (Blu-ray 4K)") == "Blade Runner"

    def test_strips_year_marker(self):
        from riplex.disc.provider import strip_dvdcompare_annotations
        assert strip_dvdcompare_annotations("Something (2020)") == "Something"

    def test_strips_stacked_markers(self):
        from riplex.disc.provider import strip_dvdcompare_annotations
        assert strip_dvdcompare_annotations("Psych: Season 1 (TV) (Blu-ray)") == "Psych: Season 1"

    def test_preserves_case(self):
        from riplex.disc.provider import strip_dvdcompare_annotations
        assert strip_dvdcompare_annotations("MacGyver (TV)") == "MacGyver"

    def test_no_marker_unchanged(self):
        from riplex.disc.provider import strip_dvdcompare_annotations
        assert strip_dvdcompare_annotations("Just A Title") == "Just A Title"

    def test_empty_returns_empty(self):
        from riplex.disc.provider import strip_dvdcompare_annotations
        assert strip_dvdcompare_annotations("") == ""



