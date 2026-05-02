"""Tests for CLI utility functions."""

import json

import pytest

from riplex_cli.formatting import (
    build_execute_command as _build_execute_command,
    dry_run_banner as _dry_run_banner,
    execute_hint as _execute_hint,
)
from riplex.detect import infer_media_type
from riplex.disc.provider import detect_disc_format, disc_content_summary
from riplex.manifest import build_scanned_from_manifests, find_ripped_discs
from riplex.title import infer_title_from_scanned, parse_volume_label, strip_year_from_title
from riplex.models import PlannedDisc, PlannedEpisode, PlannedExtra, ScannedDisc, ScannedFile


# ---------------------------------------------------------------------------
# _strip_year_from_title
# ---------------------------------------------------------------------------


class TestStripYearFromTitle:
    def test_trailing_year(self):
        assert strip_year_from_title("Waterworld (1995)") == ("Waterworld", 1995)

    def test_no_year(self):
        assert strip_year_from_title("Waterworld") == ("Waterworld", None)

    def test_year_in_middle_ignored(self):
        title, year = strip_year_from_title("2001 A Space Odyssey")
        assert title == "2001 A Space Odyssey"
        assert year is None

    def test_trailing_year_with_extra_spaces(self):
        assert strip_year_from_title("Blade Runner  (1982) ") == ("Blade Runner", 1982)


# ---------------------------------------------------------------------------
# _infer_title_from_scanned
# ---------------------------------------------------------------------------


def _make_disc(files):
    return ScannedDisc(folder_name="test", files=files)


def _make_file(name="test.mkv", duration=100, title_tag=None):
    return ScannedFile(name=name, path=f"/tmp/{name}", duration_seconds=duration, title_tag=title_tag)


class TestInferTitleFromScanned:
    def test_uses_longest_file_title_tag(self):
        scanned = [_make_disc([
            _make_file("short.mkv", 300, "Waterworld"),
            _make_file("long.mkv", 8000, "Waterworld"),
            _make_file("extra.mkv", 500, "Waterworld"),
        ])]
        assert infer_title_from_scanned(scanned) == "Waterworld"

    def test_returns_none_when_no_title_tag(self):
        scanned = [_make_disc([
            _make_file("a.mkv", 8000, None),
        ])]
        assert infer_title_from_scanned(scanned) is None

    def test_returns_none_for_empty_title_tag(self):
        scanned = [_make_disc([
            _make_file("a.mkv", 8000, "  "),
        ])]
        assert infer_title_from_scanned(scanned) is None

    def test_returns_none_for_empty_scanned(self):
        assert infer_title_from_scanned([]) is None
        assert infer_title_from_scanned([_make_disc([])]) is None

    def test_strips_trailing_year(self):
        scanned = [_make_disc([
            _make_file("a.mkv", 8000, "Blade Runner (1982)"),
        ])]
        assert infer_title_from_scanned(scanned) == "Blade Runner"

    def test_colon_preserved(self):
        scanned = [_make_disc([
            _make_file("a.mkv", 8000, "Blade Runner: The Final Cut"),
        ])]
        assert infer_title_from_scanned(scanned) == "Blade Runner: The Final Cut"

    def test_strips_trailing_disc_label(self):
        scanned = [_make_disc([
            _make_file("a.mkv", 8000, "SEVEN WORLDS ONE PLANET D1"),
        ])]
        assert infer_title_from_scanned(scanned) == "SEVEN WORLDS ONE PLANET"

    def test_strips_disc_with_word(self):
        scanned = [_make_disc([
            _make_file("a.mkv", 8000, "Planet Earth III Disc 2"),
        ])]
        assert infer_title_from_scanned(scanned) == "Planet Earth III"


# ---------------------------------------------------------------------------
# _parse_volume_label
# ---------------------------------------------------------------------------


