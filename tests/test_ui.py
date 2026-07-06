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
from riplex.ui import (
    _parse_index_spec,
    prompt_choice,
    prompt_confirm,
    prompt_proceed_or_edit,
    prompt_rip_selection,
    prompt_text,
)


# ---------------------------------------------------------------------------
# _parse_index_spec
# ---------------------------------------------------------------------------

class TestParseIndexSpec:
    def test_single_index(self):
        assert _parse_index_spec("3", [1, 2, 3, 4]) == [3]

    def test_comma_list(self):
        assert _parse_index_spec("1,3", [1, 2, 3, 4]) == [1, 3]

    def test_range(self):
        assert _parse_index_spec("2-4", [1, 2, 3, 4, 5]) == [2, 3, 4]

    def test_mixed(self):
        assert _parse_index_spec("1,3-5,7", list(range(1, 10))) == [1, 3, 4, 5, 7]

    def test_reversed_range(self):
        assert _parse_index_spec("5-3", [1, 2, 3, 4, 5]) == [3, 4, 5]

    def test_range_skips_missing_valid(self):
        # Range endpoints valid but a middle index is not on disc: skip it.
        assert _parse_index_spec("1-4", [1, 2, 4]) == [1, 2, 4]

    def test_unknown_index_raises(self):
        with pytest.raises(ValueError, match="does not exist"):
            _parse_index_spec("99", [1, 2, 3])

    def test_non_numeric_raises(self):
        with pytest.raises(ValueError, match="invalid index"):
            _parse_index_spec("abc", [1, 2, 3])

    def test_invalid_range_raises(self):
        with pytest.raises(ValueError, match="invalid range"):
            _parse_index_spec("1-x", [1, 2, 3])

    def test_empty_input_raises(self):
        with pytest.raises(ValueError, match="no valid indices"):
            _parse_index_spec(",  ,", [1, 2, 3])


# ---------------------------------------------------------------------------
# prompt_proceed_or_edit
# ---------------------------------------------------------------------------

class TestPromptProceedOrEdit:
    def test_returns_yes_when_non_interactive(self, monkeypatch):
        _patch_interactive(monkeypatch, False)
        assert prompt_proceed_or_edit() == "yes"

    def test_empty_defaults_to_yes(self, monkeypatch):
        _patch_interactive(monkeypatch, True)
        monkeypatch.setattr("builtins.input", lambda _: "")
        assert prompt_proceed_or_edit() == "yes"

    def test_yes_answers(self, monkeypatch):
        _patch_interactive(monkeypatch, True)
        for a in ("y", "Y", "yes", "YES"):
            monkeypatch.setattr("builtins.input", lambda _, a=a: a)
            assert prompt_proceed_or_edit() == "yes"

    def test_no_answer(self, monkeypatch):
        _patch_interactive(monkeypatch, True)
        for a in ("n", "N", "no"):
            monkeypatch.setattr("builtins.input", lambda _, a=a: a)
            assert prompt_proceed_or_edit() == "no"

    def test_edit_answer(self, monkeypatch):
        _patch_interactive(monkeypatch, True)
        for a in ("e", "E", "edit", "EDIT"):
            monkeypatch.setattr("builtins.input", lambda _, a=a: a)
            assert prompt_proceed_or_edit() == "edit"

    def test_eof_returns_no(self, monkeypatch):
        _patch_interactive(monkeypatch, True)
        monkeypatch.setattr(
            "builtins.input",
            lambda _: (_ for _ in ()).throw(EOFError),
        )
        assert prompt_proceed_or_edit() == "no"


# ---------------------------------------------------------------------------
# prompt_rip_selection
# ---------------------------------------------------------------------------

class _FakeTitle:
    """Duck-typed makemkv DiscTitle for picker tests."""

    def __init__(self, index, duration_seconds=1800, size_bytes=2_147_483_648):
        self.index = index
        self.duration_seconds = duration_seconds
        self.size_bytes = size_bytes


