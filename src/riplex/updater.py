"""Check for newer releases on GitHub."""

import os
import urllib.request
import json
import sys

from riplex import __version__, cache

GITHUB_REPO = "AnyCredit5518/riplex"
RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
LATEST_RELEASE_URL = f"{RELEASES_URL}/latest"

_CACHE_NS = "updater"
_CACHE_KEY = "update_check"
_CACHE_TTL_DAYS = 1
_SUPPRESS_ENV_VAR = "RIPLEX_NO_UPDATE_CHECK"


def get_current_version() -> str:
    """Return the installed package version, or 'dev' if not installed."""
    return __version__


def _parse_version(tag: str) -> tuple:
    """Parse 'v1.2.3' into (1, 2, 3) for comparison."""
    tag = tag.lstrip("v")
    parts = []
    for p in tag.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            break
    return tuple(parts)


def _major_minor(version_tuple: tuple) -> tuple:
    """Return (major, minor) from a parsed version tuple."""
    return version_tuple[:2] if len(version_tuple) >= 2 else version_tuple


def check_for_update() -> dict | None:
    """Check GitHub for a newer release.

    Returns a dict with 'tag', 'url', 'releases', and 'assets' if an update
    is available, or None if already up to date (or on error).

    'releases' is a list of dicts (tag, url, body) for all releases in the
    latest minor version series, ordered newest first.  For example if the
    latest release is v0.5.2, releases will contain v0.5.2, v0.5.1, v0.5.0.
    """
    current = get_current_version()
    if current == "dev":
        return None

    try:
        req = urllib.request.Request(
            RELEASES_URL + "?per_page=30",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "riplex"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            all_releases = json.loads(resp.read())
    except Exception:
        return None

    if not all_releases:
        return None

    # Sort by parsed version descending
    tagged = []
    for r in all_releases:
        tag = r.get("tag_name", "")
        if not tag:
            continue
        parsed = _parse_version(tag)
        if parsed:
            tagged.append((parsed, r))
    tagged.sort(key=lambda x: x[0], reverse=True)

    if not tagged:
        return None

    latest_parsed, latest_release = tagged[0]
    current_parsed = _parse_version(current)

    if latest_parsed <= current_parsed:
        return None

    # Collect all releases in the same major.minor series
    latest_minor = _major_minor(latest_parsed)
    series = []
    for parsed, r in tagged:
        if _major_minor(parsed) == latest_minor:
            series.append({
                "tag": r["tag_name"],
                "url": r.get("html_url", ""),
                "body": r.get("body", ""),
            })

    # Assets from the latest release
    assets = {}
    for asset in latest_release.get("assets", []):
        name = asset["name"].lower()
        assets[name] = asset["browser_download_url"]

    return {
        "tag": latest_release["tag_name"],
        "url": latest_release.get("html_url", ""),
        "body": latest_release.get("body", ""),
        "releases": series,
        "assets": assets,
    }


def get_download_url(update_info: dict) -> str:
    """Get the platform-appropriate download URL from update info."""
    if sys.platform == "win32":
        for name, url in update_info["assets"].items():
            if "ui" in name and "windows" in name:
                return url
    elif sys.platform == "darwin":
        for name, url in update_info["assets"].items():
            if "ui" in name and "macos" in name:
                return url
    # Fallback to release page
    return update_info["url"]


def is_check_suppressed() -> bool:
    """Return True if update checks are disabled via environment variable."""
    val = os.environ.get(_SUPPRESS_ENV_VAR, "").strip().lower()
    return val in {"1", "true", "yes", "on"}


def check_for_update_cached() -> dict | None:
    """Cached wrapper around check_for_update().

    Returns the same as check_for_update() but consults the local cache
    first to avoid hitting the GitHub API on every CLI invocation.
    Caches both positive (update available) and negative (no update)
    results for 1 day.

    Honors the RIPLEX_NO_UPDATE_CHECK environment variable: when set to
    "1" / "true" / "yes" / "on", returns None without checking.
    """
    if is_check_suppressed():
        return None
    if get_current_version() == "dev":
        return None

    cached = cache.cache_get(_CACHE_NS, _CACHE_KEY, ttl_days=_CACHE_TTL_DAYS)
    if cached is not None:
        # Empty dict is the sentinel for "no update available"
        return cached if cached else None

    result = check_for_update()
    # Cache empty dict for "no update", actual dict for "update available"
    cache.cache_set(_CACHE_NS, _CACHE_KEY, result if result else {})
    return result


def format_update_notice(update_info: dict, command: str = "pipx upgrade riplex") -> str:
    """Format a pip-style notice block announcing an available update."""
    current = get_current_version()
    tag = update_info["tag"].lstrip("v")
    url = update_info.get("url", "")
    lines = [
        f"[notice] A new release of riplex is available: {current} -> {tag}",
        f"[notice] To update, run: {command}",
    ]
    if url:
        lines.append(f"[notice] Release notes: {url}")
    return "\n".join(lines)
