"""Tests for the cache module."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from riplex import cache


class TestCacheGetSet:
    def test_roundtrip(self, tmp_path):
        with patch.object(cache, "get_cache_dir", return_value=tmp_path):
            cache.cache_set("ns", "key1", {"title": "Test"})
            result = cache.cache_get("ns", "key1")
        assert result == {"title": "Test"}

    def test_miss_returns_none(self, tmp_path):
        with patch.object(cache, "get_cache_dir", return_value=tmp_path):
            assert cache.cache_get("ns", "missing") is None

    def test_expired_returns_none(self, tmp_path):
        with patch.object(cache, "get_cache_dir", return_value=tmp_path):
            cache.cache_set("ns", "old", {"v": 1})
            # Backdate the file
            path = tmp_path / "ns" / "old.json"
            raw = json.loads(path.read_text())
            old_time = datetime.now(timezone.utc) - timedelta(days=31)
            raw["fetched_at"] = old_time.isoformat()
            path.write_text(json.dumps(raw))
            assert cache.cache_get("ns", "old", ttl_days=30) is None

    def test_not_expired_within_ttl(self, tmp_path):
        with patch.object(cache, "get_cache_dir", return_value=tmp_path):
            cache.cache_set("ns", "fresh", {"v": 2})
            assert cache.cache_get("ns", "fresh", ttl_days=30) == {"v": 2}

    def test_corrupt_file_returns_none(self, tmp_path):
        with patch.object(cache, "get_cache_dir", return_value=tmp_path):
            p = tmp_path / "ns"
            p.mkdir()
            (p / "bad.json").write_text("not json")
            assert cache.cache_get("ns", "bad") is None
            assert not (p / "bad.json").exists()

    def test_list_data(self, tmp_path):
        with patch.object(cache, "get_cache_dir", return_value=tmp_path):
            cache.cache_set("ns", "items", [{"a": 1}, {"b": 2}])
            result = cache.cache_get("ns", "items")
        assert result == [{"a": 1}, {"b": 2}]


class TestCacheDisable:
    def test_disabled_get_returns_none(self, tmp_path):
        with patch.object(cache, "get_cache_dir", return_value=tmp_path):
            cache.cache_set("ns", "k", {"v": 1})
        try:
            cache._disabled = True
            with patch.object(cache, "get_cache_dir", return_value=tmp_path):
                assert cache.cache_get("ns", "k") is None
        finally:
            cache._disabled = False

    def test_disabled_set_is_noop(self, tmp_path):
        try:
            cache._disabled = True
            with patch.object(cache, "get_cache_dir", return_value=tmp_path):
                cache.cache_set("ns", "k2", {"v": 1})
            assert not (tmp_path / "ns" / "k2.json").exists()
        finally:
            cache._disabled = False


class TestCacheClear:
    def test_clear_namespace(self, tmp_path):
        with patch.object(cache, "get_cache_dir", return_value=tmp_path):
            cache.cache_set("dvdcompare", "a", {"v": 1})
            cache.cache_set("tmdb", "b", {"v": 2})
            removed = cache.clear("dvdcompare")
        assert removed == 1
        assert not (tmp_path / "dvdcompare").exists()
        assert (tmp_path / "tmdb" / "b.json").exists()

    def test_clear_all(self, tmp_path):
        with patch.object(cache, "get_cache_dir", return_value=tmp_path):
            cache.cache_set("dvdcompare", "a", {"v": 1})
            cache.cache_set("tmdb", "b", {"v": 2})
            removed = cache.clear()
        assert removed == 2

    def test_clear_nonexistent(self, tmp_path):
        with patch.object(cache, "get_cache_dir", return_value=tmp_path):
            assert cache.clear("nonexistent") == 0


class TestHashKey:
    def test_deterministic(self):
        assert cache.hash_key("test") == cache.hash_key("test")

    def test_different_inputs(self):
        assert cache.hash_key("a") != cache.hash_key("b")

    def test_length(self):
        assert len(cache.hash_key("anything")) == 16
