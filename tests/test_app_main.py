import builtins

import certifi

from riplex_app import main as app_main
from riplex_app.main import _configure_flet_view_path, _configure_tls_certificates


def test_configure_tls_certificates_sets_ssl_env_when_unset():
    env = {}

    cert_path = _configure_tls_certificates(env)

    assert cert_path == certifi.where()
    assert env["SSL_CERT_FILE"] == certifi.where()
    assert env["REQUESTS_CA_BUNDLE"] == certifi.where()


def test_configure_tls_certificates_preserves_existing_ssl_env():
    env = {"SSL_CERT_FILE": "C:/custom/root-ca.pem"}

    cert_path = _configure_tls_certificates(env)

    assert cert_path == certifi.where()
    assert env["SSL_CERT_FILE"] == "C:/custom/root-ca.pem"
    assert env["REQUESTS_CA_BUNDLE"] == certifi.where()


def test_configure_tls_certificates_returns_none_without_certifi(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "certifi":
            raise ModuleNotFoundError("No module named 'certifi'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    env = {}

    assert _configure_tls_certificates(env) is None
    assert env == {}


def test_main_configures_tls_before_starting_flet(monkeypatch, tmp_path):
    calls = []

    def fake_configure_tls_certificates():
        calls.append("tls")

    def fake_flet_app(*, target):
        calls.append("flet")
        assert target is app_main.RiplexApp

    monkeypatch.setattr(app_main, "_configure_tls_certificates", fake_configure_tls_certificates)
    monkeypatch.setattr(app_main.ft, "app", fake_flet_app)
    monkeypatch.setattr(app_main, "RiplexApp", object)
    monkeypatch.setattr("riplex_app.crash_dump.get_log_path", lambda: tmp_path / "riplex.log")

    app_main.main()

    assert calls == ["tls", "flet"]


def test_configure_flet_view_path_uses_bundled_windows_client(tmp_path):
    client_dir = tmp_path / "flet_client"
    client_dir.mkdir()
    (client_dir / "flet.exe").write_text("", encoding="utf-8")
    env = {}

    flet_view_path = _configure_flet_view_path(env, tmp_path, "win32")

    assert flet_view_path == str(client_dir)
    assert env["FLET_VIEW_PATH"] == str(client_dir)


def test_configure_flet_view_path_uses_bundled_macos_client(tmp_path):
    client_dir = tmp_path / "flet_client"
    client_dir.mkdir()
    (client_dir / "Flet.app").mkdir()
    env = {}

    flet_view_path = _configure_flet_view_path(env, tmp_path, "darwin")

    assert flet_view_path == str(client_dir)
    assert env["FLET_VIEW_PATH"] == str(client_dir)


def test_configure_flet_view_path_preserves_existing_override(tmp_path):
    env = {"FLET_VIEW_PATH": "C:/custom/flet"}

    flet_view_path = _configure_flet_view_path(env, tmp_path, "win32")

    assert flet_view_path == "C:/custom/flet"
    assert env["FLET_VIEW_PATH"] == "C:/custom/flet"