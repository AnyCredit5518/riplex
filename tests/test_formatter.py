"""Tests for the formatter module."""

import json

from plex_planner.formatter import to_dict, to_json, to_text
from plex_planner.models import PlannedEpisode, PlannedMovie, PlannedSeason, PlannedShow


def _sample_movie() -> PlannedMovie:
    return PlannedMovie(
        canonical_title="Oppenheimer",
        year=2023,
        runtime="3h 1m",
        runtime_seconds=10860,
        relative_paths=[
            "\\Movies\\Oppenheimer (2023)\\",
            "\\Movies\\Oppenheimer (2023)\\Featurettes\\",
        ],
        main_file="Oppenheimer (2023).mkv",
    )


def _sample_show() -> PlannedShow:
    return PlannedShow(
        canonical_title="A Perfect Planet",
        year=2021,
        relative_paths=[
            "\\TV Shows\\A Perfect Planet (2021)\\Season 00\\",
            "\\TV Shows\\A Perfect Planet (2021)\\Season 01\\",
        ],
        seasons=[
            PlannedSeason(
                season_number=0,
                episodes=[
                    PlannedEpisode(
                        season_number=0,
                        episode_number=1,
                        title="Making a Perfect Planet",
                        runtime="44m",
                        runtime_seconds=2640,
                        file_name="A Perfect Planet (2021) - s00e01 - Making a Perfect Planet.mkv",
                    )
                ],
            ),
            PlannedSeason(
                season_number=1,
                episodes=[
                    PlannedEpisode(
                        season_number=1,
                        episode_number=1,
                        title="Volcano",
                        runtime="48m",
                        runtime_seconds=2880,
                        file_name="A Perfect Planet (2021) - s01e01 - Volcano.mkv",
                    )
                ],
            ),
        ],
    )


class TestMovieFormatter:
    def test_to_dict(self):
        d = to_dict(_sample_movie())
        assert d["type"] == "movie"
        assert d["canonical_title"] == "Oppenheimer"
        assert d["year"] == 2023
        assert d["runtime"] == "3h 1m"
        assert d["main_file"] == "Oppenheimer (2023).mkv"
        assert len(d["relative_paths"]) == 2

    def test_to_json_is_valid(self):
        j = to_json(_sample_movie())
        parsed = json.loads(j)
        assert parsed["type"] == "movie"

    def test_to_text(self):
        text = to_text(_sample_movie())
        assert "type: movie" in text
        assert "Oppenheimer" in text
        assert "3h 1m" in text


class TestShowFormatter:
    def test_to_dict(self):
        d = to_dict(_sample_show())
        assert d["type"] == "tv"
        assert d["canonical_title"] == "A Perfect Planet"
        assert d["year"] == 2021
        assert len(d["seasons"]) == 2
        assert d["seasons"][0]["season_number"] == 0
        assert d["seasons"][0]["episodes"][0]["title"] == "Making a Perfect Planet"

    def test_to_json_is_valid(self):
        j = to_json(_sample_show())
        parsed = json.loads(j)
        assert parsed["type"] == "tv"
        assert len(parsed["seasons"]) == 2

    def test_to_text(self):
        text = to_text(_sample_show())
        assert "type: tv" in text
        assert "A Perfect Planet" in text
        assert "s00e01" in text
        assert "Volcano" in text