class TestParseVolumeLabel:
    def test_frozen_planet_ii_d2(self):
        assert parse_volume_label("FROZEN_PLANET_II_D2") == "Frozen Planet II"

    def test_planet_earth_iii_disc3(self):
        assert parse_volume_label("PLANET_EARTH_III-Disc3") == "Planet Earth III"

    def test_blade_runner_2049(self):
        assert parse_volume_label("BLADE_RUNNER_2049") == "Blade Runner 2049"

    def test_top_gun(self):
        assert parse_volume_label("TOP_GUN") == "Top Gun"

    def test_disc_suffix_word_form(self):
        assert parse_volume_label("OPPENHEIMER_Disc_1") == "Oppenheimer"

    def test_returns_none_for_short(self):
        assert parse_volume_label("A") is None

    def test_returns_none_for_empty(self):
        assert parse_volume_label("") is None

    def test_returns_none_for_none(self):
        assert parse_volume_label(None) is None

    def test_preserves_roman_numerals(self):
        assert parse_volume_label("ROCKY_IV") == "Rocky IV"

    def test_preserves_mixed_roman(self):
        assert parse_volume_label("STAR_WARS_III") == "Star Wars III"

    def test_spaced_dash_disc_suffix(self):
        assert parse_volume_label("The Green Planet - Disc 1") == "The Green Planet"

    def test_spaced_dash_disc_suffix_d2(self):
        assert parse_volume_label("A Perfect Planet - D2") == "A Perfect Planet"

    def test_preserves_hyphenated_title(self):
        assert parse_volume_label("SPIDER-MAN") == "Spider-man"

    def test_preserves_hyphen_with_disc_suffix(self):
        assert parse_volume_label("X-MEN_D1") == "X-men"

    def test_preserves_mid_title_dash(self):
        assert parse_volume_label("ANT-MAN_AND_THE_WASP_Disc_1") == "Ant-man And The Wasp"


# ---------------------------------------------------------------------------
# _detect_disc_format
# ---------------------------------------------------------------------------


class TestDetectDiscFormat:
    def _make_disc_info(self, resolutions):
        from riplex.disc.makemkv import DiscInfo, DiscTitle

        titles = [
            DiscTitle(
                index=i, name=f"title_{i}", duration_seconds=3600,
                chapters=10, size_bytes=1_000_000, filename=f"t{i}.mkv",
                playlist=f"000{i}.mpls", resolution=res,
                video_codec="Mpeg4",
            )
            for i, res in enumerate(resolutions)
        ]
        return DiscInfo(disc_name="TEST", disc_type="Blu-ray disc", titles=titles)

    def test_4k_detected(self):
        info = self._make_disc_info(["3840x2160", "1920x1080"])
        assert detect_disc_format(info) == "Blu-ray 4K"

    def test_bluray_hd(self):
        info = self._make_disc_info(["1920x1080", "1920x1080"])
        assert detect_disc_format(info) == "Blu-ray"

    def test_no_titles(self):
        info = self._make_disc_info([])
        assert detect_disc_format(info) is None

    def test_single_4k_title(self):
        info = self._make_disc_info(["3840x2160"])
        assert detect_disc_format(info) == "Blu-ray 4K"


# ---------------------------------------------------------------------------
# _infer_media_type
# ---------------------------------------------------------------------------


class TestInferMediaType:
    def _make_disc_info(self, title_specs):
        """Create a DiscInfo from a list of (duration_seconds, segment_count) tuples."""
        from riplex.disc.makemkv import DiscInfo, DiscTitle

        titles = [
            DiscTitle(
                index=i, name=f"title_{i}", duration_seconds=dur,
                chapters=10, size_bytes=1_000_000, filename=f"t{i}.mkv",
                playlist=f"000{i}.mpls", resolution="1920x1080",
                video_codec="Mpeg4", segment_count=seg,
            )
            for i, (dur, seg) in enumerate(title_specs)
        ]
        return DiscInfo(disc_name="TEST", disc_type="Blu-ray disc", titles=titles)

    def test_tv_three_episodes_plus_playall(self):
        # 3 x ~50 min episodes + 1 play-all (3 segments)
        info = self._make_disc_info([
            (3022, 1), (3126, 1), (3076, 1), (9226, 3),
        ])
        assert infer_media_type(info) == "tv"

    def test_movie_single_feature(self):
        # Single 2-hour movie
        info = self._make_disc_info([(7200, 1)])
        assert infer_media_type(info) == "movie"

    def test_movie_with_short_extras(self):
        # Movie + short featurettes under 15 min
        info = self._make_disc_info([
            (7200, 1), (600, 1), (480, 1), (300, 1),
        ])
        assert infer_media_type(info) == "movie"

    def test_auto_for_ambiguous(self):
        # Movie-length title + episode-length titles
        info = self._make_disc_info([
            (5400, 1), (3000, 1), (3000, 1),
        ])
        assert infer_media_type(info) == "auto"

    def test_auto_for_no_titles(self):
        info = self._make_disc_info([])
        assert infer_media_type(info) == "auto"

    def test_tv_two_episodes(self):
        # 2 x ~45 min episodes
        info = self._make_disc_info([(2700, 1), (2700, 1)])
        assert infer_media_type(info) == "tv"


