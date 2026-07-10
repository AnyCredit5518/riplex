"""Generate GUI test-scenario fixtures from archived riplex rips.

Many archived rips under the MakeMKV ``_archive`` folder carry everything a
GUI integration test needs to replay a disc-set offline:

* ``_riplex/riplex-rip.snapshot.json`` — disc titles, the TMDb match, and the
  dvdcompare release breakdown (episodes/extras, or just counts on older rips).
* ``Disc N/_rip_manifest.json`` — richer per-title stream info plus the *real*
  dvdcompare release name, disc format, and volume label.

This script walks the archive, normalizes each title folder into a single
committed scenario JSON (schema shared with hand-authored fixtures), and writes
it under ``tests/fixtures/gui/scenarios/``. The committed JSON is what tests
load — the archive itself is never needed at test time, so CI stays hermetic.

Missing pieces (TMDb id, per-episode lists on older snapshots, TMDb season
structure) are synthesized deterministically and listed under a ``synthesized``
key so consumers know which blocks are inferred rather than observed.

Usage::

    python scripts/gen_gui_fixtures.py --list
    python scripts/gen_gui_fixtures.py                     # generate all
    python scripts/gen_gui_fixtures.py --only "Chernobyl (2019)"
    python scripts/gen_gui_fixtures.py --limit 5 --archive "/path/to/_archive"

The archive root defaults to the configured archive folder (``archive_root``,
or ``<rip_output>/_archive``); pass ``--archive`` to point elsewhere. Run it
whenever you want to refresh or add real-world scenarios; commit the resulting
JSON files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "gui" / "scenarios"

SCHEMA_VERSION = 1

_YEAR_RE = re.compile(r"\((\d{4})\)")
_DISC_RE = re.compile(r"Disc\s+(\d+)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(folder_name: str) -> str:
    """'Chernobyl (2019)' -> 'chernobyl-2019'; 'Blade Runner (Blu-ray 4k) (1982)'
    -> 'blade-runner-blu-ray-4k-1982'."""
    text = folder_name.lower()
    text = re.sub(r"[()]", " ", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def synth_tmdb_id(media_type: str, title: str, year: int | None) -> str:
    """Deterministic synthetic TMDb id so scenarios are stable across runs."""
    digest = hashlib.sha1(f"{media_type}:{title}:{year}".encode("utf-8")).hexdigest()
    numeric = int(digest[:6], 16)
    return f"{media_type}:{numeric}"


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - best effort over messy archive
        print(f"  ! failed to read {path.name}: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _disc_from_manifest(manifest: dict, disc_number: int) -> dict:
    """Build a scenario ``discs[]`` entry from a per-disc rip manifest."""
    titles = []
    for f in manifest.get("files", []):
        titles.append(
            {
                "index": f.get("title_index", len(titles)),
                "name": "",
                "duration_seconds": f.get("duration", 0),
                "chapters": f.get("chapter_count", 0),
                "size_bytes": f.get("size_bytes", 0),
                "filename": f.get("filename", ""),
                "playlist": "",
                "resolution": f.get("resolution", ""),
                "video_codec": "",
                "audio_tracks": [],
                "subtitle_tracks": [],
                "stream_count": f.get("stream_count", 0),
                "segment_count": 1,
                "segment_map": "",
                "classification": f.get("classification", ""),
            }
        )
    return {
        "disc_number": manifest.get("disc_number", disc_number),
        "disc_label": manifest.get("disc_label", ""),
        "disc_name": manifest.get("disc_label", "") or f"Disc {disc_number}",
        "disc_type": manifest.get("format", "Blu-ray disc"),
        "titles": titles,
    }


def _disc_from_snapshot(snap_data: dict) -> dict:
    """Build a single ``discs[]`` entry from the snapshot's title list."""
    titles = []
    for t in snap_data.get("titles", []):
        titles.append(
            {
                "index": t.get("index", len(titles)),
                "name": t.get("name", ""),
                "duration_seconds": t.get("duration_seconds", 0),
                "chapters": t.get("chapters", 0) or 0,
                "size_bytes": t.get("size_bytes", 0),
                "filename": t.get("filename", ""),
                "playlist": t.get("playlist", ""),
                "resolution": t.get("resolution", ""),
                "video_codec": t.get("video_codec", ""),
                "audio_tracks": list(t.get("audio_tracks", []) or []),
                "subtitle_tracks": list(t.get("subtitle_tracks", []) or []),
                "stream_count": t.get("stream_count", 0),
                "segment_count": t.get("segment_count", 1) or 1,
                "segment_map": t.get("segment_map", ""),
                "classification": t.get("classification", ""),
            }
        )
    return {
        "disc_number": 1,
        "disc_label": snap_data.get("disc_name", ""),
        "disc_name": snap_data.get("disc_name", ""),
        "disc_type": "Blu-ray disc",
        "titles": titles,
    }


