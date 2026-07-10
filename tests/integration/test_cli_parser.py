"""CLI parser + dispatch integration tests.

These drive the real ``riplex`` entry point (`main`) and argument parser to
lock down top-level behaviour: help on no command, ``--version``, and
rejection of unknown subcommands.
"""

from __future__ import annotations

import pytest

from riplex_cli import main as cli_main
from tests.support.cli import parse_args


def test_no_command_prints_help_and_exits_1(monkeypatch, capsys):
    monkeypatch.setattr(cli_main.sys, "argv", ["riplex"])

    with pytest.raises(SystemExit) as exc:
        cli_main.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "usage" in out.lower()


def test_version_flag_prints_version(monkeypatch, capsys):
    monkeypatch.setattr(cli_main.sys, "argv", ["riplex", "--version"])

    with pytest.raises(SystemExit) as exc:
        cli_main.main()

    assert exc.value.code == 0
    assert "riplex" in capsys.readouterr().out.lower()


def test_unknown_command_is_rejected(capsys):
    with pytest.raises(SystemExit) as exc:
        parse_args(["frobnicate"])

    # argparse exits 2 on a bad subcommand.
    assert exc.value.code == 2


@pytest.mark.parametrize("command", ["organize", "orchestrate", "rip", "lookup", "setup"])
def test_every_subcommand_parses(command, tmp_path):
    # Each subcommand requires at least its positional/None args; give the
    # ones that take a positional a throwaway value.
    argv = {
        "organize": ["organize", str(tmp_path)],
        "orchestrate": ["orchestrate"],
        "rip": ["rip"],
        "lookup": ["lookup", "The Matrix"],
        "setup": ["setup"],
    }[command]

    args = parse_args(argv)

    assert args.command == command
