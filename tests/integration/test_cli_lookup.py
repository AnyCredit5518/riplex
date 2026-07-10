"""``riplex lookup`` integration tests (offline).

Drive the real CLI into ``run_lookup`` with the TMDb + dvdcompare seams mocked,
asserting the rip guide renders and dvdcompare failures degrade gracefully
rather than erroring out.
"""

from __future__ import annotations

import json

import pytest

from riplex.lookup import LookupResult
from riplex.models import PlannedDisc, PlannedMovie
from tests.support.cli import install_cli_mocks, run_command


def _mock_lookup(monkeypatch, *, discs=None, discs_error=None):
    planned = PlannedMovie(
        canonical_title="The Matrix", year=1999,
        runtime="2h 16m", runtime_seconds=8160,
    )

    async def _lookup_metadata(request, provider, **kwargs):
        return LookupResult(
            planned=planned, canonical="The Matrix", year=1999,
            is_movie=True, movie_runtime=8160, discs=[], release_name="",
            tmdb_match=None,
        )

    async def _lookup_discs(title, **kwargs):
        if discs_error is not None:
            raise discs_error
        return discs if discs is not None else []

    monkeypatch.setattr("riplex_cli.commands.lookup.lookup_metadata", _lookup_metadata)
    monkeypatch.setattr("riplex_cli.commands.lookup.lookup_discs", _lookup_discs)


def test_lookup_prints_rip_guide(monkeypatch, capsys):
    install_cli_mocks(monkeypatch)
    _mock_lookup(monkeypatch, discs=[PlannedDisc(number=1, disc_format="Blu-ray", is_film=True)])

    code = run_command(["lookup", "The Matrix"])

    out = capsys.readouterr().out
    assert code == 0
    assert "The Matrix" in out
    assert "1999" in out
    assert "Disc 1" in out


def test_lookup_without_dvdcompare_data_still_succeeds(monkeypatch, capsys):
    install_cli_mocks(monkeypatch)
    _mock_lookup(monkeypatch, discs=[])

    code = run_command(["lookup", "The Matrix"])

    captured = capsys.readouterr()
    assert code == 0
    assert "The Matrix" in captured.out
    # No dvdcompare discs -> guide notes the absence rather than crashing.
    assert "No dvdcompare disc data" in captured.out


def test_lookup_dvdcompare_error_degrades_gracefully(monkeypatch, capsys):
    install_cli_mocks(monkeypatch)
    _mock_lookup(monkeypatch, discs_error=LookupError("dvdc down"))

    code = run_command(["lookup", "The Matrix"])

    captured = capsys.readouterr()
    assert code == 0
    assert "The Matrix" in captured.out
    assert "no dvdcompare data" in captured.err.lower()


def test_lookup_json_output_is_valid(monkeypatch, capsys):
    install_cli_mocks(monkeypatch)
    _mock_lookup(monkeypatch, discs=[PlannedDisc(number=1, disc_format="Blu-ray", is_film=True)])

    code = run_command(["lookup", "The Matrix", "--json"])

    assert code == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["title"] == "The Matrix"
    assert payload["year"] == 1999
    assert payload["media_type"] == "movie"
