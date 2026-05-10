"""Tests for riplex.updater and welcome screen install logic."""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from riplex import cache
from riplex import updater
from riplex.updater import (
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
        with patch("riplex.updater.get_current_version", return_value="dev"):
            assert check_for_update() is None

    def test_returns_none_on_network_error(self):
        with patch("riplex.updater.get_current_version", return_value="0.2.3"):
            with patch("urllib.request.urlopen", side_effect=OSError("no network")):
                assert check_for_update() is None

    def test_returns_none_when_up_to_date(self):
        response_data = json.dumps([{
            "tag_name": "v0.2.3",
            "html_url": "https://github.com/AnyCredit5518/riplex/releases/tag/v0.2.3",
            "assets": [],
        }]).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("riplex.updater.get_current_version", return_value="0.2.3"):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                assert check_for_update() is None

    def test_returns_update_info_when_newer(self):
        response_data = json.dumps([{
            "tag_name": "v0.3.0",
            "html_url": "https://github.com/AnyCredit5518/riplex/releases/tag/v0.3.0",
            "body": "### Added\n- Cool feature",
            "assets": [
                {"name": "riplex-ui-windows.exe", "browser_download_url": "https://example.com/win.exe"},
                {"name": "riplex-ui-macos.zip", "browser_download_url": "https://example.com/mac.zip"},
            ],
        }]).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("riplex.updater.get_current_version", return_value="0.2.3"):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                result = check_for_update()

        assert result is not None
        assert result["tag"] == "v0.3.0"
        assert "riplex-ui-windows.exe" in result["assets"]
        assert "riplex-ui-macos.zip" in result["assets"]
        assert len(result["releases"]) == 1
        assert result["releases"][0]["tag"] == "v0.3.0"

    def test_groups_releases_by_minor_version(self):
        response_data = json.dumps([
            {"tag_name": "v0.5.2", "html_url": "url/v0.5.2", "body": "Fix 2", "assets": []},
            {"tag_name": "v0.5.1", "html_url": "url/v0.5.1", "body": "Fix 1", "assets": []},
            {"tag_name": "v0.5.0", "html_url": "url/v0.5.0", "body": "Big release", "assets": []},
            {"tag_name": "v0.4.0", "html_url": "url/v0.4.0", "body": "Old", "assets": []},
        ]).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("riplex.updater.get_current_version", return_value="0.4.0"):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                result = check_for_update()

        assert result is not None
        assert result["tag"] == "v0.5.2"
        assert len(result["releases"]) == 3
        assert [r["tag"] for r in result["releases"]] == ["v0.5.2", "v0.5.1", "v0.5.0"]

    def test_does_not_mix_major_versions(self):
        response_data = json.dumps([
            {"tag_name": "v1.0.1", "html_url": "url/v1.0.1", "body": "Patch", "assets": []},
            {"tag_name": "v1.0.0", "html_url": "url/v1.0.0", "body": "Major", "assets": []},
            {"tag_name": "v0.5.0", "html_url": "url/v0.5.0", "body": "Old minor", "assets": []},
        ]).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("riplex.updater.get_current_version", return_value="0.5.0"):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                result = check_for_update()

        assert result is not None
        assert result["tag"] == "v1.0.1"
        # Should only contain v1.0.x, not v0.5.0
        assert len(result["releases"]) == 2
        assert [r["tag"] for r in result["releases"]] == ["v1.0.1", "v1.0.0"]


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
            "makemkvcon": "GuinpinSoft.MakeMKV",
            "ffprobe": "Gyan.FFmpeg",
            "mkvmerge": "MoritzBunkus.MKVToolNix",
        }
        missing = ["ffprobe", "mkvmerge"]
        to_install = sorted(set(packages[t] for t in missing if packages.get(t)))
        assert to_install == ["Gyan.FFmpeg", "MoritzBunkus.MKVToolNix"]

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
            "mkvmerge": "MoritzBunkus.MKVToolNix",
            "mkvpropedit": "MoritzBunkus.MKVToolNix",
        }
        missing = ["mkvmerge", "mkvpropedit"]
        to_install = sorted(set(packages[t] for t in missing if packages.get(t)))
        assert to_install == ["MoritzBunkus.MKVToolNix"]


