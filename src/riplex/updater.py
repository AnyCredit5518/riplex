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
    """Get the platform-appropriate download URL from update info.

    Skips checksum (``.sha256``) sidecar assets so the executable/bundle is
    returned, not its checksum file.
    """
    def _pick(*, must_contain: tuple[str, ...], suffix: str) -> str | None:
        for name, url in update_info["assets"].items():
            low = name.lower()
            if low.endswith(".sha256"):
                continue
            if low.endswith(suffix) and all(tok in low for tok in must_contain):
                return url
        return None

    if sys.platform == "win32":
        url = _pick(must_contain=("ui", "windows"), suffix=".exe")
        if url:
            return url
    elif sys.platform == "darwin":
        url = _pick(must_contain=("ui", "macos"), suffix=".zip")
        if url:
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


# ---------------------------------------------------------------------------
# In-place self-update (Windows, frozen onefile build only)
# ---------------------------------------------------------------------------
#
# The GUI ships as a PyInstaller ``--onefile`` ``riplex-ui.exe``. Windows lets
# a running executable be *renamed* (just not overwritten), so we can update in
# place: download the new exe, rename the running one aside, move the new one
# into its place, relaunch, and delete the leftover on next start. The download
# is verified against the SHA-256 published alongside the release asset before
# anything is swapped, and the whole thing only ever runs for a frozen Windows
# build whose folder is writable — otherwise callers fall back to the browser
# download.

import hashlib
import subprocess
from pathlib import Path

_TRUSTED_HOSTS = ("github.com", "githubusercontent.com")
_BACKUP_SUFFIX = ".old"
_STAGING_SUFFIX = ".new"


def is_frozen() -> bool:
    """True when running as a PyInstaller-frozen executable."""
    return bool(getattr(sys, "frozen", False))


def running_executable() -> Path:
    """Path to the currently running executable."""
    return Path(sys.executable)


def _dir_is_writable(directory: Path) -> bool:
    """True if we can create (and delete) a file in *directory*."""
    probe = directory / f".riplex_write_test_{os.getpid()}"
    try:
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def can_self_update() -> bool:
    """Whether an in-place update is possible for this running instance.

    Requires a frozen Windows build whose containing folder is writable (so no
    UAC elevation is needed). Running from source, on macOS/Linux, or from a
    read-only location (e.g. Program Files) all return ``False`` — callers then
    fall back to opening the release page in a browser.
    """
    if not is_frozen() or sys.platform != "win32":
        return False
    return _dir_is_writable(running_executable().parent)


def _is_trusted_url(url: str) -> bool:
    """Only allow HTTPS downloads from GitHub / its asset CDN."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in _TRUSTED_HOSTS)


def get_checksum_url(update_info: dict) -> str | None:
    """Return the URL of the ``.sha256`` asset for this platform's UI build."""
    assets = update_info.get("assets", {})
    for name, url in assets.items():
        low = name.lower()
        if low.endswith(".sha256") and "ui" in low and "windows" in low:
            return url
    return None


def fetch_checksum(url: str, *, timeout: int = 15) -> str:
    """Download a ``sha256sum``-style file and return the hex digest.

    The file is expected to contain ``<hex>  <filename>`` (coreutils format);
    we take the first whitespace-delimited token.
    """
    if not _is_trusted_url(url):
        raise ValueError(f"refusing to fetch checksum from untrusted URL: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "riplex"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", "replace").strip()
    token = text.split()[0] if text else ""
    if len(token) != 64 or any(c not in "0123456789abcdefABCDEF" for c in token):
        raise ValueError("checksum file did not contain a valid SHA-256 digest")
    return token.lower()


def sha256_of(path: Path) -> str:
    """Return the SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _looks_like_windows_exe(path: Path) -> bool:
    """Cheap sanity check that a file is a PE executable (starts with 'MZ')."""
    try:
        with open(path, "rb") as fh:
            return fh.read(2) == b"MZ"
    except OSError:
        return False


def download_file(url: str, dest: Path, *, progress=None, timeout: int = 30) -> Path:
    """Download *url* to *dest*, verifying the byte count against Content-Length.

    ``progress`` is an optional ``callable(got, total)`` for UI feedback.
    """
    if not _is_trusted_url(url):
        raise ValueError(f"refusing to download from untrusted URL: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "riplex"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length", 0) or 0)
        got = 0
        with open(dest, "wb") as out:
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                out.write(chunk)
                got += len(chunk)
                if progress and total:
                    progress(got, total)
    if total and got != total:
        dest.unlink(missing_ok=True)
        raise IOError(f"incomplete download: {got}/{total} bytes")
    return dest


def stage_update(update_info: dict, *, progress=None) -> Path:
    """Download + verify the new executable, returning the staged file path.

    Does NOT modify the running exe — call :func:`swap_executable` (or
    :func:`apply_update_and_relaunch`) after. Raises on any failure and leaves
    the running install untouched.
    """
    if not can_self_update():
        raise RuntimeError("in-place update is not available for this build")

    url = get_download_url(update_info)
    if not url or url == update_info.get("url"):
        raise RuntimeError("no downloadable executable asset for this platform")

    current = running_executable()
    staged = current.with_name(current.name + _STAGING_SUFFIX)
    staged.unlink(missing_ok=True)

    download_file(url, staged, progress=progress)

    checksum_url = get_checksum_url(update_info)
    if checksum_url:
        expected = fetch_checksum(checksum_url)
        actual = sha256_of(staged)
        if actual != expected:
            staged.unlink(missing_ok=True)
            raise RuntimeError(
                f"checksum mismatch (expected {expected[:12]}…, got {actual[:12]}…)"
            )
    elif not _looks_like_windows_exe(staged):
        staged.unlink(missing_ok=True)
        raise RuntimeError("downloaded file is not a valid Windows executable")

    return staged


def swap_executable(current: Path, staged: Path) -> Path:
    """Rename-swap the running exe with *staged*; return the backup path.

    Windows permits renaming a running executable. The old exe is moved to
    ``<name>.old`` (deleted on next launch by :func:`cleanup_stale_update`). On
    failure the original is rolled back into place and the error re-raised.
    """
    backup = current.with_name(current.name + _BACKUP_SUFFIX)
    if backup.exists():
        try:
            backup.unlink()
        except OSError:
            pass  # locked leftover; os.replace below will still work to a new name

    os.replace(current, backup)          # move the running exe aside
    try:
        os.replace(staged, current)      # move the new exe into place
    except OSError:
        os.replace(backup, current)      # roll back
        raise
    return backup


def apply_update_and_relaunch(staged: Path) -> None:
    """Swap in *staged*, relaunch the app, and terminate this process.

    This does not return on success. Callers should have already downloaded and
    verified *staged* via :func:`stage_update`.
    """
    current = running_executable()
    swap_executable(current, staged)

    creationflags = 0
    if sys.platform == "win32":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP so the child outlives us.
        creationflags = 0x00000008 | 0x00000200

    subprocess.Popen([str(current)], close_fds=True, creationflags=creationflags)
    os._exit(0)


def cleanup_stale_update(exe: Path | None = None) -> None:
    """Delete a leftover ``<exe>.old`` (and ``.new``) from a prior update.

    Safe to call unconditionally at startup; a no-op when nothing is staged or
    when not frozen.
    """
    if exe is None:
        if not is_frozen():
            return
        exe = running_executable()
    for suffix in (_BACKUP_SUFFIX, _STAGING_SUFFIX):
        leftover = exe.with_name(exe.name + suffix)
        if leftover.exists():
            try:
                leftover.unlink()
            except OSError:
                pass  # still locked (rare); will retry next launch

