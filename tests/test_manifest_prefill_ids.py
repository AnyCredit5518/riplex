"""Tests for optional identity fields in rip manifests: ``tmdb_source_id``,
``dvdcompare_film_id``, ``dvdcompare_release_name``.

The organize screen uses these to skip the TMDb picker and the
dvdcompare release picker when the manifest already recorded them at
rip time.
"""

import json
from unittest.mock import MagicMock

from riplex.manifest import (
    build_rip_manifest,
    build_snapshot_manifest,
    read_prefill_ids_from_manifests,
)


def _make_disc_info():
    di = MagicMock()
    di.titles = []
    return di


class TestBuildRipManifestIdentityFields:
    def test_omits_fields_when_not_provided(self):
        manifest = build_rip_manifest(
            canonical="Psych",
            year=2006,
            is_movie=False,
            disc_number=1,
            volume_label="PSYCH_S1_D1",
            disc_format="DVD",
            release_name="Psych: Season 1 (TV) (DVD)",
            disc_info=_make_disc_info(),
            rip_results=[],
            dvd_entries=[],
            movie_runtime=None,
            total_episode_runtime=0,
            episode_count=0,
        )
        assert "tmdb_source_id" not in manifest
        assert "dvdcompare_film_id" not in manifest
        assert "dvdcompare_release_name" not in manifest

    def test_includes_fields_when_provided(self):
        manifest = build_rip_manifest(
            canonical="Psych",
            year=2006,
            is_movie=False,
            disc_number=1,
            volume_label="PSYCH_S1_D1",
            disc_format="DVD",
            release_name="Psych: Season 1 (TV) (DVD)",
            disc_info=_make_disc_info(),
            rip_results=[],
            dvd_entries=[],
            movie_runtime=None,
            total_episode_runtime=0,
            episode_count=0,
            tmdb_source_id="tv:1447",
            dvdcompare_film_id=12345,
            dvdcompare_release_name="Psych: Season 1 (TV) (DVD)",
        )
        assert manifest["tmdb_source_id"] == "tv:1447"
        assert manifest["dvdcompare_film_id"] == 12345
        assert manifest["dvdcompare_release_name"] == "Psych: Season 1 (TV) (DVD)"


class TestBuildSnapshotManifestIdentityFields:
    def test_includes_fields_when_provided(self):
        manifest = build_snapshot_manifest(
            canonical="Psych",
            year=2006,
            is_movie=False,
            disc_number=1,
            volume_label="PSYCH_S1_D1",
            disc_format="DVD",
            release_name="Psych: Season 1 (TV) (DVD)",
            disc_info=_make_disc_info(),
            titles=[],
            dvd_entries=[],
            movie_runtime=None,
            total_episode_runtime=0,
            episode_count=0,
            tmdb_source_id="tv:1447",
            dvdcompare_film_id=12345,
            dvdcompare_release_name="Psych: Season 1 (TV) (DVD)",
        )
        assert manifest["tmdb_source_id"] == "tv:1447"
        assert manifest["dvdcompare_film_id"] == 12345
        assert manifest["dvdcompare_release_name"] == "Psych: Season 1 (TV) (DVD)"


def _write_manifest(disc_dir, data):
    disc_dir.mkdir(parents=True, exist_ok=True)
    (disc_dir / "_rip_manifest.json").write_text(json.dumps(data), encoding="utf-8")


class TestReadPrefillIdsFromManifests:
    def test_reads_all_three_from_first_disc(self, tmp_path):
        _write_manifest(tmp_path / "Disc 1", {
            "title": "Psych",
            "type": "tv",
            "tmdb_source_id": "tv:1447",
            "dvdcompare_film_id": 12345,
            "dvdcompare_release_name": "Psych: Season 1 (TV) (DVD)",
        })
        _write_manifest(tmp_path / "Disc 2", {
            "title": "Psych",
            "type": "tv",
            "tmdb_source_id": "tv:1447",
            "dvdcompare_film_id": 12345,
            "dvdcompare_release_name": "Psych: Season 1 (TV) (DVD)",
        })

        tmdb, fid, rel = read_prefill_ids_from_manifests(tmp_path)
        assert tmdb == "tv:1447"
        assert fid == 12345
        assert rel == "Psych: Season 1 (TV) (DVD)"

    def test_returns_none_when_fields_absent(self, tmp_path):
        # Legacy manifest written before this feature.
        _write_manifest(tmp_path / "Disc 1", {
            "title": "Psych",
            "type": "tv",
        })
        assert read_prefill_ids_from_manifests(tmp_path) == (None, None, None)

    def test_returns_none_when_folder_missing(self, tmp_path):
        missing = tmp_path / "nowhere"
        assert read_prefill_ids_from_manifests(missing) == (None, None, None)

    def test_returns_none_when_folder_has_no_manifests(self, tmp_path):
        (tmp_path / "Disc 1").mkdir()
        assert read_prefill_ids_from_manifests(tmp_path) == (None, None, None)

    def test_ignores_malformed_json(self, tmp_path):
        d = tmp_path / "Disc 1"
        d.mkdir()
        (d / "_rip_manifest.json").write_text("{not json", encoding="utf-8")
        # First manifest is malformed → skipped; nothing else here.
        assert read_prefill_ids_from_manifests(tmp_path) == (None, None, None)

    def test_coerces_film_id_to_int(self, tmp_path):
        # Older manifests might have stored the fid as a string.
        _write_manifest(tmp_path / "Disc 1", {
            "title": "Psych",
            "dvdcompare_film_id": "12345",
        })
        _, fid, _ = read_prefill_ids_from_manifests(tmp_path)
        assert fid == 12345

    def test_invalid_film_id_yields_none(self, tmp_path):
        _write_manifest(tmp_path / "Disc 1", {
            "title": "Psych",
            "dvdcompare_film_id": "not-a-number",
        })
        _, fid, _ = read_prefill_ids_from_manifests(tmp_path)
        assert fid is None
