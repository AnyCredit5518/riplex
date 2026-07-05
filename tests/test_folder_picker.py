"""Tests for the folder-picker screen's title/season inference."""

import json

from riplex_app.screens.folder_picker import _read_title_and_season_from_manifests


def _write_manifest(folder, *, title, kind="tv"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "_rip_manifest.json").write_text(
        json.dumps({"title": title, "type": kind, "year": 2006, "disc_number": 1}),
        encoding="utf-8",
    )


class TestReadTitleAndSeasonFromManifests:
    """The organize folder-picker prefers the title recorded at rip
    time over any folder-name heuristic. Prevents ``Season 01`` from
    ending up as the "detected" title when the user points at a
    season-nested work-folder."""

    def test_reads_title_from_first_disc_manifest(self, tmp_path):
        season = tmp_path / "Psych (2006)" / "Season 01"
        _write_manifest(season / "Disc 1", title="Psych", kind="tv")
        _write_manifest(season / "Disc 2", title="Psych", kind="tv")

        title, s, media_type = _read_title_and_season_from_manifests(season)
        assert title == "Psych"
        assert s == 1
        assert media_type == "tv"

    def test_walks_up_to_parent_when_season_is_on_parent(self, tmp_path):
        """User picked the movie ``Batman Begins`` root (no ``Season``
        segment in path) — season stays ``None`` for movies."""
        root = tmp_path / "Batman Begins (2005)"
        _write_manifest(root / "Disc 1", title="Batman Begins", kind="movie")

        title, s, media_type = _read_title_and_season_from_manifests(root)
        assert title == "Batman Begins"
        assert s is None
        assert media_type == "movie"

    def test_returns_none_for_folder_without_manifests(self, tmp_path):
        # Simulates an organize source produced outside riplex.
        (tmp_path / "Disc 1").mkdir(parents=True)
        (tmp_path / "Disc 1" / "somefile.mkv").write_bytes(b"")

        title, s, media_type = _read_title_and_season_from_manifests(tmp_path)
        assert title is None
        assert s is None
        assert media_type is None

    def test_ignores_malformed_manifest(self, tmp_path):
        disc = tmp_path / "Disc 1"
        disc.mkdir(parents=True)
        (disc / "_rip_manifest.json").write_text("{not json", encoding="utf-8")

        title, s, media_type = _read_title_and_season_from_manifests(tmp_path)
        # Malformed first manifest → skip and keep looking; nothing else
        # here, so everything is None.
        assert title is None
        assert s is None
        assert media_type is None

    def test_tv_manifest_at_flat_layout_has_no_recoverable_season(self, tmp_path):
        """Legacy pre-Season-NN layout: ``Psych (2006)/Disc N`` with a
        TV manifest inside. Title still resolves; season is None
        because the folder name doesn't carry it."""
        root = tmp_path / "Psych (2006)"
        _write_manifest(root / "Disc 1", title="Psych", kind="tv")

        title, s, media_type = _read_title_and_season_from_manifests(root)
        assert title == "Psych"
        assert s is None
        assert media_type == "tv"
