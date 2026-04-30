"""Tests for disc_provider conversion logic."""

import pytest

from dvdcompare.models import Disc, Feature, FilmComparison, Release

from riplex.disc_provider import _clean_feature_type, _convert_film


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
        assert len(d.extras) == 2
        assert d.extras[0].title == "To End All War"
        assert d.extras[0].runtime_seconds == 87 * 60 + 18
        assert d.extras[0].feature_type == "documentary"
        assert d.extras[1].title == "Innovations in Film"

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
        assert d.extras == []

    def test_disc_three_mixed(self):
        discs = _convert_film(_planet_earth_film())
        d = discs[1]  # second in our fixture (disc 3)
        assert d.number == 3
        assert len(d.episodes) == 2
        assert d.episodes[0].title == "Human"
        assert d.episodes[1].title == "Heroes"
        assert len(d.extras) == 1
        assert d.extras[0].title == "Making of Planet Earth III"
        assert d.extras[0].feature_type == "behind-the-scenes montage"


class TestConvertFilmEdgeCases:
    def test_no_releases(self):
        film = FilmComparison(title="Empty", releases=[])
        assert _convert_film(film) == []

    def test_release_not_found_raises(self):
        film = _oppenheimer_film()
        with pytest.raises(LookupError):
            _convert_film(film, "nonexistent")
