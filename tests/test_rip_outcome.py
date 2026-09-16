import argparse
from pathlib import Path
from types import SimpleNamespace

import pytest

from riplex.disc.makemkv import RipResult
from riplex.output_paths import RipOutputPreflight
from riplex.rip_outcome import summarize_rip_results


def test_summarize_rip_results_distinguishes_all_failed_from_empty():
    failed = RipResult(
        title_index=1,
        success=False,
        output_file="",
        error_message="permission denied",
    )

    assert summarize_rip_results([]).all_failed is False
    assert summarize_rip_results([failed]).all_failed is True


@pytest.mark.asyncio
async def test_orchestrate_returns_failure_when_every_title_fails(
    tmp_path, monkeypatch, capsys,
):
    import riplex.disc.makemkv as makemkv_mod
    import riplex_cli.commands.orchestrate as orchestrate_mod

    title = SimpleNamespace(index=1, duration_seconds=600, size_bytes=1024)
    disc_info = SimpleNamespace(titles=[title], disc_name="MOVIE")
    drive = SimpleNamespace(
        index=0,
        has_disc=True,
        device="/dev/sr0",
        disc_label="MOVIE",
    )
    release_disc = SimpleNamespace(number=1, disc_format="DVD")
    metadata = SimpleNamespace(
        canonical="Movie",
        year=2020,
        is_movie=True,
        movie_runtime=600,
        discs=[release_disc],
        release_name="Movie DVD",
        dvdcompare_error=None,
        tmdb_match=SimpleNamespace(source_id="movie:1"),
        season_number=None,
    )
    analysis = SimpleNamespace(
        dvd_entries=[],
        total_episode_runtime=0,
        episode_count=0,
        rippable_titles=[title],
        classifications={},
        recovered_carryover_indices=set(),
        assessments={},
        next_episode_carryover=[],
    )

    class FakeProvider:
        def __init__(self, **_kwargs):
            pass

        async def close(self):
            pass

    async def fake_lookup(*_args, **_kwargs):
        return metadata

    monkeypatch.setattr(
        orchestrate_mod,
        "setup_logging",
        lambda **_kwargs: tmp_path / "riplex.log",
    )
    monkeypatch.setattr(
        orchestrate_mod,
        "preflight_configured_rip_outputs",
        lambda *_args, **_kwargs: RipOutputPreflight(
            output_root=tmp_path / "Videos",
            rip_output=tmp_path / "Rips",
        ),
    )
    monkeypatch.setattr(orchestrate_mod, "TmdbProvider", FakeProvider)
    monkeypatch.setattr(orchestrate_mod, "lookup_metadata", fake_lookup)
    monkeypatch.setattr(orchestrate_mod, "find_existing_session", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrate_mod, "find_ripped_discs", lambda *_args, **_kwargs: set())
    monkeypatch.setattr(orchestrate_mod, "write_session_marker", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(orchestrate_mod, "detect_disc_number", lambda *_args: 1)
    monkeypatch.setattr(orchestrate_mod, "disc_content_summary", lambda _disc: "1 title")
    monkeypatch.setattr(orchestrate_mod, "analyze_disc", lambda *_args, **_kwargs: analysis)
    monkeypatch.setattr(orchestrate_mod, "print_disc_analysis", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrate_mod, "prompt_choice", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(orchestrate_mod, "is_interactive", lambda: False)
    monkeypatch.setattr(makemkv_mod, "find_makemkvcon", lambda: Path("makemkvcon"))
    monkeypatch.setattr(makemkv_mod, "run_drive_list", lambda _exe: [drive])
    monkeypatch.setattr(makemkv_mod, "run_disc_info", lambda *_args: disc_info)
    monkeypatch.setattr(
        makemkv_mod,
        "run_rip",
        lambda *_args, **_kwargs: RipResult(
            title_index=1,
            success=False,
            output_file="",
            error_message="permission denied",
        ),
    )

    result = await orchestrate_mod.run_orchestrate(argparse.Namespace(
        execute=True,
        snapshot=False,
        verbose=False,
        output=None,
        no_cache=False,
        drive="auto",
        title="Movie",
        disc_format="DVD",
        media_type="movie",
        api_key=None,
        year=2020,
        season_number=None,
        release=None,
        discs=None,
        yes=True,
    ))

    assert result == 1
    assert "No discs were ripped" in capsys.readouterr().err