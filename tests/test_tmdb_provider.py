import pytest

from riplex.metadata.sources.tmdb import (
    TmdbProvider,
    _looks_like_read_access_token,
    _title_match_tier,
)

# A JWT-shaped sample (header.payload.signature). Not a real credential.
_SAMPLE_READ_ACCESS_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJyaXBsZXgifQ.c2lnbmF0dXJl"
_SAMPLE_API_KEY = "0123456789abcdef0123456789abcdef"


class TestLooksLikeReadAccessToken:
    def test_jwt_token_is_detected(self):
        assert _looks_like_read_access_token(_SAMPLE_READ_ACCESS_TOKEN) is True

    def test_v3_hex_key_is_not_detected(self):
        assert _looks_like_read_access_token(_SAMPLE_API_KEY) is False

    def test_empty_string_is_not_detected(self):
        assert _looks_like_read_access_token("") is False


class TestTmdbProviderAuth:
    @pytest.mark.asyncio
    async def test_read_access_token_uses_authorization_header(self):
        provider = TmdbProvider(api_key=_SAMPLE_READ_ACCESS_TOKEN)
        try:
            assert (
                provider._client.headers["Authorization"]
                == f"Bearer {_SAMPLE_READ_ACCESS_TOKEN}"
            )
            assert "api_key" not in provider._client.params
        finally:
            await provider.close()

    @pytest.mark.asyncio
    async def test_v3_key_uses_query_parameter(self):
        provider = TmdbProvider(api_key=_SAMPLE_API_KEY)
        try:
            assert provider._client.params["api_key"] == _SAMPLE_API_KEY
            assert "Authorization" not in provider._client.headers
        finally:
            await provider.close()

    @pytest.mark.asyncio
    async def test_whitespace_is_stripped_from_credential(self):
        provider = TmdbProvider(api_key=f"  {_SAMPLE_API_KEY}  ")
        try:
            assert provider._client.params["api_key"] == _SAMPLE_API_KEY
        finally:
            await provider.close()

    def test_missing_key_raises(self, monkeypatch):
        monkeypatch.delenv("TMDB_API_KEY", raising=False)
        with pytest.raises(ValueError, match="TMDb API key is required"):
            TmdbProvider(api_key="")


class TestTitleMatchTier:
    def test_exact_match_ranks_highest(self):
        assert _title_match_tier("Tron", "Tron") == 4

    def test_match_is_case_insensitive(self):
        assert _title_match_tier("tron", "TRON") == 4

    def test_punctuation_is_ignored(self):
        # "TRON: Legacy" should compare equal to "Tron Legacy".
        assert _title_match_tier("Tron Legacy", "TRON: Legacy") == 4

    def test_title_starting_with_query_outranks_substring(self):
        assert _title_match_tier("Tron", "TRON: Legacy") == 3

    def test_query_as_whole_word_inside_title(self):
        assert _title_match_tier("Planet", "The Green Planet") == 2

    def test_substring_without_word_boundary(self):
        assert _title_match_tier("ron", "Tron") == 1

    def test_no_overlap_ranks_lowest(self):
        assert _title_match_tier("Tron", "House of the Dragon") == 0

    def test_empty_query_ranks_lowest(self):
        assert _title_match_tier("", "Tron") == 0

    def test_relevance_beats_popularity_for_tron(self):
        """The original Tron (low popularity) must outrank an unrelated but
        wildly popular fuzzy match like House of the Dragon."""
        original = ("Tron", 3.54)
        fuzzy = ("House of the Dragon", 494.97)
        ranked = sorted(
            [original, fuzzy],
            key=lambda item: (_title_match_tier("Tron", item[0]), item[1]),
            reverse=True,
        )
        assert ranked[0] == original


# Minimal /search/multi payload mirroring TMDb's real shape for "Tron":
# a mix of movie, tv, person, and collection entities.
_MULTI_TRON_PAYLOAD = {
    "results": [
        {
            "id": 20526,
            "media_type": "movie",
            "title": "TRON: Legacy",
            "release_date": "2010-12-14",
            "overview": "Sam Flynn...",
            "popularity": 14.15,
        },
        {
            "id": 97,
            "media_type": "movie",
            "title": "Tron",
            "release_date": "1982-07-09",
            "overview": "A computer hacker...",
            "popularity": 4.36,
        },
        {
            "id": 44217,
            "media_type": "tv",
            "name": "TRON: Uprising",
            "first_air_date": "2012-05-18",
            "overview": "Beck becomes...",
            "popularity": 6.34,
        },
        {
            "id": 123,
            "media_type": "person",
            "name": "Tron Mai",
            "popularity": 0.14,
        },
        {
            "id": 456,
            "media_type": "collection",
            "name": "TRON Collection",
            "overview": "The TRON franchise.",
            "popularity": 2.0,
        },
    ]
}


class TestSearchMulti:
    @pytest.mark.asyncio
    async def test_auto_uses_multi_and_filters_person_and_collection(
        self, monkeypatch
    ):
        provider = TmdbProvider(api_key=_SAMPLE_API_KEY)
        calls: list[str] = []

        async def fake_get_json(path, params=None, cache_ns=None, cache_key=None):
            calls.append(path)
            return _MULTI_TRON_PAYLOAD

        monkeypatch.setattr(provider, "_get_json", fake_get_json)
        try:
            results = await provider.search("Tron")
        finally:
            await provider.close()

        # Routed through /search/multi exactly once (not the per-type endpoints).
        assert calls == ["/search/multi"]
        # person and collection entities are dropped; only movie/tv survive.
        assert {r.media_type for r in results} == {"movie", "tv"}
        assert all(
            r.title not in ("Tron Mai", "TRON Collection") for r in results
        )
        # Exact title match ("Tron") ranks first despite lower popularity.
        assert results[0].title == "Tron"
        assert results[0].year == 1982

    @pytest.mark.asyncio
    async def test_auto_with_year_uses_dedicated_endpoints(self, monkeypatch):
        provider = TmdbProvider(api_key=_SAMPLE_API_KEY)
        calls: list[str] = []

        async def fake_get_json(path, params=None, cache_ns=None, cache_key=None):
            calls.append(path)
            return {"results": []}

        monkeypatch.setattr(provider, "_get_json", fake_get_json)
        try:
            await provider.search("Tron", year=1982)
        finally:
            await provider.close()

        # A year filter falls back to the dedicated endpoints (multi can't
        # filter by year), so both movie and tv search are queried.
        assert "/search/movie" in calls
        assert "/search/tv" in calls
        assert "/search/multi" not in calls

    @pytest.mark.asyncio
    async def test_explicit_media_type_uses_dedicated_endpoint(self, monkeypatch):
        provider = TmdbProvider(api_key=_SAMPLE_API_KEY)
        calls: list[str] = []

        async def fake_get_json(path, params=None, cache_ns=None, cache_key=None):
            calls.append(path)
            return {"results": []}

        monkeypatch.setattr(provider, "_get_json", fake_get_json)
        try:
            await provider.search("Game of Thrones", media_type="tv")
        finally:
            await provider.close()

        assert calls == ["/search/tv"]

