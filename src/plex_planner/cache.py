"""File-based JSON cache for external API responses.

Each cached item is stored as a JSON file containing the payload and a
``fetched_at`` ISO timestamp.  Items older than the configured TTL are
treated as missing.

Cache location follows OS conventions via platformdirs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from platformdirs import user_cache_dir

log = logging.getLogger(__name__)

_APP_NAME = "plex-planner"

# Module-level flag: when True, all reads return None (misses).
_disabled = False


def get_cache_dir() -> Path:
    """Return the root cache directory, creating it if needed."""
    p = Path(user_cache_dir(_APP_NAME))
    p.mkdir(parents=True, exist_ok=True)
    return p


def disable() -> None:
    """Disable the cache globally (``--no-cache``)."""
    global _disabled
    _disabled = True
    log.debug("Cache disabled")


def is_disabled() -> bool:
    """Return whether caching is currently disabled."""
    return _disabled


def _key_path(namespace: str, key: str) -> Path:
    """Build the filesystem path for a cache entry."""
    return get_cache_dir() / namespace / f"{key}.json"


def hash_key(value: str) -> str:
    """Produce a filesystem-safe hash for arbitrary string keys."""
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def cache_get(namespace: str, key: str, ttl_days: int = 30) -> dict | list | None:
    """Read a cached value, returning ``None`` on miss or expiry."""
    if _disabled:
        return None
    path = _key_path(namespace, key)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        fetched = datetime.fromisoformat(raw["fetched_at"])
        age_days = (datetime.now(timezone.utc) - fetched).total_seconds() / 86400
        if age_days > ttl_days:
            log.debug("Cache expired: %s/%s (%.1f days old)", namespace, key, age_days)
            path.unlink(missing_ok=True)
            return None
        log.debug("Cache hit: %s/%s (%.1f days old)", namespace, key, age_days)
        return raw["data"]
    except (json.JSONDecodeError, KeyError, ValueError):
        log.debug("Cache corrupt, removing: %s/%s", namespace, key)
        path.unlink(missing_ok=True)
        return None


def cache_set(namespace: str, key: str, data: dict | list) -> None:
    """Write a value to the cache."""
    if _disabled:
        return
    path = _key_path(namespace, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    log.debug("Cache write: %s/%s", namespace, key)


def clear(namespace: str | None = None) -> int:
    """Remove cached files.  Returns the number of files removed."""
    base = get_cache_dir()
    target = base / namespace if namespace else base
    if not target.exists():
        return 0
    count = sum(1 for _ in target.rglob("*.json"))
    if namespace:
        shutil.rmtree(target, ignore_errors=True)
    else:
        for child in base.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            elif child.suffix == ".json":
                child.unlink(missing_ok=True)
    log.debug("Cache cleared: %s (%d files)", target, count)
    return count
