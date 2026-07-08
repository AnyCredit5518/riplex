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


class TestResumeUsesSavedSeason:
    """When the marker recorded ``season_number``, the resume adapter
    must bias the dvdcompare film lookup with ``"<title>: Season N"``
    and return the saved season directly (skip film-title parsing).
    """

    def test_biases_lookup_with_season(self, monkeypatch):
        release = _FakeRelease("Season 2")
        # Return a film whose title says Season 1 so we can prove the
        # returned season came from the marker, not the film title.
        film = _FakeFilm(
            title="Psych: Season 1 (TV) (Blu-ray)",
            releases=[release],
        )
        provider = _FakeProvider(film=film)

        monkeypatch.setattr(
            "riplex.disc.provider.DiscProvider", lambda: provider,
        )
        monkeypatch.setattr(
            "riplex.disc.provider._convert_release", lambda r: [],
        )

        result = _run(resume_from_session(
            _session(season_number=2, release_name="Season 2"),
        ))

        # The lookup title carries the season bias.
        assert provider.calls == [("Psych: Season 2", "Blu-ray", 2006)]
        # Saved season wins over parsed film title.
        assert result.season_number == 2

    def test_legacy_no_season_falls_back_to_film_title(self, monkeypatch):
        release = _FakeRelease("The Complete Series")
        film = _FakeFilm(
            title="Psych: Season 3 (TV) (Blu-ray)",
            releases=[release],
        )
        provider = _FakeProvider(film=film)

        monkeypatch.setattr(
            "riplex.disc.provider.DiscProvider", lambda: provider,
        )
        monkeypatch.setattr(
            "riplex.disc.provider._convert_release", lambda r: [],
        )

        # Legacy marker: season_number is None (its default).
        result = _run(resume_from_session(_session()))

        # No season bias applied to the film lookup.
        assert provider.calls == [("Psych", "Blu-ray", 2006)]
        # Falls back to parsing the film title.
        assert result.season_number == 3

    def test_movie_never_biases_with_season(self, monkeypatch):
        # Even if season_number somehow leaked into a movie session
        # (shouldn't happen with build_session_work, but be defensive),
        # movies must never send "Season N" to dvdcompare.
        release = _FakeRelease("Ultimate Edition")
        film = _FakeFilm(title="Some Movie (Blu-ray)", releases=[release])
        provider = _FakeProvider(film=film)

        monkeypatch.setattr(
            "riplex.disc.provider.DiscProvider", lambda: provider,
        )
        monkeypatch.setattr(
            "riplex.disc.provider._convert_release", lambda r: [],
        )

        result = _run(resume_from_session(_session(
            title="Some Movie",
            media_type="movie",
            season_number=5,   # bogus, must be ignored for movies
        )))

        assert provider.calls == [("Some Movie", "Blu-ray", 2006)]
        assert result.season_number == 5  # returned as-is; movies just ignore it


class TestResumeFetchesShowDetail:
    """The GUI selection screen and the CLI rip guide both cross-
    reference TMDb ShowDetail against dvdcompare to enrich labels and
    demote duplicate-episode entries (e.g. Psych S3 D1 lists a bonus
    re-edit alongside the real episode). The resume adapter is the
    single place that fetch lives so both surfaces stay in sync."""

    def test_fetches_show_detail_for_tv_resume(self, monkeypatch):
        film = _FakeFilm(releases=[_FakeRelease("The Complete Series")])
        provider = _FakeProvider(film=film)
        monkeypatch.setattr(
            "riplex.disc.provider.DiscProvider", lambda: provider,
        )
        monkeypatch.setattr(
            "riplex.disc.provider._convert_release", lambda r: [],
        )

        sentinel_detail = object()
        called = {}

        async def _fake_fetch(source_id):
            called["source_id"] = source_id
            return sentinel_detail

        import riplex.resume as resume_mod
        monkeypatch.setattr(resume_mod, "_fetch_show_detail", _fake_fetch)

        result = _run(resume_from_session(_session()))

        assert called == {"source_id": "tv:1447"}
        assert result.show_detail is sentinel_detail

    def test_skips_show_detail_for_movie_resume(self, monkeypatch):
        film = _FakeFilm(title="Some Movie (Blu-ray)", releases=[_FakeRelease("Ultimate")])
        provider = _FakeProvider(film=film)
        monkeypatch.setattr(
            "riplex.disc.provider.DiscProvider", lambda: provider,
        )
        monkeypatch.setattr(
            "riplex.disc.provider._convert_release", lambda r: [],
        )

        called = {"count": 0}

        async def _fake_fetch(source_id):
            called["count"] += 1
            return object()

        import riplex.resume as resume_mod
        monkeypatch.setattr(resume_mod, "_fetch_show_detail", _fake_fetch)

        result = _run(resume_from_session(_session(
            title="Some Movie", media_type="movie",
        )))

        assert called["count"] == 0
        assert result.show_detail is None

    def test_skips_show_detail_when_source_id_missing(self, monkeypatch):
        """Legacy TV markers without a source_id (pre-source_id
        sessions) can't fetch ShowDetail — skip cleanly rather than
        letting a bad TMDb call raise."""
        film = _FakeFilm(releases=[_FakeRelease("The Complete Series")])
        provider = _FakeProvider(film=film)
        monkeypatch.setattr(
            "riplex.disc.provider.DiscProvider", lambda: provider,
        )
        monkeypatch.setattr(
            "riplex.disc.provider._convert_release", lambda r: [],
        )

        async def _stub_rehydrate(session):
            # ``_rehydrate_tmdb_match`` normally hits the network for
            # legacy markers; stub it out so this test stays pure-unit.
            from riplex.metadata.provider import MetadataSearchResult
            return MetadataSearchResult(
                source_id="", title=session.title, year=session.year,
                media_type=session.media_type,
            )

        import riplex.resume as resume_mod
        monkeypatch.setattr(resume_mod, "_rehydrate_tmdb_match", _stub_rehydrate)

        called = {"count": 0}

        async def _fake_fetch(source_id):
            called["count"] += 1
            return object()

        monkeypatch.setattr(resume_mod, "_fetch_show_detail", _fake_fetch)

        result = _run(resume_from_session(_session(source_id="")))

        assert called["count"] == 0
        assert result.show_detail is None

