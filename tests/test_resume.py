"""Tests for the shared resume adapter (``riplex.resume``)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from riplex.manifest import ExistingSession
from riplex.resume import ResumedLookup, resume_from_session


def _session(**kw) -> ExistingSession:
    defaults = dict(
        title="Psych",
        year=2006,
        media_type="tv",
        release_name="The Complete Series",
        disc_format="Blu-ray",
        rip_root=Path("/tmp/rip"),
        ripped_discs={1},
        works=[],
        all_ripped_discs={1},
        source_id="tv:1447",
    )
    defaults.update(kw)
    return ExistingSession(**defaults)


class _FakeFilm:
    def __init__(self, *, title="Psych: Season 1 (TV) (Blu-ray)", film_id=66231, releases=None):
        self.title = title
        self.film_id = film_id
        self.releases = releases or []


class _FakeRelease:
    def __init__(self, name: str):
        self.name = name


class _FakeProvider:
    def __init__(self, film=None, exc: Exception | None = None):
        self._film = film
        self._exc = exc
        self.calls: list[tuple] = []

    async def _fetch_film_cached(self, title, disc_format, *, year=None):
        self.calls.append((title, disc_format, year))
        if self._exc is not None:
            raise self._exc
        return self._film


def _run(coro):
    return asyncio.run(coro)


class TestResumeFromSession:
    def test_matches_release_by_name(self, monkeypatch):
        release = _FakeRelease("The Complete Series")
        film = _FakeFilm(releases=[release])
        provider = _FakeProvider(film=film)

        import riplex.resume as resume_mod
        monkeypatch.setattr(
            "riplex.disc.provider.DiscProvider",
            lambda: provider,
        )
        monkeypatch.setattr(
            "riplex.disc.provider._convert_release",
            lambda r: ["disc1", "disc2"],
        )

        result = _run(resume_from_session(_session()))

        assert result.canonical == "Psych"
        assert result.year == 2006
        assert result.is_movie is False
        assert result.media_type == "tv"
        assert result.tmdb_match.source_id == "tv:1447"
        assert result.dvdcompare_film is film
        assert result.dvdcompare_film_id == 66231
        assert result.dvdcompare_film_title == "Psych: Season 1 (TV) (Blu-ray)"
        assert result.release is release
        assert result.release_name == "The Complete Series"
        assert result.discs == ["disc1", "disc2"]
        assert result.season_number == 1
        assert result.disc_format == "Blu-ray"
        assert result.dvdcompare_error is None
        assert provider.calls == [("Psych", "Blu-ray", 2006)]

    def test_falls_back_to_first_release_when_name_unknown(self, monkeypatch):
        first = _FakeRelease("Season 1 (US)")
        second = _FakeRelease("Season 1 (UK)")
        film = _FakeFilm(releases=[first, second])
        provider = _FakeProvider(film=film)

        monkeypatch.setattr(
            "riplex.disc.provider.DiscProvider", lambda: provider,
        )
        monkeypatch.setattr(
            "riplex.disc.provider._convert_release", lambda r: [],
        )

        result = _run(resume_from_session(_session(release_name="Nonexistent Edition")))

        assert result.release is first
        assert result.release_name == "Season 1 (US)"

    def test_movie_skips_season_backfill(self, monkeypatch):
        release = _FakeRelease("Ultimate Edition")
        film = _FakeFilm(
            title="Back to the Future Part III (Blu-ray)",
            film_id=100,
            releases=[release],
        )
        provider = _FakeProvider(film=film)

        monkeypatch.setattr(
            "riplex.disc.provider.DiscProvider", lambda: provider,
        )
        monkeypatch.setattr(
            "riplex.disc.provider._convert_release", lambda r: [],
        )

        result = _run(resume_from_session(_session(
            title="Back to the Future Part III",
            year=1990,
            media_type="movie",
            source_id="movie:105",
            release_name="Ultimate Edition",
        )))

        assert result.is_movie is True
        assert result.season_number is None

    def test_missing_disc_format_uses_disc_info(self, monkeypatch):
        release = _FakeRelease("The Complete Series")
        film = _FakeFilm(releases=[release])
        provider = _FakeProvider(film=film)

        monkeypatch.setattr(
            "riplex.disc.provider.DiscProvider", lambda: provider,
        )
        monkeypatch.setattr(
            "riplex.disc.provider._convert_release", lambda r: [],
        )
        monkeypatch.setattr(
            "riplex.disc.provider.detect_disc_format",
            lambda info: "DVD",
        )

        result = _run(resume_from_session(
            _session(disc_format=None),
            disc_info=MagicMock(),
        ))

        assert result.disc_format == "DVD"
        # And that value was passed to the film fetch.
        assert provider.calls[0][1] == "DVD"

    def test_film_fetch_failure_records_error(self, monkeypatch):
        provider = _FakeProvider(exc=RuntimeError("boom"))
        monkeypatch.setattr(
            "riplex.disc.provider.DiscProvider", lambda: provider,
        )
        monkeypatch.setattr(
            "riplex.disc.provider._convert_release", lambda r: [],
        )

        result = _run(resume_from_session(_session()))

        assert result.dvdcompare_error is not None
        assert isinstance(result.dvdcompare_error, RuntimeError)
        assert result.discs == []
        assert result.release is None
        # tmdb_match is still populated from the marker so organize
        # can still fetch detail later.
        assert result.tmdb_match.source_id == "tv:1447"

    def test_convert_release_failure_leaves_empty_discs(self, monkeypatch):
        release = _FakeRelease("The Complete Series")
        film = _FakeFilm(releases=[release])
        provider = _FakeProvider(film=film)

        def _boom(_rel):
            raise ValueError("bad release")

        monkeypatch.setattr(
            "riplex.disc.provider.DiscProvider", lambda: provider,
        )
        monkeypatch.setattr(
            "riplex.disc.provider._convert_release", _boom,
        )

        result = _run(resume_from_session(_session()))

        assert result.release is release
        assert result.discs == []
        # Error path still populates film metadata.
        assert result.dvdcompare_film is film

    def test_legacy_session_without_source_id_stub_tmdb_match(self, monkeypatch):
        """When ``source_id`` is empty AND the best-guess fails, we still
        return a stub MetadataSearchResult so downstream code has
        something to hold onto."""
        release = _FakeRelease("The Complete Series")
        film = _FakeFilm(releases=[release])
        provider = _FakeProvider(film=film)

        monkeypatch.setattr(
            "riplex.disc.provider.DiscProvider", lambda: provider,
        )
        monkeypatch.setattr(
            "riplex.disc.provider._convert_release", lambda r: [],
        )

        # Force the TMDb rehydration path to raise (no API key
        # configured in the test env) — the stub should be returned.
        def _boom_key(_arg=None):
            raise RuntimeError("no api key")

        monkeypatch.setattr("riplex.config.get_api_key", _boom_key)

        result = _run(resume_from_session(_session(source_id="")))

        assert result.tmdb_match is not None
        assert result.tmdb_match.source_id == ""
        assert result.tmdb_match.title == "Psych"

    def test_no_releases_leaves_release_none(self, monkeypatch):
        film = _FakeFilm(releases=[])
        provider = _FakeProvider(film=film)

        monkeypatch.setattr(
            "riplex.disc.provider.DiscProvider", lambda: provider,
        )
        monkeypatch.setattr(
            "riplex.disc.provider._convert_release", lambda r: [],
        )

        result = _run(resume_from_session(_session(release_name="Whatever")))

        assert result.release is None
        assert result.release_name == "Whatever"
        assert result.discs == []
