"""``riplex organize`` integration tests (offline, dry-run).

Drive the real CLI parser + dispatch into ``run_organize``. The snapshot path
loads a committed scan snapshot (no ffprobe / real files); TMDb + dvdcompare
are supplied by mocking the lookup seam the command already uses.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from riplex.lookup import LookupResult
from riplex.models import PlannedMovie
from tests.support.cli import install_cli_mocks, run_command

SNAPSHOT = Path("tests/snapshots/The Dark Knight.snapshot.json").resolve()


def _mock_movie_lookup(monkeypatch):
    """Make the organize command resolve to a simple single-work movie."""
    planned = PlannedMovie(
        canonical_title="The Dark Knight", year=2008,
        runtime="2h 32m", runtime_seconds=9120,
    )

    async def _lookup(request, provider, **kwargs):
        return LookupResult(
            planned=planned, canonical="The Dark Knight", year=2008,
            is_movie=True, movie_runtime=9120, discs=[], release_name="",
            tmdb_match=None,
        )

    async def _resolve(meta, provider, **kwargs):
        return []  # single-work release

    monkeypatch.setattr("riplex_cli.commands.organize.lookup_metadata", _lookup)
    monkeypatch.setattr("riplex_cli.commands.organize.resolve_disc_groups", _resolve)


def test_organize_snapshot_dry_run_prints_plan(monkeypatch, capsys, tmp_path):
    install_cli_mocks(monkeypatch)
    _mock_movie_lookup(monkeypatch)

    code = run_command([
        "organize", "The Dark Knight (2008)",
        "--snapshot", str(SNAPSHOT),
        "--title", "The Dark Knight", "--year", "2008",
        "--output", str(tmp_path),
    ])

    out = capsys.readouterr().out
    assert code == 0
    assert "DRY RUN" in out.upper()
    # A dry-run always ends with the hint to re-run with --execute.
    assert "--execute" in out


def test_organize_snapshot_rejects_execute(monkeypatch, capsys, tmp_path):
    install_cli_mocks(monkeypatch)

    code = run_command([
        "organize", "The Dark Knight (2008)",
        "--snapshot", str(SNAPSHOT), "--execute",
        "--output", str(tmp_path),
    ])

    assert code == 1
    assert "not allowed with --snapshot" in capsys.readouterr().err


def test_organize_missing_snapshot_file_errors(monkeypatch, capsys, tmp_path):
    install_cli_mocks(monkeypatch)

    code = run_command([
        "organize", "Whatever",
        "--snapshot", str(tmp_path / "nope.json"),
        "--output", str(tmp_path),
    ])

    assert code == 1
    assert "not found" in capsys.readouterr().err


def test_organize_nonexistent_folder_errors(monkeypatch, capsys, tmp_path):
    install_cli_mocks(monkeypatch)

    code = run_command(["organize", str(tmp_path / "does-not-exist")])

    assert code == 1
    assert "not a directory" in capsys.readouterr().err