# ---------------------------------------------------------------------------
# _pick_best (interactive TMDb selection)
# ---------------------------------------------------------------------------

from riplex.metadata.provider import MetadataSearchResult
from riplex.metadata.planner import _pick_best, _format_tmdb_option
from riplex.models import SearchRequest
from riplex import ui
import riplex.metadata.planner as _planner_mod


def _result(title, year, media_type="tv", popularity=1.0):
    return MetadataSearchResult(
        source_id=f"{media_type}:{year}",
        title=title,
        year=year,
        media_type=media_type,
        overview="",
        popularity=popularity,
    )


def _set_interactive(monkeypatch, val: bool):
    """Patch is_interactive in both ui and planner modules."""
    monkeypatch.setattr(ui, "is_interactive", lambda: val)
    monkeypatch.setattr(_planner_mod, "is_interactive", lambda: val)


class TestPickBest:
    def test_single_exact_match_no_prompt(self, monkeypatch):
        """Single exact title match returns immediately, no interactive prompt."""
        _set_interactive(monkeypatch, True)
        results = [_result("Dynasties", 2018), _result("American Dynasties", 2019)]
        req = SearchRequest(title="Dynasties")
        assert _pick_best(results, req).year == 2018

    def test_exact_title_and_year_no_prompt(self, monkeypatch):
        """Exact title+year match returns immediately."""
        _set_interactive(monkeypatch, True)
        results = [_result("Dynasties", 2018), _result("Dynasties", 2003)]
        req = SearchRequest(title="Dynasties", year=2018)
        assert _pick_best(results, req).year == 2018

    def test_multiple_exact_matches_interactive_prompts(self, monkeypatch, capsys):
        """Multiple exact title matches trigger an interactive prompt."""
        _set_interactive(monkeypatch, True)
        monkeypatch.setattr("builtins.input", lambda _: "2")
        results = [
            _result("Dynasties", 2018, popularity=5.0),
            _result("Dynasties", 2003, popularity=0.1),
        ]
        req = SearchRequest(title="Dynasties")
        chosen = _pick_best(results, req)
        assert chosen.year == 2003  # user picked #2

    def test_multiple_exact_matches_noninteractive_picks_first(self, monkeypatch):
        """Non-interactive mode picks the first exact match (highest popularity)."""
        _set_interactive(monkeypatch, False)
        results = [
            _result("Dynasties", 2018, popularity=5.0),
            _result("Dynasties", 2003, popularity=0.1),
        ]
        req = SearchRequest(title="Dynasties")
        assert _pick_best(results, req).year == 2018

    def test_no_exact_match_interactive_prompts(self, monkeypatch):
        """No exact match triggers interactive prompt."""
        _set_interactive(monkeypatch, True)
        monkeypatch.setattr("builtins.input", lambda _: "1")
        results = [
            _result("Dynasty Warriors", 2021, "movie"),
            _result("Dynasties", 2018),
        ]
        req = SearchRequest(title="Dynasty")
        chosen = _pick_best(results, req)
        assert chosen.title == "Dynasty Warriors"

    def test_no_exact_match_noninteractive_first_result(self, monkeypatch):
        """Non-interactive with no exact match returns first result."""
        _set_interactive(monkeypatch, False)
        results = [_result("Dynasty Warriors", 2021, "movie")]
        req = SearchRequest(title="Dynasty")
        assert _pick_best(results, req).title == "Dynasty Warriors"


