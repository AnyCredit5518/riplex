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
