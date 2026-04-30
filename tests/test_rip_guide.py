"""Tests for the rip-guide subcommand."""

import json

import pytest

from riplex.cli import (
    _create_rip_folders,
    _disc_role,
    _format_seconds,
    _print_rip_guide,
    _rip_guide_json,
)
from riplex.models import PlannedDisc, PlannedEpisode, PlannedExtra


# ---------------------------------------------------------------------------
# _format_seconds
# ---------------------------------------------------------------------------


class TestFormatSeconds:
    def test_minutes_and_seconds(self):
        assert _format_seconds(125) == "2:05"

    def test_hours(self):
        assert _format_seconds(3661) == "1:01:01"

    def test_zero(self):
        assert _format_seconds(0) == "0:00"

    def test_exact_hour(self):
        assert _format_seconds(3600) == "1:00:00"

    def test_under_a_minute(self):
        assert _format_seconds(45) == "0:45"


# ---------------------------------------------------------------------------
# _print_rip_guide
# ---------------------------------------------------------------------------


def _make_movie_discs():
    """Create a typical 2-disc movie release (film + extras)."""
    return [
        PlannedDisc(
            number=1,
            disc_format="Blu-ray 4K",
            is_film=True,
            extras=[],
        ),
        PlannedDisc(
            number=2,
            disc_format="Blu-ray",
            is_film=False,
            extras=[
                PlannedExtra(title="Making Of", runtime_seconds=1800, feature_type="featurettes"),
                PlannedExtra(title="Trailer", runtime_seconds=120, feature_type="trailers"),
            ],
        ),
    ]


def _make_tv_discs():
    """Create a typical TV disc with episodes (play-all children)."""
    return [
        PlannedDisc(
            number=1,
            disc_format="Blu-ray",
            is_film=False,
            episodes=[
                PlannedEpisode(season_number=0, episode_number=1, title="Episode 1", runtime="", runtime_seconds=3000),
                PlannedEpisode(season_number=0, episode_number=2, title="Episode 2", runtime="", runtime_seconds=3100),
                PlannedEpisode(season_number=0, episode_number=3, title="Episode 3", runtime="", runtime_seconds=2900),
            ],
        ),
    ]


class TestPrintRipGuide:
    def test_movie_with_discs(self, capsys):
        discs = _make_movie_discs()
        _print_rip_guide("Blade Runner", 1982, True, 7051, discs)
        out = capsys.readouterr().out

        assert "Blade Runner (1982) [Movie]" in out
        assert "Disc 1" in out
        assert "MAIN FILM" in out
        assert "Disc 2" in out
        assert "Making Of" in out
        assert "Trailer" in out
        assert "Rips/Blade Runner (1982)/Disc 1/" in out
        assert "Rips/Blade Runner (1982)/Disc 2/" in out

    def test_tv_with_episodes(self, capsys):
        discs = _make_tv_discs()
        _print_rip_guide("Frozen Planet II", 2022, False, None, discs)
        out = capsys.readouterr().out

        assert "Frozen Planet II (2022) [TV Show]" in out
        assert "Episode 1 (50:00)" in out
        assert "Episode 2 (51:40)" in out
        assert "Episode 3 (48:20)" in out
        assert "play-all" in out.lower() or "play" in out.lower()

    def test_no_dvdcompare_data(self, capsys):
        _print_rip_guide("Unknown Movie", 2020, True, 6000, [])
        out = capsys.readouterr().out

        assert "No dvdcompare disc data available" in out
        assert "1:40:00" in out  # 6000 seconds
        assert "riplex organize" in out

    def test_extras_disc_tip(self, capsys):
        discs = _make_movie_discs()
        _print_rip_guide("Blade Runner", 1982, True, 7051, discs)
        out = capsys.readouterr().out

        assert "Extras are on disc 2" in out
        assert "Main film is on disc 1" in out

    def test_organize_command_shown(self, capsys):
        discs = _make_movie_discs()
        _print_rip_guide("Blade Runner", 1982, True, 7051, discs)
        out = capsys.readouterr().out

        assert 'riplex organize "Blade Runner (1982)"' in out

    def test_movie_play_all_extras_not_labeled_episodes(self, capsys):
        """For movies, play-all children on non-film disc show as extras, not episodes."""
        discs = [
            PlannedDisc(number=1, disc_format="Blu-ray 4K", is_film=True),
            PlannedDisc(
                number=2,
                disc_format="Blu-ray",
                is_film=False,
                episodes=[
                    PlannedEpisode(season_number=0, episode_number=1, title="Behind the Scenes Part 1", runtime="", runtime_seconds=1200),
                    PlannedEpisode(season_number=0, episode_number=2, title="Behind the Scenes Part 2", runtime="", runtime_seconds=1300),
                ],
                extras=[
                    PlannedExtra(title="Trailer", runtime_seconds=120, feature_type="trailers"),
                ],
            ),
        ]
        _print_rip_guide("Oppenheimer", 2023, True, 10812, discs)
        out = capsys.readouterr().out

        # Should NOT say "Episodes" for a movie extras disc
        lines = out.split("\n")
        disc2_section = "\n".join(lines[lines.index(next(l for l in lines if "Disc 2" in l)):])
        assert "Episodes (" not in disc2_section
        assert "play-all group" in disc2_section
        assert "Behind the Scenes Part 1" in out
        # Disc 2 role should be "extras" not "episodes"
        assert "(extras)" in out