class TestFormatTmdbOption:
    def test_format_with_overview(self):
        r = _result("Dynasties", 2018)
        r.overview = "David Attenborough explores animal family dynamics"
        text = _format_tmdb_option(r)
        assert "Dynasties (2018) [tv]" in text
        assert "David Attenborough" in text

    def test_truncates_long_overview(self):
        r = _result("Test", 2020)
        r.overview = "A" * 100
        text = _format_tmdb_option(r)
        assert "..." in text

    def test_no_year(self):
        r = _result("Unknown", None)
        text = _format_tmdb_option(r)
        assert "(?) [tv]" in text


# ---------------------------------------------------------------------------
# _build_execute_command / _dry_run_banner / _execute_hint
# ---------------------------------------------------------------------------


class TestBuildExecuteCommand:
    def test_basic(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["riplex", "organize", "folder"])
        assert _build_execute_command() == "riplex organize folder --execute"

    def test_quotes_spaces(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["riplex", "organize", "E:\\My Folder\\rip"])
        result = _build_execute_command()
        assert '"E:\\My Folder\\rip"' in result
        assert result.endswith("--execute")

    def test_strips_dry_run(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["riplex", "rip", "--dry-run"])
        result = _build_execute_command()
        assert "--dry-run" not in result
        assert "--execute" in result

    def test_strips_n_flag(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["riplex", "rip", "-n"])
        result = _build_execute_command()
        assert "-n" not in result
        assert "--execute" in result

    def test_no_double_execute(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["riplex", "rip", "--execute"])
        result = _build_execute_command()
        assert result.count("--execute") == 1

    def test_strips_exe_path(self, monkeypatch):
        monkeypatch.setattr("sys.argv", [
            "C:\\Users\\me\\AppData\\Local\\Programs\\Python\\Python314\\Scripts\\riplex.exe",
            "organize", "folder",
        ])
        result = _build_execute_command()
        assert result.startswith("riplex ")
        assert "C:\\Users" not in result


class TestDryRunBanner:
    def test_move_files(self):
        assert _dry_run_banner("move files") == "--- DRY RUN (pass --execute to move files) ---"

    def test_rip(self):
        assert _dry_run_banner("rip") == "--- DRY RUN (pass --execute to rip) ---"


class TestExecuteHint:
    def test_organize(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["riplex", "organize", "folder"])
        hint = _execute_hint("organize")
        assert "Re-run with --execute to apply these changes:" in hint
        assert "riplex organize folder --execute" in hint

    def test_rip(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["riplex", "rip"])
        hint = _execute_hint("rip")
        assert "Re-run with --execute to rip:" in hint
        assert "riplex rip --execute" in hint


# ---------------------------------------------------------------------------
# Orchestrate helpers: _disc_content_summary / _find_ripped_discs
# ---------------------------------------------------------------------------


def _make_planned_disc(number, fmt="Blu-ray 4K", episodes=None, extras=None):
    return PlannedDisc(
        number=number,
        disc_format=fmt,
        episodes=episodes or [],
        extras=extras or [],
    )


def _ep(title, season=1, episode=1):
    return PlannedEpisode(
        season_number=season, episode_number=episode,
        title=title, runtime="50m", runtime_seconds=3000,
    )


class TestDiscContentSummary:
    def test_episodes_only(self):
        disc = _make_planned_disc(1, episodes=[_ep("Ep 1"), _ep("Ep 2", episode=2)])
        assert disc_content_summary(disc) == "Ep 1, Ep 2"

    def test_episodes_and_extras(self):
        disc = _make_planned_disc(1,
            episodes=[_ep("Ep 1")],
            extras=[PlannedExtra(title="Behind the Scenes")],
        )
        result = disc_content_summary(disc)
        assert "Ep 1" in result
        assert "Behind the Scenes" in result

    def test_truncation(self):
        disc = _make_planned_disc(1, episodes=[
            _ep(f"Episode {i}", episode=i)
            for i in range(1, 7)
        ])
        summary = disc_content_summary(disc)
        assert "..." in summary
        assert "6 items" in summary

    def test_empty_disc(self):
        disc = _make_planned_disc(1)
        assert disc_content_summary(disc) == "(no content listed)"


