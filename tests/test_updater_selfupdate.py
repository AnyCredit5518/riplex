"""Tests for the in-place self-update logic in riplex.updater."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from riplex import updater


# ---------------------------------------------------------------------------
# can_self_update / guards
# ---------------------------------------------------------------------------

class TestCanSelfUpdate:
    def test_false_when_not_frozen(self, monkeypatch):
        monkeypatch.setattr(updater, "is_frozen", lambda: False)
        monkeypatch.setattr(updater.sys, "platform", "win32")
        assert updater.can_self_update() is False

    def test_false_on_non_windows(self, monkeypatch, tmp_path):
        monkeypatch.setattr(updater, "is_frozen", lambda: True)
        monkeypatch.setattr(updater.sys, "platform", "darwin")
        monkeypatch.setattr(updater, "running_executable", lambda: tmp_path / "riplex-ui")
        assert updater.can_self_update() is False

    def test_true_when_frozen_windows_writable(self, monkeypatch, tmp_path):
        monkeypatch.setattr(updater, "is_frozen", lambda: True)
        monkeypatch.setattr(updater.sys, "platform", "win32")
        monkeypatch.setattr(updater, "running_executable", lambda: tmp_path / "riplex-ui.exe")
        assert updater.can_self_update() is True


# ---------------------------------------------------------------------------
# URL trust
# ---------------------------------------------------------------------------

class TestTrustedUrl:
    @pytest.mark.parametrize("url", [
        "https://github.com/AnyCredit5518/riplex/releases/download/v1/riplex-ui-windows.exe",
        "https://objects.githubusercontent.com/abc/riplex-ui-windows.exe",
    ])
    def test_trusted(self, url):
        assert updater._is_trusted_url(url) is True

    @pytest.mark.parametrize("url", [
        "http://github.com/x.exe",              # not https
        "https://evil.com/riplex-ui-windows.exe",
        "https://github.com.evil.com/x.exe",    # suffix trick
        "ftp://github.com/x.exe",
    ])
    def test_untrusted(self, url):
        assert updater._is_trusted_url(url) is False


# ---------------------------------------------------------------------------
# checksum + hashing
# ---------------------------------------------------------------------------

def _fake_urlopen(payload: bytes, *, content_length: int | None = None):
    class _Resp(io.BytesIO):
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()
            return False

    resp = _Resp(payload)
    resp.headers = {"Content-Length": str(content_length if content_length is not None else len(payload))}
    return resp


class TestChecksum:
    def test_sha256_of(self, tmp_path):
        f = tmp_path / "blob"
        f.write_bytes(b"hello world")
        assert updater.sha256_of(f) == hashlib.sha256(b"hello world").hexdigest()

    def test_fetch_checksum_parses_coreutils_format(self, monkeypatch):
        digest = "a" * 64
        monkeypatch.setattr(
            updater.urllib.request, "urlopen",
            lambda *a, **k: _fake_urlopen(f"{digest}  riplex-ui-windows.exe\n".encode()),
        )
        assert updater.fetch_checksum("https://github.com/x.sha256") == digest

    def test_fetch_checksum_rejects_garbage(self, monkeypatch):
        monkeypatch.setattr(
            updater.urllib.request, "urlopen",
            lambda *a, **k: _fake_urlopen(b"not-a-hash\n"),
        )
        with pytest.raises(ValueError):
            updater.fetch_checksum("https://github.com/x.sha256")

    def test_fetch_checksum_rejects_untrusted_host(self):
        with pytest.raises(ValueError):
            updater.fetch_checksum("https://evil.com/x.sha256")


class TestPeHeader:
    def test_recognizes_pe(self, tmp_path):
        exe = tmp_path / "a.exe"
        exe.write_bytes(b"MZ\x90\x00rest")
        assert updater._looks_like_windows_exe(exe) is True

    def test_rejects_non_pe(self, tmp_path):
        txt = tmp_path / "a.txt"
        txt.write_bytes(b"hello")
        assert updater._looks_like_windows_exe(txt) is False


# ---------------------------------------------------------------------------
# download_file
# ---------------------------------------------------------------------------

class TestDownloadFile:
    def test_downloads_and_reports_progress(self, monkeypatch, tmp_path):
        payload = b"x" * 5000
        monkeypatch.setattr(
            updater.urllib.request, "urlopen",
            lambda *a, **k: _fake_urlopen(payload),
        )
        seen = []
        dest = tmp_path / "out.bin"
        updater.download_file("https://github.com/a.bin", dest, progress=lambda g, t: seen.append((g, t)))
        assert dest.read_bytes() == payload
        assert seen and seen[-1][0] == len(payload)

    def test_rejects_untrusted_url(self, tmp_path):
        with pytest.raises(ValueError):
            updater.download_file("https://evil.com/a.bin", tmp_path / "x")

    def test_incomplete_download_raises(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            updater.urllib.request, "urlopen",
            lambda *a, **k: _fake_urlopen(b"short", content_length=999),
        )
        with pytest.raises(IOError):
            updater.download_file("https://github.com/a.bin", tmp_path / "x")


# ---------------------------------------------------------------------------
# swap_executable / cleanup
# ---------------------------------------------------------------------------

class TestSwapExecutable:
    def test_swap_moves_new_into_place_and_backs_up(self, tmp_path):
        current = tmp_path / "riplex-ui.exe"
        current.write_bytes(b"OLD")
        staged = tmp_path / "riplex-ui.exe.new"
        staged.write_bytes(b"NEW")

        backup = updater.swap_executable(current, staged)

        assert current.read_bytes() == b"NEW"
        assert backup.read_bytes() == b"OLD"
        assert not staged.exists()

    def test_swap_replaces_stale_backup(self, tmp_path):
        current = tmp_path / "riplex-ui.exe"
        current.write_bytes(b"OLD2")
        staged = tmp_path / "riplex-ui.exe.new"
        staged.write_bytes(b"NEW2")
        (tmp_path / "riplex-ui.exe.old").write_bytes(b"ANCIENT")

        updater.swap_executable(current, staged)

        assert current.read_bytes() == b"NEW2"


class TestCleanupStaleUpdate:
    def test_removes_old_and_new(self, tmp_path):
        exe = tmp_path / "riplex-ui.exe"
        exe.write_bytes(b"cur")
        (tmp_path / "riplex-ui.exe.old").write_bytes(b"old")
        (tmp_path / "riplex-ui.exe.new").write_bytes(b"new")

        updater.cleanup_stale_update(exe)

        assert exe.exists()
        assert not (tmp_path / "riplex-ui.exe.old").exists()
        assert not (tmp_path / "riplex-ui.exe.new").exists()

    def test_noop_when_nothing_staged(self, tmp_path):
        exe = tmp_path / "riplex-ui.exe"
        exe.write_bytes(b"cur")
        updater.cleanup_stale_update(exe)  # must not raise
        assert exe.exists()


# ---------------------------------------------------------------------------
# get_checksum_url
# ---------------------------------------------------------------------------

class TestGetChecksumUrl:
    def test_finds_windows_ui_checksum(self):
        info = {"assets": {
            "riplex-ui-windows.exe": "https://github.com/a.exe",
            "riplex-ui-windows.exe.sha256": "https://github.com/a.exe.sha256",
            "riplex-ui-macos.zip.sha256": "https://github.com/m.zip.sha256",
        }}
        assert updater.get_checksum_url(info) == "https://github.com/a.exe.sha256"

    def test_none_when_absent(self):
        assert updater.get_checksum_url({"assets": {}}) is None


# ---------------------------------------------------------------------------
# stage_update (end to end with the network + swap mocked)
# ---------------------------------------------------------------------------

class TestStageUpdate:
    def _info(self):
        return {
            "url": "https://github.com/AnyCredit5518/riplex/releases/tag/v2",
            "assets": {
                "riplex-ui-windows.exe": "https://github.com/a/riplex-ui-windows.exe",
                "riplex-ui-windows.exe.sha256": "https://github.com/a/riplex-ui-windows.exe.sha256",
            },
        }

    def _prep(self, monkeypatch, tmp_path):
        monkeypatch.setattr(updater, "can_self_update", lambda: True)
        monkeypatch.setattr(updater.sys, "platform", "win32")
        monkeypatch.setattr(updater, "running_executable", lambda: tmp_path / "riplex-ui.exe")

    def test_success_verifies_checksum(self, monkeypatch, tmp_path):
        self._prep(monkeypatch, tmp_path)
        payload = b"MZnew-binary"

        def _dl(url, dest, *, progress=None, timeout=30):
            Path(dest).write_bytes(payload)
            return Path(dest)

        monkeypatch.setattr(updater, "download_file", _dl)
        monkeypatch.setattr(updater, "fetch_checksum", lambda url: hashlib.sha256(payload).hexdigest())

        staged = updater.stage_update(self._info())

        assert staged.read_bytes() == payload
        assert staged.name == "riplex-ui.exe.new"

    def test_checksum_mismatch_raises_and_cleans_up(self, monkeypatch, tmp_path):
        self._prep(monkeypatch, tmp_path)

        def _dl(url, dest, *, progress=None, timeout=30):
            Path(dest).write_bytes(b"MZbad")
            return Path(dest)

        monkeypatch.setattr(updater, "download_file", _dl)
        monkeypatch.setattr(updater, "fetch_checksum", lambda url: "0" * 64)

        with pytest.raises(RuntimeError, match="checksum"):
            updater.stage_update(self._info())
        assert not (tmp_path / "riplex-ui.exe.new").exists()

    def test_raises_when_cannot_self_update(self, monkeypatch):
        monkeypatch.setattr(updater, "can_self_update", lambda: False)
        with pytest.raises(RuntimeError):
            updater.stage_update({"assets": {}, "url": "x"})