# ---------------------------------------------------------------------------
# _disc_role
# ---------------------------------------------------------------------------


class TestDiscRole:
    def test_film_disc(self):
        disc = PlannedDisc(number=1, disc_format="Blu-ray 4K", is_film=True)
        assert _disc_role(disc, is_movie=True) == " (main film)"
        assert _disc_role(disc, is_movie=False) == " (main film)"

    def test_movie_extras_disc_with_episodes(self):
        disc = PlannedDisc(
            number=2, disc_format="Blu-ray", is_film=False,
            episodes=[PlannedEpisode(0, 1, "BTS", "", 600)],
        )
        assert _disc_role(disc, is_movie=True) == " (extras)"

    def test_tv_episodes_disc(self):
        disc = PlannedDisc(
            number=1, disc_format="Blu-ray", is_film=False,
            episodes=[PlannedEpisode(0, 1, "Ep 1", "", 3000)],
        )
        assert _disc_role(disc, is_movie=False) == " (episodes)"

    def test_tv_mixed_disc(self):
        disc = PlannedDisc(
            number=1, disc_format="Blu-ray", is_film=False,
            episodes=[PlannedEpisode(0, 1, "Ep 1", "", 3000)],
            extras=[PlannedExtra(title="BTS", runtime_seconds=600)],
        )
        assert _disc_role(disc, is_movie=False) == " (episodes + extras)"

    def test_empty_disc(self):
        disc = PlannedDisc(number=1, disc_format="Blu-ray", is_film=False)
        assert _disc_role(disc, is_movie=True) == ""
        assert _disc_role(disc, is_movie=False) == ""


# ---------------------------------------------------------------------------
# _rip_guide_json
# ---------------------------------------------------------------------------


class TestRipGuideJson:
    def test_movie_json(self):
        discs = _make_movie_discs()
        raw = _rip_guide_json("Blade Runner", 1982, True, 7051, discs)
        data = json.loads(raw)

        assert data["title"] == "Blade Runner"
        assert data["year"] == 1982
        assert data["media_type"] == "movie"
        assert data["movie_runtime_seconds"] == 7051
        assert data["recommended_folder"] == "Blade Runner (1982)"
        assert len(data["discs"]) == 2

    def test_tv_json(self):
        discs = _make_tv_discs()
        raw = _rip_guide_json("Frozen Planet II", 2022, False, None, discs)
        data = json.loads(raw)

        assert data["media_type"] == "tv"
        assert data["movie_runtime_seconds"] is None
        assert len(data["discs"]) == 1
        assert len(data["discs"][0]["episodes"]) == 3

    def test_empty_discs_json(self):
        raw = _rip_guide_json("Unknown", 2020, True, 5000, [])
        data = json.loads(raw)

        assert data["discs"] == []


# ---------------------------------------------------------------------------
# _create_rip_folders
# ---------------------------------------------------------------------------


class TestCreateRipFolders:
    def test_creates_disc_folders(self, tmp_path):
        discs = _make_movie_discs()
        root = tmp_path / "Blade Runner (1982)"
        created = _create_rip_folders(root, discs)

        assert len(created) == 2
        assert (root / "Disc 1").is_dir()
        assert (root / "Disc 2").is_dir()

    def test_idempotent(self, tmp_path):
        discs = _make_movie_discs()
        root = tmp_path / "Blade Runner (1982)"
        _create_rip_folders(root, discs)
        # Second call should not re-create
        created = _create_rip_folders(root, discs)
        assert len(created) == 0

    def test_empty_discs(self, tmp_path):
        root = tmp_path / "Unknown (2020)"
        created = _create_rip_folders(root, [])
        assert created == []