class TestFindRippedDiscs:
    def test_empty_dir(self, tmp_path):
        assert find_ripped_discs(tmp_path) == set()

    def test_nonexistent_dir(self, tmp_path):
        assert find_ripped_discs(tmp_path / "nope") == set()

    def test_finds_manifests(self, tmp_path):
        d1 = tmp_path / "Disc 1"
        d1.mkdir()
        (d1 / "_rip_manifest.json").write_text("{}")
        d3 = tmp_path / "Disc 3"
        d3.mkdir()
        (d3 / "_rip_manifest.json").write_text("{}")
        # Disc 2 exists but no manifest
        d2 = tmp_path / "Disc 2"
        d2.mkdir()
        assert find_ripped_discs(tmp_path) == {1, 3}

    def test_ignores_non_disc_folders(self, tmp_path):
        other = tmp_path / "Extras"
        other.mkdir()
        (other / "_rip_manifest.json").write_text("{}")
        assert find_ripped_discs(tmp_path) == set()


class TestBuildScannedFromManifests:
    def _write_manifest(self, disc_dir, manifest_data):
        disc_dir.mkdir(parents=True, exist_ok=True)
        (disc_dir / "_rip_manifest.json").write_text(
            json.dumps(manifest_data), encoding="utf-8"
        )

    def test_builds_scanned_files_from_manifest(self, tmp_path):
        manifest = {
            "title": "Dunkirk",
            "year": 2017,
            "type": "movie",
            "disc_number": 1,
            "files": [
                {
                    "filename": "title00.mkv",
                    "title_index": 0,
                    "duration": 6360,
                    "resolution": "3840x2160",
                    "size_bytes": 50000000000,
                    "classification": "movie",
                    "stream_count": 5,
                    "stream_fingerprint": "hevc:3840x2160|truehd:eng:8ch|ac3:eng:6ch|sub:eng|sub:spa",
                    "chapter_count": 12,
                    "chapter_durations": [300, 400, 500, 600, 500, 400, 300, 500, 600, 400, 500, 360],
                },
            ],
        }
        disc1 = tmp_path / "Disc 1"
        self._write_manifest(disc1, manifest)

        result = build_scanned_from_manifests(tmp_path)
        assert len(result) == 1
        assert result[0].folder_name == "Disc 1"
        assert len(result[0].files) == 1

        f = result[0].files[0]
        assert f.name == "title00.mkv"
        assert f.duration_seconds == 6360
        assert f.size_bytes == 50000000000
        assert f.stream_count == 5
        assert "hevc:3840x2160" in f.stream_fingerprint
        assert f.chapter_count == 12
        assert len(f.chapter_durations) == 12
        assert f.max_width == 3840
        assert f.max_height == 2160

    def test_multiple_discs(self, tmp_path):
        for i in range(1, 4):
            manifest = {
                "title": "Planet Earth III",
                "disc_number": i,
                "files": [
                    {"filename": f"title0{j}.mkv", "duration": 3000 + j * 100,
                     "resolution": "1920x1080", "size_bytes": 1000000}
                    for j in range(3)
                ],
            }
            self._write_manifest(tmp_path / f"Disc {i}", manifest)

        result = build_scanned_from_manifests(tmp_path)
        assert len(result) == 3
        assert sum(len(d.files) for d in result) == 9

    def test_empty_dir_returns_empty(self, tmp_path):
        assert build_scanned_from_manifests(tmp_path) == []

    def test_skips_files_without_filename(self, tmp_path):
        manifest = {
            "title": "Test",
            "files": [
                {"filename": "", "duration": 100},
                {"filename": "real.mkv", "duration": 200, "resolution": "1920x1080"},
            ],
        }
        self._write_manifest(tmp_path / "Disc 1", manifest)
        result = build_scanned_from_manifests(tmp_path)
        assert len(result[0].files) == 1
        assert result[0].files[0].name == "real.mkv"