def _dvdcompare_block(snap_dvd: dict, synthesized: list[str]) -> dict:
    """Normalize the snapshot dvdcompare block; synthesize episodes/extras
    from counts when the snapshot only recorded totals (older rips)."""
    out_discs = []
    for d in snap_dvd.get("discs", []):
        episodes = d.get("episodes")
        extras = d.get("extras")
        if episodes is None:
            episodes = [
                {"season_number": 1, "episode_number": i + 1,
                 "title": f"Episode {i + 1}", "runtime_seconds": 0}
                for i in range(d.get("episode_count", 0))
            ]
            if episodes:
                synthesized.append(f"dvdcompare.disc{d.get('number')}.episodes")
        else:
            episodes = [
                {"season_number": e.get("season_number", 1),
                 "episode_number": e.get("episode_number", i + 1),
                 "title": e.get("title", f"Episode {i + 1}"),
                 "runtime_seconds": e.get("runtime_seconds", 0)}
                for i, e in enumerate(episodes)
            ]
        if extras is None:
            extras = [
                {"title": f"Extra {i + 1}", "runtime_seconds": 0, "feature_type": ""}
                for i in range(d.get("extra_count", 0))
            ]
            if extras:
                synthesized.append(f"dvdcompare.disc{d.get('number')}.extras")
        else:
            extras = [
                {"title": x.get("title", f"Extra {i + 1}"),
                 "runtime_seconds": x.get("runtime_seconds", 0),
                 "feature_type": x.get("feature_type", "")}
                for i, x in enumerate(extras)
            ]
        out_discs.append(
            {
                "number": d.get("number", len(out_discs) + 1),
                "disc_format": d.get("format", ""),
                "is_film": d.get("is_film", False),
                "episodes": episodes,
                "extras": extras,
                "title": d.get("title", ""),
            }
        )
    return {"release": snap_dvd.get("release", ""), "discs": out_discs}


def _synth_seasons(dvd_block: dict, synthesized: list[str]) -> list[dict]:
    """Build a minimal TMDb ShowDetail season list from dvdcompare episodes."""
    episodes: list[dict] = []
    for d in dvd_block.get("discs", []):
        for e in d.get("episodes", []):
            episodes.append(e)
    if not episodes:
        return []
    synthesized.append("tmdb.seasons")
    for i, e in enumerate(episodes):
        e.setdefault("season_number", 1)
        e["episode_number"] = i + 1
    return [{"season_number": 1, "name": "Season 1", "episodes": episodes}]


