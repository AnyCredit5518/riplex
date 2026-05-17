"""Auto-discovered tests against developer-captured disc fixtures.

Every subfolder under ``_captures/<slug>/Disc N/`` that has the three
snapshot files written by ``scripts/capture_fixture.py`` is automatically
turned into one or more parametrized test cases here. Adding a new
capture under ``_captures/`` gives us a new regression case for free.

Two layers of coverage:

1. ``test_capture_pipeline_smoke``
   Runs for every capture. Asserts the pipeline loads the snapshots,
   converts the dvdcompare release into PlannedDiscs, builds entries,
   and classifies every MakeMKV title without exploding. Assertions
   are generic so movies and TV both pass without per-fixture tuning.

2. ``test_capture_classifications_match_expected``
   Runs only for captures that have an ``expected.json`` next to the
   three snapshot files. Asserts the per-title classifications exactly
   match the baseline. To regenerate baselines after an intentional
   change, run::

       $env:RIPLEX_UPDATE_CAPTURE_EXPECTED=1; py -m pytest tests/test_captures.py

If ``_captures/`` is missing or empty the tests are skipped, so CI and
fresh clones don't fail.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from riplex.disc.analysis import build_dvd_entries, classify_title
from riplex.disc.provider import _convert_release


REPO_ROOT = Path(__file__).resolve().parent.parent
CAPTURES_ROOT = REPO_ROOT / "_captures"

_REQUIRED_FILES = (
    "riplex-rip.snapshot.json",
    "tmdb.snapshot.json",
    "dvdcompare.snapshot.json",
)
_EXPECTED_FILE = "expected.json"
_UPDATE_ENV = "RIPLEX_UPDATE_CAPTURE_EXPECTED"


def _discover_captures() -> list[Path]:
    if not CAPTURES_ROOT.is_dir():
        return []
    discovered: list[Path] = []
    for slug_dir in sorted(CAPTURES_ROOT.iterdir()):
        if not slug_dir.is_dir():
            continue
        for disc_dir in sorted(slug_dir.iterdir()):
            if not disc_dir.is_dir():
                continue
            if all((disc_dir / name).is_file() for name in _REQUIRED_FILES):
                discovered.append(disc_dir)
    return discovered


def _capture_id(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


def _ns(obj):
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: _ns(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [_ns(x) for x in obj]
    return obj


def _load_snapshots(capture_dir: Path) -> tuple[dict, dict, dict]:
    rip = json.loads((capture_dir / "riplex-rip.snapshot.json").read_text(encoding="utf-8"))
    tmdb = json.loads((capture_dir / "tmdb.snapshot.json").read_text(encoding="utf-8"))
    dvdc = json.loads((capture_dir / "dvdcompare.snapshot.json").read_text(encoding="utf-8"))
    return rip, tmdb, dvdc


def _run_classification(
    rip: dict,
    tmdb: dict,
    dvdc: dict,
    release_index: int = 0,
) -> tuple[dict[int, str], str]:
    """Run the rip-time classification pipeline.

    Returns (classifications_by_title_index, media_type).
    """
    picked = tmdb.get("picked") or {}
    media_type = picked.get("media_type") or "movie"
    is_movie = media_type == "movie"
    movie_runtime = picked.get("runtime_seconds") or 0

    releases = (dvdc.get("film") or {}).get("releases") or []
    discs = _convert_release(_ns(releases[release_index]))
    dvd_entries, total_ep_runtime, ep_count = build_dvd_entries(discs)

    titles_raw = rip.get("data", {}).get("titles") or []
    titles = [
        SimpleNamespace(
            index=t["index"],
            duration_seconds=t.get("duration_seconds", 0),
            resolution=t.get("resolution", ""),
            size_bytes=t.get("size_bytes", 0),
            chapter_count=t.get("chapters", 0),
            name=f"t{t['index']:02d}.mkv",
        )
        for t in titles_raw
    ]

    classifications: dict[int, str] = {}
    for t in titles:
        classifications[t.index] = classify_title(
            t,
            titles,
            dvd_entries,
            is_movie=is_movie,
            movie_runtime=movie_runtime,
            total_episode_runtime=total_ep_runtime,
            episode_count=ep_count,
        )
    return classifications, media_type


CAPTURES = _discover_captures()
CAPTURES_WITH_EXPECTED = [p for p in CAPTURES if (p / _EXPECTED_FILE).is_file()]


# ---------------------------------------------------------------------------
# Smoke layer: every capture runs through the pipeline
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not CAPTURES,
    reason="No developer captures present under _captures/",
)
@pytest.mark.parametrize(
    "capture_dir",
    CAPTURES,
    ids=[_capture_id(p) for p in CAPTURES],
)
def test_capture_pipeline_smoke(capture_dir: Path) -> None:
    rip, tmdb, dvdc = _load_snapshots(capture_dir)

    titles_raw = rip.get("data", {}).get("titles") or []
    assert titles_raw, f"{capture_dir}: rip snapshot has no titles"

    picked = tmdb.get("picked")
    assert picked, f"{capture_dir}: tmdb snapshot has no picked result"
    assert picked.get("title"), f"{capture_dir}: tmdb picked missing title"
    media_type = picked.get("media_type")
    assert media_type in {"movie", "tv"}, (
        f"{capture_dir}: unexpected media_type {media_type!r}"
    )

    releases = (dvdc.get("film") or {}).get("releases") or []
    assert releases, f"{capture_dir}: dvdcompare snapshot has no releases"

    discs = _convert_release(_ns(releases[0]))
    assert discs, f"{capture_dir}: dvdcompare release[0] produced no PlannedDiscs"

    classifications, _ = _run_classification(rip, tmdb, dvdc)
    assert len(classifications) == len(titles_raw)
    for idx, cls in classifications.items():
        assert isinstance(cls, str) and cls, (
            f"{capture_dir}: title index {idx} classify_title returned {cls!r}"
        )


# ---------------------------------------------------------------------------
# Expected-baseline layer: opt-in per capture via expected.json
# ---------------------------------------------------------------------------


def _params_for_expected():
    """Parametrize the expected-baseline test.

    In update mode, parametrize over every capture so we regenerate
    baselines for all of them. In assertion mode, parametrize only
    over captures that already have an expected.json.
    """
    if os.environ.get(_UPDATE_ENV):
        return CAPTURES
    return CAPTURES_WITH_EXPECTED


_EXPECTED_PARAMS = _params_for_expected()


@pytest.mark.skipif(
    not _EXPECTED_PARAMS,
    reason=(
        "No captures with expected.json baselines. "
        f"Set {_UPDATE_ENV}=1 to generate them."
    ),
)
@pytest.mark.parametrize(
    "capture_dir",
    _EXPECTED_PARAMS,
    ids=[_capture_id(p) for p in _EXPECTED_PARAMS],
)
def test_capture_classifications_match_expected(capture_dir: Path) -> None:
    rip, tmdb, dvdc = _load_snapshots(capture_dir)
    expected_path = capture_dir / _EXPECTED_FILE

    release_index = 0
    if expected_path.is_file() and not os.environ.get(_UPDATE_ENV):
        existing = json.loads(expected_path.read_text(encoding="utf-8"))
        release_index = existing.get("release_index", 0)

    classifications, media_type = _run_classification(
        rip, tmdb, dvdc, release_index=release_index,
    )
    classifications_str = {str(k): v for k, v in sorted(classifications.items())}

    baseline = {
        "release_index": release_index,
        "media_type": media_type,
        "classifications": classifications_str,
    }

    if os.environ.get(_UPDATE_ENV):
        expected_path.write_text(
            json.dumps(baseline, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        pytest.skip(f"Updated baseline at {expected_path}")
        return

    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    assert baseline["media_type"] == expected.get("media_type"), (
        f"{capture_dir}: media_type drift "
        f"(got {baseline['media_type']!r}, expected {expected.get('media_type')!r})"
    )
    assert baseline["classifications"] == expected.get("classifications"), (
        f"{capture_dir}: classifications drift\n"
        f"  got:      {baseline['classifications']}\n"
        f"  expected: {expected.get('classifications')}"
    )
