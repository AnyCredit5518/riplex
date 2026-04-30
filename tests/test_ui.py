"""Tests for riplex.ui interactive prompt utilities."""

from __future__ import annotations

import io

import pytest

from riplex import ui


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_interactive(monkeypatch, interactive: bool = True):
    """Force is_interactive() to return a fixed value."""
    monkeypatch.setattr(ui, "_auto_mode", not interactive)
    if interactive:
        monkeypatch.setattr("sys.stdin", io.StringIO())  # isatty() = False
        # Override isatty for tests: force True
        monkeypatch.setattr(ui, "is_interactive", lambda: True)
    else:
        monkeypatch.setattr(ui, "is_interactive", lambda: False)


# ---------------------------------------------------------------------------
# is_interactive / set_auto_mode
# ---------------------------------------------------------------------------

class TestIsInteractive:
    def test_auto_mode_disables_interactive(self, monkeypatch):
        monkeypatch.setattr(ui, "_auto_mode", True)
        assert ui.is_interactive() is False

    def test_non_tty_disables_interactive(self, monkeypatch):
        monkeypatch.setattr(ui, "_auto_mode", False)
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        assert ui.is_interactive() is False

    def test_set_auto_mode(self, monkeypatch):
        monkeypatch.setattr(ui, "_auto_mode", False)
        ui.set_auto_mode(True)
        assert ui._auto_mode is True
        ui.set_auto_mode(False)
        assert ui._auto_mode is False


# ---------------------------------------------------------------------------
# prompt_choice
# ---------------------------------------------------------------------------

class TestPromptChoice:
    def test_returns_default_when_non_interactive(self, monkeypatch):
        _patch_interactive(monkeypatch, False)
        result = prompt_choice("Pick:", ["A", "B", "C"], default=1)
        assert result == 1

    def test_returns_default_on_empty_input(self, monkeypatch, capsys):
        _patch_interactive(monkeypatch, True)
        monkeypatch.setattr("builtins.input", lambda _: "")
        result = prompt_choice("Pick:", ["A", "B", "C"], default=2)
        assert result == 2
        out = capsys.readouterr().out
        assert "1. A" in out
        assert "2. B" in out
        assert "3. C (* recommended)" in out  # default marker on item 3 (index 2)

    def test_user_selects_option(self, monkeypatch, capsys):
        _patch_interactive(monkeypatch, True)
        monkeypatch.setattr("builtins.input", lambda _: "2")
        result = prompt_choice("Pick:", ["X", "Y", "Z"])
        assert result == 1  # 0-based index for "Y"

    def test_clamps_default_to_range(self, monkeypatch):
        _patch_interactive(monkeypatch, False)
        result = prompt_choice("Pick:", ["A"], default=99)
        assert result == 0

    def test_empty_options_returns_default(self, monkeypatch):
        _patch_interactive(monkeypatch, True)
        result = prompt_choice("Pick:", [], default=0)
        assert result == 0

    def test_eof_returns_default(self, monkeypatch):
        _patch_interactive(monkeypatch, True)
        monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError))
        result = prompt_choice("Pick:", ["A", "B"], default=1)
        assert result == 1

    def test_invalid_then_valid(self, monkeypatch, capsys):
        inputs = iter(["abc", "0", "2"])
        _patch_interactive(monkeypatch, True)
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        result = prompt_choice("Pick:", ["A", "B"])
        assert result == 1  # "2" -> index 1


# ---------------------------------------------------------------------------
# prompt_confirm
# ---------------------------------------------------------------------------

class TestPromptConfirm:
    def test_returns_default_when_non_interactive(self, monkeypatch):
        _patch_interactive(monkeypatch, False)
        assert prompt_confirm("OK?", default=True) is True
        assert prompt_confirm("OK?", default=False) is False

    def test_empty_input_returns_default(self, monkeypatch):
        _patch_interactive(monkeypatch, True)
        monkeypatch.setattr("builtins.input", lambda _: "")
        assert prompt_confirm("OK?", default=True) is True

    def test_yes_answers(self, monkeypatch):
        _patch_interactive(monkeypatch, True)
        for answer in ("y", "Y", "yes", "YES"):
            monkeypatch.setattr("builtins.input", lambda _, a=answer: a)
            assert prompt_confirm("OK?", default=False) is True

    def test_no_answers(self, monkeypatch):
        _patch_interactive(monkeypatch, True)
        for answer in ("n", "N", "no", "nope"):
            monkeypatch.setattr("builtins.input", lambda _, a=answer: a)
            assert prompt_confirm("OK?", default=True) is False

    def test_eof_returns_default(self, monkeypatch):
        _patch_interactive(monkeypatch, True)
        monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError))
        assert prompt_confirm("OK?", default=True) is True


# ---------------------------------------------------------------------------
# prompt_text
# ---------------------------------------------------------------------------

class TestPromptText:
    def test_returns_default_when_non_interactive(self, monkeypatch):
        _patch_interactive(monkeypatch, False)
        assert prompt_text("Name:", default="Foo") == "Foo"

    def test_empty_input_returns_default(self, monkeypatch):
        _patch_interactive(monkeypatch, True)
        monkeypatch.setattr("builtins.input", lambda _: "")
        assert prompt_text("Name:", default="Foo") == "Foo"

    def test_user_overrides(self, monkeypatch):
        _patch_interactive(monkeypatch, True)
        monkeypatch.setattr("builtins.input", lambda _: "Bar")
        assert prompt_text("Name:", default="Foo") == "Bar"

    def test_whitespace_stripped(self, monkeypatch):
        _patch_interactive(monkeypatch, True)
        monkeypatch.setattr("builtins.input", lambda _: "  Baz  ")
        assert prompt_text("Name:", default="Foo") == "Baz"

    def test_eof_returns_default(self, monkeypatch):
        _patch_interactive(monkeypatch, True)
        monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(KeyboardInterrupt))
        assert prompt_text("Name:", default="Foo") == "Foo"


# Import prompt functions at module level for convenience
from riplex.ui import prompt_choice, prompt_confirm, prompt_text
