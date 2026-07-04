"""Tests for the ``_riplex_session.json`` marker + aggregated resume."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from riplex import manifest as manifest_mod
from riplex.manifest import (
    SESSION_MARKER_NAME,
    ExistingSession,
    SessionWork,
    _iter_candidate_work_folders,
    build_rip_path,
    find_existing_session,
    read_session_marker,
    write_session_marker,
)


@pytest.fixture
def rip_root(tmp_path, monkeypatch):
    """Point manifest._session_root() at a scratch dir."""
    root = tmp_path / "Rips"
    root.mkdir()

    def _fake_session_root() -> Path:
        return root

    monkeypatch.setattr(manifest_mod, "_session_root", _fake_session_root)
    return root


def _write_manifest(folder: Path, disc_num: int, title: str, year: int = 2000) -> None:
    disc_dir = folder / f"Disc {disc_num}"
    disc_dir.mkdir(parents=True, exist_ok=True)
    (disc_dir / "_rip_manifest.json").write_text(
        json.dumps({
            "title": title,
            "year": year,
            "type": "movie",
            "release": "Test Release",
            "format": "DVD",
        }),
        encoding="utf-8",
    )


class TestWriteSessionMarker:
    def test_writes_marker_into_each_work_folder(self, rip_root):
        works = [
            SessionWork(title="Psych", year=2006, media_type="tv",
                        folder="Psych (2006)", disc_numbers=[1, 2]),
            SessionWork(title="Psych: The Movie", year=2017, media_type="movie",
                        folder="Psych The Movie (2017)", disc_numbers=[3]),
        ]
        written = write_session_marker(works, release_name="Psych Complete Series")

        assert len(written) == 2
        for w in works:
            marker = rip_root / w.folder / SESSION_MARKER_NAME
            assert marker.exists()
            data = json.loads(marker.read_text(encoding="utf-8"))
            assert data["type"] == "riplex_session"
            assert data["release_name"] == "Psych Complete Series"
            assert len(data["works"]) == 2
            folders = {w["folder"] for w in data["works"]}
            assert folders == {"Psych (2006)", "Psych The Movie (2017)"}

    def test_creates_missing_folders(self, rip_root):
        works = [SessionWork(title="X", year=2020, media_type="movie",
                             folder="X (2020)", disc_numbers=[1])]
        write_session_marker(works, release_name="rel")
        assert (rip_root / "X (2020)" / SESSION_MARKER_NAME).exists()

    def test_idempotent_overwrite(self, rip_root):
        works = [SessionWork(title="X", year=2020, media_type="movie",
                             folder="X (2020)", disc_numbers=[1])]
        write_session_marker(works, release_name="rel-1")
        write_session_marker(works, release_name="rel-2")
        marker = rip_root / "X (2020)" / SESSION_MARKER_NAME
        data = json.loads(marker.read_text(encoding="utf-8"))
        assert data["release_name"] == "rel-2"

    def test_empty_works_writes_nothing(self, rip_root):
        assert write_session_marker([], release_name="rel") == []

    def test_persists_source_id(self, rip_root):
        """source_id round-trips through the marker so resume can
        rebuild a real MetadataSearchResult without a fuzzy title
        re-search."""
        works = [SessionWork(
            title="Psych", year=2006, media_type="tv",
            folder="Psych (2006)", disc_numbers=[1],
            source_id="tv:1447",
        )]
        write_session_marker(works, release_name="rel")
        data = json.loads(
            (rip_root / "Psych (2006)" / SESSION_MARKER_NAME)
            .read_text(encoding="utf-8"),
        )
        assert data["works"][0]["source_id"] == "tv:1447"


class TestReadSessionMarker:
    def test_returns_none_when_missing(self, tmp_path):
        assert read_session_marker(tmp_path) is None

    def test_returns_none_on_wrong_type(self, tmp_path):
        (tmp_path / SESSION_MARKER_NAME).write_text(
            json.dumps({"type": "something-else"}), encoding="utf-8",
        )
        assert read_session_marker(tmp_path) is None

    def test_returns_none_on_bad_json(self, tmp_path):
        (tmp_path / SESSION_MARKER_NAME).write_text("not json", encoding="utf-8")
        assert read_session_marker(tmp_path) is None

    def test_returns_payload(self, rip_root):
        works = [SessionWork(title="X", year=2020, media_type="movie",
                             folder="X (2020)", disc_numbers=[1])]
        write_session_marker(works, release_name="rel")
        data = read_session_marker(rip_root / "X (2020)")
        assert data is not None
        assert data["type"] == "riplex_session"


class TestFindExistingSessionAggregation:
    def test_legacy_single_work_returns_local_ripped(self, rip_root):
        folder = rip_root / "Solo (2020)"
        _write_manifest(folder, 1, "Solo", 2020)
        _write_manifest(folder, 2, "Solo", 2020)

        session = find_existing_session("Solo")

        assert isinstance(session, ExistingSession)
        assert session.ripped_discs == {1, 2}
        assert session.works == []
        # For legacy sessions callers may fall back to ripped_discs.
        assert session.all_ripped_discs == {1, 2}

    def test_marker_aggregates_across_siblings(self, rip_root):
        tv_folder = rip_root / "Psych (2006)"
        film_folder = rip_root / "Psych The Movie (2017)"
        _write_manifest(tv_folder, 1, "Psych", 2006)
        _write_manifest(tv_folder, 2, "Psych", 2006)
        _write_manifest(film_folder, 3, "Psych: The Movie", 2017)

        works = [
            SessionWork(title="Psych", year=2006, media_type="tv",
                        folder="Psych (2006)", disc_numbers=[1, 2]),
            SessionWork(title="Psych: The Movie", year=2017, media_type="movie",
                        folder="Psych The Movie (2017)", disc_numbers=[3]),
        ]
        write_session_marker(works, release_name="Psych Set")

        # Look up via TV title
        s1 = find_existing_session("Psych")
        assert s1 is not None
        assert s1.ripped_discs == {1, 2}
        assert s1.all_ripped_discs == {1, 2, 3}
        assert len(s1.works) == 2

        # Look up via film title — same aggregation
        s2 = find_existing_session("Psych: The Movie")
        assert s2 is not None
        assert s2.ripped_discs == {3}
        assert s2.all_ripped_discs == {1, 2, 3}

    def test_missing_sibling_folder_is_ignored(self, rip_root):
        tv_folder = rip_root / "Psych (2006)"
        _write_manifest(tv_folder, 1, "Psych", 2006)

        works = [
            SessionWork(title="Psych", year=2006, media_type="tv",
                        folder="Psych (2006)", disc_numbers=[1]),
            SessionWork(title="Psych: The Movie", year=2017, media_type="movie",
                        folder="Psych The Movie (2017)", disc_numbers=[3]),
        ]
        write_session_marker(works, release_name="Psych Set")

        session = find_existing_session("Psych")
        assert session is not None
        # Sibling folder exists (write_session_marker created it) but has
        # no manifest, so it contributes zero discs.
        assert session.all_ripped_discs == {1}

    def test_no_match_returns_none(self, rip_root):
        _write_manifest(rip_root / "Solo (2020)", 1, "Solo", 2020)
        assert find_existing_session("Unknown") is None

    def test_root_missing_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            manifest_mod, "_session_root",
            lambda: tmp_path / "does-not-exist",
        )
        assert find_existing_session("anything") is None

    def test_marker_only_match_resolves_unripped_work(self, rip_root):
        """Real-world Psych case: disc 31 (the film work) was ripped
        first, which wrote _riplex_session.json into every work-folder
        including the TV folder. The TV folder itself has no rip
        manifest yet. Inserting a TV disc later and looking up 'Psych'
        must still resolve the session by finding the marker's
        works[*].title entry — not just by matching a rip manifest.
        """
        tv_folder = rip_root / "Psych (2006)"
        film_folder = rip_root / "Psych The Movie (2017)"
        # Only the film work has a rip manifest.
        _write_manifest(film_folder, 31, "Psych: The Movie", 2017)

        works = [
            SessionWork(title="Psych", year=2006, media_type="tv",
                        folder="Psych (2006)",
                        disc_numbers=list(range(1, 31))),
            SessionWork(title="Psych: The Movie", year=2017,
                        media_type="movie",
                        folder="Psych The Movie (2017)",
                        disc_numbers=[31]),
        ]
        write_session_marker(works, release_name="Psych Complete Series")

        # Look up via the TV title — the TV folder has no manifest but
        # its marker names 'Psych' as a work, so this must resolve.
        session = find_existing_session("Psych")
        assert session is not None
        assert session.title == "Psych"

    def test_resume_populates_source_id_from_marker(self, rip_root):
        """When the marker carries source_id, ExistingSession surfaces
        it so _resume_session can build a real MetadataSearchResult
        (not the empty-source_id placeholder that broke organize)."""
        tv_folder = rip_root / "Psych (2006)"
        _write_manifest(tv_folder, 1, "Psych", 2006)
        works = [SessionWork(
            title="Psych", year=2006, media_type="tv",
            folder="Psych (2006)", disc_numbers=[1],
            source_id="tv:1447",
        )]
        write_session_marker(works, release_name="rel")

        session = find_existing_session("Psych")
        assert session is not None
        assert session.source_id == "tv:1447"


class TestBuildRipPathSeasonNesting:
    """``build_rip_path`` nests TV rips under ``Season NN`` so rips of
    different seasons of the same show don't collide on ``Disc N``.
    """

    @pytest.fixture(autouse=True)
    def _fake_rip_output(self, tmp_path, monkeypatch):
        root = tmp_path / "Rips"
        root.mkdir()
        from riplex import config as config_mod
        monkeypatch.setattr(config_mod, "get_rip_output", lambda: str(root))
        return root

    def test_movie_flat_layout(self, _fake_rip_output):
        p = build_rip_path("Batman Begins", 2005, disc_number=1)
        assert p == _fake_rip_output / "Batman Begins (2005)" / "Disc 1"

    def test_movie_no_disc_number(self, _fake_rip_output):
        p = build_rip_path("Batman Begins", 2005)
        assert p == _fake_rip_output / "Batman Begins (2005)"

    def test_tv_with_season_nests_under_season_folder(self, _fake_rip_output):
        p = build_rip_path("Psych", 2006, disc_number=1, season_number=1)
        assert p == _fake_rip_output / "Psych (2006)" / "Season 01" / "Disc 1"

    def test_tv_with_season_no_disc(self, _fake_rip_output):
        p = build_rip_path("Psych", 2006, season_number=1)
        assert p == _fake_rip_output / "Psych (2006)" / "Season 01"

    def test_tv_double_digit_season_padded(self, _fake_rip_output):
        p = build_rip_path("Doctor Who", 2005, disc_number=3, season_number=12)
        assert p == _fake_rip_output / "Doctor Who (2005)" / "Season 12" / "Disc 3"

    def test_tv_without_season_stays_flat(self, _fake_rip_output):
        # Regression: TV rip without a known season keeps the legacy flat
        # layout so we don't force a bogus ``Season 00`` folder.
        p = build_rip_path("Some Show", 2020, disc_number=1)
        assert p == _fake_rip_output / "Some Show (2020)" / "Disc 1"


class TestIterCandidateWorkFolders:
    def test_yields_flat_and_nested_folders(self, tmp_path):
        (tmp_path / "Psych (2006)" / "Season 01").mkdir(parents=True)
        (tmp_path / "Psych (2006)" / "Season 02").mkdir(parents=True)
        (tmp_path / "Batman Begins (2005)").mkdir()
        # Underscore-prefixed folders are skipped (debug dirs, markers).
        (tmp_path / "_riplex").mkdir()
        (tmp_path / "Psych (2006)" / "_riplex").mkdir()

        folders = {p.relative_to(tmp_path).as_posix()
                   for p in _iter_candidate_work_folders(tmp_path)}

        assert folders == {
            "Psych (2006)",
            "Psych (2006)/Season 01",
            "Psych (2006)/Season 02",
            "Batman Begins (2005)",
        }

    def test_ignores_non_season_subfolders(self, tmp_path):
        (tmp_path / "Movie (2020)" / "Disc 1").mkdir(parents=True)
        (tmp_path / "Movie (2020)" / "Extras").mkdir()

        folders = {p.relative_to(tmp_path).as_posix()
                   for p in _iter_candidate_work_folders(tmp_path)}

        assert folders == {"Movie (2020)"}

    def test_missing_root_yields_nothing(self, tmp_path):
        folders = list(_iter_candidate_work_folders(tmp_path / "nope"))
        assert folders == []


class TestFindExistingSessionSeasonNested:
    """``find_existing_session`` must discover TV sessions whose rips
    live in ``<root>/<title>/Season NN/Disc N`` — the new default TV
    layout — and must still discover legacy flat sessions.
    """

    def test_finds_session_in_season_nested_folder(self, rip_root):
        season_folder = rip_root / "Psych (2006)" / "Season 01"
        _write_manifest(season_folder, 1, "Psych", year=2006)
        # Force media_type to tv on the manifest.
        m = season_folder / "Disc 1" / "_rip_manifest.json"
        data = json.loads(m.read_text(encoding="utf-8"))
        data["type"] = "tv"
        m.write_text(json.dumps(data), encoding="utf-8")

        session = find_existing_session("Psych")
        assert session is not None
        assert session.title == "Psych"
        assert session.rip_root == season_folder
        assert session.ripped_discs == {1}

    def test_legacy_flat_tv_session_still_discovered(self, rip_root):
        # Users with existing (pre-nesting) TV rips must still resume.
        flat_folder = rip_root / "Psych (2006)"
        _write_manifest(flat_folder, 1, "Psych", year=2006)

        session = find_existing_session("Psych")
        assert session is not None
        assert session.rip_root == flat_folder
        assert session.ripped_discs == {1}

    def test_marker_only_match_survives_missing_own_folder(self, rip_root):
        """If the work's own folder is gone entirely (user cleaned up),
        the marker in a sibling folder still surfaces the session, with
        an empty ripped_discs for the requested work.
        """
        film_folder = rip_root / "Psych The Movie (2017)"
        _write_manifest(film_folder, 31, "Psych: The Movie", 2017)
        # Write markers into every work-folder, including a TV folder
        # that we then delete to simulate manual cleanup.
        works = [
            SessionWork(title="Psych", year=2006, media_type="tv",
                        folder="Psych (2006)", disc_numbers=[1]),
            SessionWork(title="Psych: The Movie", year=2017,
                        media_type="movie",
                        folder="Psych The Movie (2017)",
                        disc_numbers=[31]),
        ]
        write_session_marker(works, release_name="Psych Set")
        tv_folder = rip_root / "Psych (2006)"
        # Remove the TV folder entirely.
        (tv_folder / SESSION_MARKER_NAME).unlink()
        tv_folder.rmdir()

        # Marker in the film folder still names 'Psych' as a work.
        session = find_existing_session("Psych")
        assert session is not None
        assert session.title == "Psych"
        # rip_root falls back to the folder holding the marker.
        assert session.rip_root == film_folder
        assert session.all_ripped_discs == {31}

