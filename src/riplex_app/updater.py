"""Check for newer releases on GitHub."""

import urllib.request
import json
import sys
from importlib.metadata import version, PackageNotFoundError

GITHUB_REPO = "AnyCredit5518/riplex"
RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def get_current_version() -> str:
    """Return the installed package version, or 'dev' if not installed."""
    try:
        return version("riplex")
    except PackageNotFoundError:
        return "dev"


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


def check_for_update() -> dict | None:
    """Check GitHub for a newer release.

    Returns a dict with 'tag', 'url', and 'assets' if an update is available,
    or None if already up to date (or on error).
    """
    current = get_current_version()
    if current == "dev":
        return None

    try:
        req = urllib.request.Request(
            RELEASES_URL,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "riplex"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
    except Exception:
        return None

    latest_tag = data.get("tag_name", "")
    if not latest_tag:
        return None

    if _parse_version(latest_tag) > _parse_version(current):
        # Find the right asset for this platform
        assets = {}
        for asset in data.get("assets", []):
            name = asset["name"].lower()
            assets[name] = asset["browser_download_url"]

        return {
            "tag": latest_tag,
            "url": data.get("html_url", ""),
            "assets": assets,
        }

    return None


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
