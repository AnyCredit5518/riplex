import builtins

import certifi
import flet as ft

from riplex_app import main as app_main
from riplex_app.main import (
    _append_to_footer_row,
    _button_label,
    _configure_flet_view_path,
    _configure_tls_certificates,
    _tree_has_quit,
)


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


# ---------------------------------------------------------------------------
# Footer Quit-button injection
# ---------------------------------------------------------------------------


def test_button_label_reads_flet085_content_attr():
    # Flet 0.85 stores a TextButton's label under .content (a plain str)
    # and has no .text attribute at all — verify we still read the label
    # so the Quit dedup below is reliable.
    quit_btn = ft.TextButton("Quit")

    assert getattr(quit_btn, "text", None) is None
    assert quit_btn.content == "Quit"
    assert _button_label(quit_btn) == "Quit"


def test_tree_has_quit_detects_baked_in_quit_anywhere():
    # done/orchestrate_done bake in a local Quit that may not sit in the
    # last footer row; a whole-tree scan must still find it.
    tree = ft.Column(
        [
            ft.Text("Rip complete"),
            ft.Row([ft.TextButton("Open Folder"), ft.TextButton("Quit")]),
            ft.Row([ft.TextButton("Report a Bug")]),
        ]
    )

    assert _tree_has_quit(tree) is True


def test_append_to_footer_row_skips_injection_when_quit_present():
    # A screen with its own Quit must not get a second injected Quit.
    footer = ft.Row([ft.TextButton("Open Folder"), ft.TextButton("Quit")])
    tree = ft.Column([ft.Text("Done"), footer])
    injected = ft.TextButton("Quit")

    handled = _append_to_footer_row(tree, injected)

    assert handled is True
    # Flet controls compare by value, so use identity to confirm the
    # injected Quit was NOT added on top of the baked-in one.
    assert not any(c is injected for c in footer.controls)
    assert len(footer.controls) == 2


def test_append_to_footer_row_appends_when_no_quit_present():
    # A screen without a Quit (e.g. disc_overview) gets exactly one
    # injected Quit in its last footer row.
    footer = ft.Row([ft.TextButton("Back"), ft.Button("Start Ripping")])
    tree = ft.Column([ft.Text("Disc Overview"), footer])
    injected = ft.TextButton("Quit")

    handled = _append_to_footer_row(tree, injected)

    assert handled is True
    assert footer.controls[-1] is injected