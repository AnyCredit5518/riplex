"""Tests for the best_guess() TMDb auto-fill helper."""

import pytest

from riplex.metadata.autosearch import (
    DEFAULT_FUZZY_THRESHOLD,
    best_guess,
    score_title,
)
from riplex.metadata.provider import MetadataSearchResult


class _FakeProvider:
    """Duck-typed stand-in for TmdbProvider that returns canned results
    without hitting the network. Records the last query for assertions."""

    def __init__(self, results):
        self._results = results
        self.last_query = None
        self.last_media_type = None

    async def search(self, query, *, year=None, media_type="auto"):
        self.last_query = query
        self.last_media_type = media_type
        return list(self._results)


class _RaisingProvider:
    async def search(self, query, *, year=None, media_type="auto"):
        raise RuntimeError("boom")


def _result(title, media_type="movie", year=2020):
    return MetadataSearchResult(
        source_id="1",
        title=title,
        year=year,
        media_type=media_type,
    )


class TestScoreTitle:
    def test_identical_titles_score_one(self):
        assert score_title("Psych", "Psych") == 1.0

    def test_case_and_punctuation_ignored(self):
        assert score_title("Psych: The Movie", "psych the movie") == pytest.approx(1.0)

    def test_unrelated_titles_score_low(self):
        assert score_title("Psych", "Breaking Bad") < 0.5

    def test_close_variant_scores_high(self):
        # Extra colon / punctuation shouldn't tank the score.
        s = score_title("Psych 2: Lassie Come Home", "Psych 2 Lassie Come Home")
        assert s >= 0.95

    def test_empty_inputs_return_zero(self):
        assert score_title("", "Something") == 0.0
        assert score_title("Something", "") == 0.0


class TestBestGuess:
    @pytest.mark.asyncio
    async def test_confident_hit_returns_result_and_score(self):
        provider = _FakeProvider([_result("Psych", media_type="tv")])
        got = await best_guess(provider, "Psych", media_type="tv")
        assert got is not None
        result, score = got
        assert result.title == "Psych"
        assert score >= DEFAULT_FUZZY_THRESHOLD
        # media_type filter passed through to the provider.
        assert provider.last_media_type == "tv"

    @pytest.mark.asyncio
    async def test_weak_hit_returns_none(self):
        # Top hit's title is nothing like the query.
        provider = _FakeProvider([_result("Completely Different Show")])
        assert await best_guess(provider, "Psych") is None

    @pytest.mark.asyncio
    async def test_empty_query_returns_none_without_calling_provider(self):
        provider = _FakeProvider([_result("Psych")])
        assert await best_guess(provider, "   ") is None
        assert provider.last_query is None

    @pytest.mark.asyncio
    async def test_no_results_returns_none(self):
        provider = _FakeProvider([])
        assert await best_guess(provider, "Psych") is None

    @pytest.mark.asyncio
    async def test_provider_error_returns_none(self):
        # Network failures shouldn't propagate — the caller treats a
        # missing guess the same as a low-confidence one.
        assert await best_guess(_RaisingProvider(), "Psych") is None

    @pytest.mark.asyncio
    async def test_custom_threshold_can_reject_confident_hit(self):
        # A perfect match still fails if the threshold is set impossibly high.
        provider = _FakeProvider([_result("Psych")])
        assert await best_guess(provider, "Psych", threshold=1.01) is None

    @pytest.mark.asyncio
    async def test_takes_top_hit_only(self):
        # A weaker second hit should not be considered even if the top hit
        # falls below the threshold — best_guess() never fishes down the list.
        provider = _FakeProvider([
            _result("Completely Different"),
            _result("Psych"),
        ])
        assert await best_guess(provider, "Psych") is None
