"""CLI callers must use the same enriched disc analysis as title selection."""

import argparse
from pathlib import Path
from types import SimpleNamespace

import pytest

from riplex.disc.analysis import analyze_disc
from riplex.disc.makemkv import DiscInfo, DiscTitle
from riplex.metadata.provider import EpisodeMetadata, SeasonMetadata, ShowDetail
from riplex.models import PlannedDisc, PlannedEpisode, PlannedSeason, PlannedShow
from riplex.output_paths import RipOutputPreflight
from tests.support.disc_fixtures import load_disc_fixture, load_show_detail


@pytest.mark.asyncio
@pytest.mark.parametrize("command,resume", [("rip", False), ("orchestrate", False), ("orchestrate", True)])
@pytest.mark.parametrize("season_scoped", [False, True])
async def test_cli_pacific_uses_available_tmdb_metadata(
    command, resume, season_scoped, tmp_path, monkeypatch, capsys,
):
    import riplex.disc.makemkv as makemkv_module
    from riplex_cli.commands import orchestrate, rip

    module = rip if command == "rip" else orchestrate
    info, discs, _expected = load_disc_fixture("pacific_disc1.json")
    detail = load_show_detail("pacific_disc1.json")
    disc_number = 1
    expected_labels = ["S01E01 - Guadalcanal/Leckie", "S01E02 - Basilone"]
    if season_scoped:
        # Complete-series metadata can repeat names across seasons. The
        # inserted disc's label must scope enrichment before matching names.
        detail = ShowDetail("tv:1", "Show", 2020, seasons=[
            SeasonMetadata(number, episodes=[
                EpisodeMetadata(number, 1, "Pilot", 3000 + offset),
                EpisodeMetadata(number, 2, "Second", 3100 + offset),
            ])
            for number, offset in [(1, 0), (2, 600)]
        ])
        discs = [PlannedDisc(number, "Blu-ray", title=f"Season {number}", episodes=[
            PlannedEpisode(number, 1, "Pilot", ""),
            PlannedEpisode(number, 2, "Second", ""),
        ]) for number in (1, 2)]
        info = DiscInfo("SHOW_D2", "Blu-ray disc", titles=[
            DiscTitle(index, name=f"Title {index}", duration_seconds=runtime,
                      size_bytes=(index + 1) * 10_000_000_000, chapters=8,
                      filename=f"title_t{index:02d}.mkv", playlist="",
                      resolution="1920x1080", video_codec="Mpeg4", segment_count=1)
            for index, runtime in [(0, 3600), (1, 3700)]
        ])
        disc_number = 2
        expected_labels = ["S02E01 - Pilot", "S02E02 - Second"]
    planned = PlannedShow(detail.title, detail.year, seasons=[
        PlannedSeason(season.season_number, episodes=[
            PlannedEpisode(
                episode.season_number, episode.episode_number, episode.title,
                runtime="", runtime_seconds=episode.runtime_seconds,
            )
            for episode in season.episodes
        ])
        for season in detail.seasons
    ])
    metadata = SimpleNamespace(
        canonical=detail.title, year=detail.year, is_movie=False,
        movie_runtime=None, discs=discs, release_name="Blu-ray ALL America - HBO",
        dvdcompare_error=None, season_number=None, disc_format="Blu-ray",
        dvdcompare_film_title="Pacific (The) (Mini-series)",
        tmdb_match=SimpleNamespace(source_id=detail.source_id),
        **({"show_detail": detail} if resume else {"planned": planned}),
    )
    drive = SimpleNamespace(
        index=0, has_disc=True, disc_label=info.disc_name, device="D:",
    )
    captured_analyses = []

    def record_analysis(*args, **kwargs):
        result = analyze_disc(*args, **kwargs)
        captured_analyses.append(result)
        return result

    class FakeProvider:
        def __init__(self, **kwargs):
            pass

        async def close(self):
            pass

    class FakeMakeMKV:
        def __init__(self, exe):
            pass

        def resolve_drive(self, drive_arg):
            return drive

        def rip(self, *args, **kwargs):
            raise AssertionError("dry-run must never rip a physical disc")

    async def lookup(*args, **kwargs):
        assert not resume
        return metadata

    async def resumed_lookup(*args, **kwargs):
        assert resume
        return metadata

    monkeypatch.setattr(module, "setup_logging", lambda **kwargs: tmp_path / "riplex.log")
    monkeypatch.setattr(module, "preflight_configured_rip_outputs", lambda *args, **kwargs: RipOutputPreflight(
        output_root=tmp_path / "Videos", rip_output=tmp_path / "Rips",
    ))
    monkeypatch.setattr(module, "get_api_key", lambda _key: None)
    monkeypatch.setattr(module, "TmdbProvider", FakeProvider)
    monkeypatch.setattr(module, "lookup_metadata", lookup)
    monkeypatch.setattr(module, "analyze_disc", record_analysis)
    if command == "rip":
        monkeypatch.setattr(rip, "find_makemkvcon", lambda: Path("makemkvcon"))
        monkeypatch.setattr(rip, "MakeMKV", FakeMakeMKV)
        monkeypatch.setattr(rip, "run_disc_info", lambda *args: info)
    else:
        session = SimpleNamespace(title=detail.title, year=detail.year, all_ripped_discs=set())
        monkeypatch.setattr(orchestrate, "find_existing_session", lambda *args, **kwargs: session if resume else None)
        monkeypatch.setattr(orchestrate, "find_ripped_discs", lambda *args: set())
        monkeypatch.setattr(orchestrate, "resume_from_session", resumed_lookup)
        monkeypatch.setattr(orchestrate, "is_interactive", lambda: False)
        monkeypatch.setattr(makemkv_module, "find_makemkvcon", lambda: Path("makemkvcon"))
        monkeypatch.setattr(makemkv_module, "run_drive_list", lambda *args: [drive])
        monkeypatch.setattr(makemkv_module, "run_disc_info", lambda *args: info)

    args = argparse.Namespace(
        execute=False, snapshot=False, verbose=False, output=None, no_cache=False,
        drive="auto", title=detail.title, disc_format="Blu-ray", media_type="tv",
        api_key=None, year=detail.year, season_number=None, release=None,
        discs=str(disc_number), yes=True, title_policy="primary",
    )
    result = await (rip.run_rip(args) if command == "rip" else orchestrate.run_orchestrate(args))

    assert result == 0
    assert len(captured_analyses) == 1
    assert captured_analyses[0].primary_title_indices == {0, 1}
    assert [title.index for title in captured_analyses[0].rippable_titles] == [0, 1]
    output = capsys.readouterr().out
    assert all(label in output for label in expected_labels)
    assert "Will rip 2 title(s) [0, 1]" in output