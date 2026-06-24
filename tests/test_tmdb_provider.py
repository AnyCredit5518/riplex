import pytest

from riplex.metadata.sources.tmdb import (
    TmdbProvider,
    _looks_like_read_access_token,
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