# ---------------------------------------------------------------------------
# Cached check + suppression + notice formatting
# ---------------------------------------------------------------------------


@pytest.fixture
def _isolated_cache(tmp_path, monkeypatch):
    """Redirect the cache to a tmp dir for each test."""
    monkeypatch.setattr(cache, "get_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(cache, "_disabled", False)
    yield


@pytest.fixture
def _force_version(monkeypatch):
    """Pretend an installed version so the updater does not bail on 'dev'."""
    monkeypatch.setattr(updater, "__version__", "0.6.0")
    monkeypatch.setattr(updater, "get_current_version", lambda: "0.6.0")


class TestSuppressionEnv:
    def test_default(self, monkeypatch):
        monkeypatch.delenv(updater._SUPPRESS_ENV_VAR, raising=False)
        assert updater.is_check_suppressed() is False

    @pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on"])
    def test_truthy_values(self, monkeypatch, val):
        monkeypatch.setenv(updater._SUPPRESS_ENV_VAR, val)
        assert updater.is_check_suppressed() is True

    @pytest.mark.parametrize("val", ["0", "false", "no", "off", ""])
    def test_falsy_values(self, monkeypatch, val):
        monkeypatch.setenv(updater._SUPPRESS_ENV_VAR, val)
        assert updater.is_check_suppressed() is False


class TestCheckForUpdateCached:
    def test_suppressed_returns_none(self, monkeypatch, _isolated_cache, _force_version):
        monkeypatch.setenv(updater._SUPPRESS_ENV_VAR, "1")
        with patch.object(updater, "check_for_update") as mock_check:
            assert updater.check_for_update_cached() is None
        mock_check.assert_not_called()

    def test_dev_version_returns_none(self, monkeypatch, _isolated_cache):
        monkeypatch.setattr(updater, "get_current_version", lambda: "dev")
        with patch.object(updater, "check_for_update") as mock_check:
            assert updater.check_for_update_cached() is None
        mock_check.assert_not_called()

    def test_uses_cache_on_second_call(self, _isolated_cache, _force_version):
        fake = {"tag": "v0.6.2", "url": "https://example/release"}
        with patch.object(updater, "check_for_update", return_value=fake) as mock_check:
            first = updater.check_for_update_cached()
            second = updater.check_for_update_cached()
        assert first == fake
        assert second == fake
        assert mock_check.call_count == 1

    def test_caches_negative_result(self, _isolated_cache, _force_version):
        with patch.object(updater, "check_for_update", return_value=None) as mock_check:
            first = updater.check_for_update_cached()
            second = updater.check_for_update_cached()
        assert first is None
        assert second is None
        assert mock_check.call_count == 1


class TestFormatUpdateNotice:
    def test_includes_version_arrow(self, monkeypatch):
        monkeypatch.setattr(updater, "get_current_version", lambda: "0.6.0")
        info = {"tag": "v0.6.2", "url": "https://example/release"}
        notice = updater.format_update_notice(info)
        assert "0.6.0 -> 0.6.2" in notice
        assert "pipx upgrade riplex" in notice
        assert "https://example/release" in notice

    def test_omits_url_when_missing(self, monkeypatch):
        monkeypatch.setattr(updater, "get_current_version", lambda: "0.6.0")
        info = {"tag": "v0.6.2", "url": ""}
        notice = updater.format_update_notice(info)
        assert "Release notes:" not in notice
        assert "0.6.0 -> 0.6.2" in notice

    def test_custom_command(self, monkeypatch):
        monkeypatch.setattr(updater, "get_current_version", lambda: "0.6.0")
        info = {"tag": "v0.6.2", "url": "https://example/release"}
        notice = updater.format_update_notice(info, command="brew upgrade riplex")
        assert "brew upgrade riplex" in notice