def build_scenario(title_dir: Path) -> dict | None:
    """Assemble one normalized scenario dict from an archived title folder."""
    snap_path = title_dir / "_riplex" / "riplex-rip.snapshot.json"
    snapshot = _read_json(snap_path) if snap_path.exists() else None
    if not snapshot or snapshot.get("type") != "rip":
        print(f"  - {title_dir.name}: no usable rip snapshot, skipping", file=sys.stderr)
        return None

    data = snapshot.get("data", {})
    tmdb = data.get("tmdb", {})
    media_type = tmdb.get("type", "movie")
    title = tmdb.get("canonical_title", "")
    year = tmdb.get("year")
    synthesized: list[str] = []

    # Prefer per-disc rip manifests (richer + real release/format) when present.
    manifests: list[tuple[int, dict]] = []
    for disc_dir in sorted(title_dir.glob("Disc *")):
        m = _DISC_RE.search(disc_dir.name)
        if not m:
            continue
        mf = disc_dir / "_rip_manifest.json"
        if mf.exists():
            parsed = _read_json(mf)
            if parsed:
                manifests.append((int(m.group(1)), parsed))

    if manifests:
        discs = [_disc_from_manifest(mf, n) for n, mf in manifests]
        release_name = next((mf.get("release", "") for _, mf in manifests if mf.get("release")), "")
    else:
        discs = [_disc_from_snapshot(data)]
        release_name = ""

    dvd_block = _dvdcompare_block(data.get("dvdcompare", {}), synthesized)
    if release_name and not dvd_block.get("release"):
        dvd_block["release"] = release_name

    # Prefer a title-qualified slug when the folder name has no year of its
    # own (e.g. per-season folders like "Season 01") so scenarios stay
    # meaningful and don't collide across seasons of the same show.
    if not _YEAR_RE.search(title_dir.name) and title:
        slug = slugify(f"{title} {title_dir.name}")
    else:
        slug = slugify(title_dir.name)

    source_id = synth_tmdb_id(media_type, title, year)
    synthesized.append("tmdb.source_id")

    tmdb_block: dict = {
        "source_id": source_id,
        "title": title,
        "year": year,
        "media_type": media_type,
        "overview": "",
        "popularity": 1.0,
        "movie_runtime_seconds": tmdb.get("movie_runtime"),
    }
    if media_type == "tv":
        tmdb_block["seasons"] = _synth_seasons(dvd_block, synthesized)

    scenario = {
        "schema_version": SCHEMA_VERSION,
        "scenario": slug,
        "source": f"archive:{title_dir.name}",
        "workflow": "orchestrate",
        "media_type": media_type,
        "title": title,
        "year": year,
        "tmdb": tmdb_block,
        "dvdcompare": dvd_block,
        "discs": discs,
        "selected_titles": data.get("selected_titles", []),
        "ripped_titles": data.get("ripped_titles", []),
        "synthesized": sorted(set(synthesized)),
    }
    scenario["category"] = _classify_scenario(scenario)
    return scenario


def _classify_scenario(scenario: dict) -> str:
    """Media-type category for a scenario, reusing the loader's classifier so
    generator and tests agree. Falls back to a coarse guess if the test
    package isn't importable (e.g. running the script in isolation)."""
    try:
        # Running ``python scripts/gen_gui_fixtures.py`` puts ``scripts/`` on
        # sys.path, not the repo root — add the root so ``tests`` imports.
        repo_root = str(Path(__file__).resolve().parent.parent)
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
        from tests.support.fixtures import classify

        return classify(scenario)
    except Exception:
        return "movie" if scenario.get("media_type") != "tv" else "tv_miniseries"



# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def iter_title_dirs(archive: Path):
    for child in sorted(archive.iterdir()):
        if child.is_dir() and not child.name.startswith("_"):
            yield child


def _default_archive() -> Path | None:
    """Resolve the archive root from riplex config, or None if unconfigured."""
    try:
        from riplex.config import get_archive_root, get_rip_output

        root = get_archive_root()
        if root:
            return Path(root)
        rip = get_rip_output()
        if rip:
            return Path(rip) / "_archive"
    except Exception:
        pass
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--archive", type=Path, default=None,
                        help="Archive root (default: configured archive_root or "
                             "<rip_output>/_archive).")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help="Output dir (default: tests/fixtures/gui/scenarios).")
    parser.add_argument("--only", action="append", default=None,
                        help="Only process this archived folder name (repeatable).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process at most N folders.")
    parser.add_argument("--list", action="store_true",
                        help="List archived folders and exit.")
    args = parser.parse_args(argv)

    archive = args.archive or _default_archive()
    if archive is None:
        print("No archive path. Pass --archive or configure archive_root/rip_output.",
              file=sys.stderr)
        return 2
    args.archive = archive

    if not args.archive.exists():
        print(f"Archive not found: {args.archive}", file=sys.stderr)
        return 2

    if args.list:
        for d in iter_title_dirs(args.archive):
            has_snap = (d / "_riplex" / "riplex-rip.snapshot.json").exists()
            print(f"{'*' if has_snap else ' '} {d.name}")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    written = 0
    processed = 0
    for title_dir in iter_title_dirs(args.archive):
        if args.only and title_dir.name not in args.only:
            continue
        if args.limit is not None and processed >= args.limit:
            break
        processed += 1
        scenario = build_scenario(title_dir)
        if scenario is None:
            continue
        out_path = args.out / f"{scenario['scenario']}.json"
        out_path.write_text(
            json.dumps(scenario, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"  + {out_path.relative_to(args.out.parent.parent.parent)}"
              f"  ({len(scenario['discs'])} disc(s), media={scenario['media_type']})")
        written += 1

    print(f"\nWrote {written} scenario fixture(s) to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