def _titles(*indices):
    return [_FakeTitle(i) for i in indices]


class TestPromptRipSelection:
    def test_returns_default_when_non_interactive(self, monkeypatch):
        _patch_interactive(monkeypatch, False)
        result = prompt_rip_selection(_titles(1, 2, 3), [1, 3])
        assert result == [1, 3]

    def test_empty_titles_returns_default(self, monkeypatch):
        _patch_interactive(monkeypatch, True)
        assert prompt_rip_selection([], [1, 2]) == [1, 2]

    def test_done_accepts_default(self, monkeypatch, capsys):
        _patch_interactive(monkeypatch, True)
        monkeypatch.setattr("builtins.input", lambda _: "done")
        result = prompt_rip_selection(_titles(1, 2, 3), [1, 3])
        assert result == [1, 3]

    def test_enter_accepts_default(self, monkeypatch):
        _patch_interactive(monkeypatch, True)
        monkeypatch.setattr("builtins.input", lambda _: "")
        result = prompt_rip_selection(_titles(1, 2, 3), [1, 3])
        assert result == [1, 3]

    def test_toggle_adds_and_removes(self, monkeypatch):
        _patch_interactive(monkeypatch, True)
        inputs = iter(["2", "1", ""])  # add 2, remove 1, accept
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        result = prompt_rip_selection(_titles(1, 2, 3), [1, 3])
        assert result == [2, 3]

    def test_all_selects_everything(self, monkeypatch):
        _patch_interactive(monkeypatch, True)
        inputs = iter(["all", ""])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        result = prompt_rip_selection(_titles(0, 1, 2, 5), [1])
        assert result == [0, 1, 2, 5]

    def test_none_deselects_everything(self, monkeypatch):
        _patch_interactive(monkeypatch, True)
        inputs = iter(["none", ""])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        result = prompt_rip_selection(_titles(1, 2), [1, 2])
        assert result == []

    def test_default_restores_recommendation(self, monkeypatch):
        _patch_interactive(monkeypatch, True)
        inputs = iter(["none", "default", ""])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        result = prompt_rip_selection(_titles(1, 2, 3), [2])
        assert result == [2]

    def test_cancel_returns_none(self, monkeypatch):
        _patch_interactive(monkeypatch, True)
        monkeypatch.setattr("builtins.input", lambda _: "cancel")
        assert prompt_rip_selection(_titles(1, 2), [1]) is None

    def test_range_toggle(self, monkeypatch):
        _patch_interactive(monkeypatch, True)
        inputs = iter(["2-4", ""])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        result = prompt_rip_selection(_titles(1, 2, 3, 4, 5), [1])
        assert result == [1, 2, 3, 4]

    def test_invalid_input_reprompts(self, monkeypatch, capsys):
        _patch_interactive(monkeypatch, True)
        inputs = iter(["99", ""])  # bogus index then accept
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        result = prompt_rip_selection(_titles(1, 2), [1])
        assert result == [1]
        out = capsys.readouterr().out
        assert "does not exist" in out

    def test_eof_returns_none(self, monkeypatch):
        _patch_interactive(monkeypatch, True)
        monkeypatch.setattr(
            "builtins.input",
            lambda _: (_ for _ in ()).throw(EOFError),
        )
        assert prompt_rip_selection(_titles(1, 2), [1]) is None

    def test_classifications_appear_in_output(self, monkeypatch, capsys):
        _patch_interactive(monkeypatch, True)
        monkeypatch.setattr("builtins.input", lambda _: "")
        prompt_rip_selection(
            _titles(1, 2),
            [1],
            classifications={1: "MAIN FILM", 2: "SKIP: junk"},
        )
        out = capsys.readouterr().out
        assert "MAIN FILM" in out
        assert "SKIP: junk" in out
        # Selected marker
        assert "[x]" in out
        assert "[ ]" in out
