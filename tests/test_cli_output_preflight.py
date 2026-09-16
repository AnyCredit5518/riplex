import argparse
from pathlib import Path

import pytest


def _blocked_paths(tmp_path):
    output_root = tmp_path / "Videos"
    blocked_parent = tmp_path / "Riplex"
    blocked_parent.write_text("not a directory", encoding="utf-8")
    return output_root, blocked_parent / "Raw"


@pytest.mark.asyncio
async def test_rip_rejects_unusable_output_before_drive_scan(
    tmp_path, monkeypatch, capsys,
):
    import riplex.config as config_mod
    import riplex_cli.commands.rip as rip_mod

    output_root, rip_output = _blocked_paths(tmp_path)
    monkeypatch.setattr(rip_mod, "setup_logging", lambda **kwargs: tmp_path / "riplex.log")
    monkeypatch.setattr(config_mod, "load_config", lambda: {
        "output_root": str(output_root),
        "rip_output": str(rip_output),
    })
    monkeypatch.setattr(rip_mod, "find_makemkvcon", lambda: Path("makemkvcon"))

    class UnexpectedDriveScan:
        def __init__(self, exe):
            pass

        def resolve_drive(self, drive):
            raise AssertionError("drive scan should not run")

    monkeypatch.setattr(rip_mod, "MakeMKV", UnexpectedDriveScan)

    result = await rip_mod.run_rip(argparse.Namespace(
        execute=True,
        verbose=False,
        output=None,
        no_cache=False,
    ))

    captured = capsys.readouterr()
    assert result == 1
    assert str(rip_output) in captured.err
    assert "riplex setup" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.asyncio
async def test_orchestrate_rejects_unusable_output_before_drive_scan(
    tmp_path, monkeypatch, capsys,
):
    import riplex.config as config_mod
    import riplex.disc.makemkv as makemkv_mod
    import riplex_cli.commands.orchestrate as orchestrate_mod

    output_root, rip_output = _blocked_paths(tmp_path)
    monkeypatch.setattr(
        orchestrate_mod,
        "setup_logging",
        lambda **kwargs: tmp_path / "riplex.log",
    )
    monkeypatch.setattr(config_mod, "load_config", lambda: {
        "output_root": str(output_root),
        "rip_output": str(rip_output),
    })
    monkeypatch.setattr(makemkv_mod, "find_makemkvcon", lambda: Path("makemkvcon"))

    def unexpected_drive_scan(exe):
        raise AssertionError("drive scan should not run")

    monkeypatch.setattr(makemkv_mod, "run_drive_list", unexpected_drive_scan)

    result = await orchestrate_mod.run_orchestrate(argparse.Namespace(
        execute=True,
        snapshot=False,
        verbose=False,
        output=None,
        no_cache=False,
    ))

    captured = capsys.readouterr()
    assert result == 1
    assert str(rip_output) in captured.err
    assert "riplex setup" in captured.err
    assert "Traceback" not in captured.err