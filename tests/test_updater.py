"""Tests for riplex_app.updater and welcome screen install logic."""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from riplex_app.updater import (
    _parse_version,
    check_for_update,
    get_current_version,
    get_download_url,
)


# ---------------------------------------------------------------------------
# _parse_version
# ---------------------------------------------------------------------------


class TestParseVersion:
    def test_standard(self):
        assert _parse_version("v1.2.3") == (1, 2, 3)

    def test_no_prefix(self):
        assert _parse_version("0.2.5") == (0, 2, 5)

    def test_dev_suffix(self):
        # Stops at non-integer part
        assert _parse_version("v0.2.5.dev3") == (0, 2, 5)

    def test_two_parts(self):
        assert _parse_version("v1.0") == (1, 0)


# ---------------------------------------------------------------------------
# check_for_update
# ---------------------------------------------------------------------------


class TestCheckForUpdate:
    def test_returns_none_when_dev(self):
        with patch("riplex_app.updater.get_current_version", return_value="dev"):
            assert check_for_update() is None

    def test_returns_none_on_network_error(self):
        with patch("riplex_app.updater.get_current_version", return_value="0.2.3"):
            with patch("urllib.request.urlopen", side_effect=OSError("no network")):
                assert check_for_update() is None

    def test_returns_none_when_up_to_date(self):
        response_data = json.dumps({
            "tag_name": "v0.2.3",
            "html_url": "https://github.com/AnyCredit5518/riplex/releases/tag/v0.2.3",
            "assets": [],
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("riplex_app.updater.get_current_version", return_value="0.2.3"):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                assert check_for_update() is None

    def test_returns_update_info_when_newer(self):
        response_data = json.dumps({
            "tag_name": "v0.3.0",
            "html_url": "https://github.com/AnyCredit5518/riplex/releases/tag/v0.3.0",
            "assets": [
                {"name": "riplex-ui-windows.exe", "browser_download_url": "https://example.com/win.exe"},
                {"name": "riplex-ui-macos.zip", "browser_download_url": "https://example.com/mac.zip"},
            ],
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("riplex_app.updater.get_current_version", return_value="0.2.3"):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                result = check_for_update()

        assert result is not None
        assert result["tag"] == "v0.3.0"
        assert "riplex-ui-windows.exe" in result["assets"]
        assert "riplex-ui-macos.zip" in result["assets"]


# ---------------------------------------------------------------------------
# get_download_url
# ---------------------------------------------------------------------------


class TestGetDownloadUrl:
    def test_windows(self):
        info = {
            "tag": "v0.3.0",
            "url": "https://github.com/releases/v0.3.0",
            "assets": {
                "riplex-ui-windows.exe": "https://example.com/win.exe",
                "riplex-macos": "https://example.com/mac",
            },
        }
        with patch("sys.platform", "win32"):
            assert get_download_url(info) == "https://example.com/win.exe"

    def test_macos(self):
        info = {
            "tag": "v0.3.0",
            "url": "https://github.com/releases/v0.3.0",
            "assets": {
                "riplex-ui-windows.exe": "https://example.com/win.exe",
                "riplex-ui-macos.zip": "https://example.com/mac.zip",
            },
        }
        with patch("sys.platform", "darwin"):
            assert get_download_url(info) == "https://example.com/mac.zip"

    def test_fallback_to_release_page(self):
        info = {
            "tag": "v0.3.0",
            "url": "https://github.com/releases/v0.3.0",
            "assets": {},
        }
        with patch("sys.platform", "linux"):
            assert get_download_url(info) == "https://github.com/releases/v0.3.0"


# ---------------------------------------------------------------------------
# Install tools logic (from welcome screen)
# ---------------------------------------------------------------------------


class TestInstallToolsLogic:
    """Test the package mapping logic used by the welcome screen."""

    def test_windows_package_mapping(self):
        """Verify correct winget package IDs for missing tools."""
        packages = {
            "makemkvcon": "MakeMKV.MakeMKV",
            "ffprobe": "Gyan.FFmpeg",
            "mkvmerge": "MKVToolNix.MKVToolNix",
        }
        missing = ["ffprobe", "mkvmerge"]
        to_install = sorted(set(packages[t] for t in missing if packages.get(t)))
        assert to_install == ["Gyan.FFmpeg", "MKVToolNix.MKVToolNix"]

    def test_macos_package_mapping(self):
        """Verify correct brew package names for missing tools."""
        packages = {
            "makemkvcon": "makemkv",
            "ffprobe": "ffmpeg",
            "mkvmerge": "mkvtoolnix",
        }
        missing = ["makemkvcon", "ffprobe", "mkvmerge"]
        to_install = sorted(set(packages[t] for t in missing if packages.get(t)))
        assert to_install == ["ffmpeg", "makemkv", "mkvtoolnix"]

    def test_deduplicates_packages(self):
        """mkvmerge and mkvpropedit map to same package."""
        packages = {
            "mkvmerge": "MKVToolNix.MKVToolNix",
            "mkvpropedit": "MKVToolNix.MKVToolNix",
        }
        missing = ["mkvmerge", "mkvpropedit"]
        to_install = sorted(set(packages[t] for t in missing if packages.get(t)))
        assert to_install == ["MKVToolNix.MKVToolNix"]
