"""Tests for the session-marker fan-out branch of ``riplex organize``.

When a work-folder contains ``_riplex_session.json`` (written by
orchestrate at start-of-session), ``run_organize`` must dispatch to
every work-folder named by the marker instead of treating the pointed-at
folder as a single work. This covers the Psych: Complete Series case
where a TV series and a linked film disc live in sibling folders under
the same release and must be organized in one pass.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from riplex.manifest import SESSION_MARKER_NAME
from riplex_cli.commands import organize as organize_mod


def _write_marker(folder: Path, works: list[dict], *, release_name: str = "Test") -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / SESSION_MARKER_NAME).write_text(
        json.dumps({
            "type": "riplex_session",
            "release_name": release_name,
            "started_at": "2025-01-01T00:00:00Z",
            "works": works,
        }, indent=2),
        encoding="utf-8",
    )


class _FakeProvider:
    async def close(self):
        pass


def _base_args(folder: Path) -> argparse.Namespace:
    return argparse.Namespace(
        folder=str(folder),
        title=None,
        year=None,
        media_type=None,
        disc_format=None,
        release="1",
        output=str(folder.parent),
        execute=False,
        json=False,
        api_key=None,
        unmatched="extras",
        verbose=False,
        no_cache=True,
        force=False,
        snapshot=None,
        auto=True,
    )


@pytest.mark.asyncio
async def test_marker_fans_out_across_every_work(monkeypatch, tmp_path):
    """A marker with two works organizes both work-folders."""
    root = tmp_path / "Rips"
    tv_folder = root / "Psych (2006)"
    film_folder = root / "Psych - The Movie (2017)"
    tv_folder.mkdir(parents=True)
    film_folder.mkdir(parents=True)

    works = [
        {"title": "Psych", "year": 2006, "media_type": "tv",
         "folder": "Psych (2006)", "disc_numbers": [1, 2]},
        {"title": "Psych: The Movie", "year": 2017, "media_type": "movie",
         "folder": "Psych - The Movie (2017)", "disc_numbers": [31]},
    ]
    _write_marker(tv_folder, works)
    _write_marker(film_folder, works)

    calls: list[tuple[str, str, int, str]] = []

    async def _fake_organize_single(folder, title, args, output_root, provider):
        calls.append((str(folder), title, args.year, args.media_type))
        return 0

    monkeypatch.setattr(organize_mod, "_organize_single", _fake_organize_single)
    # TMDb constructor also runs — stub it so no real HTTP is attempted.
    monkeypatch.setattr(
        organize_mod, "TmdbProvider", lambda api_key=None: _FakeProvider(),
    )

    rc = await organize_mod.run_organize(_base_args(tv_folder))

    assert rc == 0
    assert len(calls) == 2

    # Each call carries its own work-specific title / year / media_type.
    tv_call = [c for c in calls if "Psych (2006)" in c[0]]
    film_call = [c for c in calls if "Psych - The Movie (2017)" in c[0]]
    assert len(tv_call) == 1
    assert tv_call[0][1] == "Psych"
    assert tv_call[0][2] == 2006
    assert tv_call[0][3] == "tv"

    assert len(film_call) == 1
    assert film_call[0][1] == "Psych: The Movie"
    assert film_call[0][2] == 2017
    assert film_call[0][3] == "movie"


@pytest.mark.asyncio
async def test_marker_skips_missing_sibling_but_organizes_present(
    monkeypatch, tmp_path,
):
    """A work-folder named in the marker that doesn't exist on disk is
    logged and skipped; every existing work still gets organized."""
    root = tmp_path / "Rips"
    tv_folder = root / "Psych (2006)"
    tv_folder.mkdir(parents=True)
    # Film folder is NOT created — simulates a partial rip / user cleanup.

    works = [
        {"title": "Psych", "year": 2006, "media_type": "tv",
         "folder": "Psych (2006)", "disc_numbers": [1]},
        {"title": "Psych: The Movie", "year": 2017, "media_type": "movie",
         "folder": "Psych - The Movie (2017)", "disc_numbers": [31]},
    ]
    _write_marker(tv_folder, works)

    calls: list[str] = []

    async def _fake_organize_single(folder, title, args, output_root, provider):
        calls.append(str(folder))
        return 0

    monkeypatch.setattr(organize_mod, "_organize_single", _fake_organize_single)
    monkeypatch.setattr(
        organize_mod, "TmdbProvider", lambda api_key=None: _FakeProvider(),
    )

    rc = await organize_mod.run_organize(_base_args(tv_folder))

    assert rc == 0
    assert len(calls) == 1
    assert "Psych (2006)" in calls[0]


@pytest.mark.asyncio
async def test_empty_works_list_falls_back_to_single(monkeypatch, tmp_path):
    """A marker with no works falls back to the legacy single-folder path."""
    root = tmp_path / "Rips"
    folder = root / "Nothing (2020)"
    folder.mkdir(parents=True)
    _write_marker(folder, [])

    calls: list[tuple[str, str]] = []

    async def _fake_organize_single(f, title, args, output_root, provider):
        calls.append((str(f), title))
        return 0

    monkeypatch.setattr(organize_mod, "_organize_single", _fake_organize_single)
    monkeypatch.setattr(
        organize_mod, "TmdbProvider", lambda api_key=None: _FakeProvider(),
    )

    rc = await organize_mod.run_organize(_base_args(folder))

    assert rc == 0
    assert len(calls) == 1
    assert str(folder) == calls[0][0]
    # Fallback path infers title from folder name and strips year.
    assert calls[0][1] == "Nothing"


@pytest.mark.asyncio
async def test_no_marker_uses_layout_detection(monkeypatch, tmp_path):
    """Without a marker, run_organize goes through detect_organize_layout."""
    folder = tmp_path / "SomeMovie (2020)"
    folder.mkdir()
    (folder / "movie.mkv").write_bytes(b"")

    single_calls: list[str] = []

    async def _fake_organize_single(f, title, args, output_root, provider):
        single_calls.append(str(f))
        return 0

    monkeypatch.setattr(organize_mod, "_organize_single", _fake_organize_single)
    monkeypatch.setattr(
        organize_mod, "TmdbProvider", lambda api_key=None: _FakeProvider(),
    )

    rc = await organize_mod.run_organize(_base_args(folder))

    assert rc == 0
    assert single_calls == [str(folder)]


@pytest.mark.asyncio
async def test_malformed_marker_falls_back(monkeypatch, tmp_path):
    """A corrupt marker file logs a warning and uses the legacy path."""
    folder = tmp_path / "Corrupt (2020)"
    folder.mkdir()
    (folder / "movie.mkv").write_bytes(b"")
    # Write malformed JSON (invalid syntax).
    (folder / SESSION_MARKER_NAME).write_text("{not json", encoding="utf-8")

    single_calls: list[str] = []

    async def _fake_organize_single(f, title, args, output_root, provider):
        single_calls.append(str(f))
        return 0

    monkeypatch.setattr(organize_mod, "_organize_single", _fake_organize_single)
    monkeypatch.setattr(
        organize_mod, "TmdbProvider", lambda api_key=None: _FakeProvider(),
    )

    rc = await organize_mod.run_organize(_base_args(folder))

    assert rc == 0
    # Legacy single-folder path took over.
    assert single_calls == [str(folder)]
