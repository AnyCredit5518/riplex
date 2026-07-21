"""Headless screen-screenshot launcher for release notes / docs.

Renders any riplex-ui screen, seeded with fixture data, in Flet's *web* mode and
captures a PNG with headless Playwright chromium -- no window ever appears.

How it works:
  * ``--_serve`` (internal) exports the Flet app as an ASGI app and serves it
    with uvicorn on a port, with ``app.state`` seeded for one screen.
  * The default (orchestrator) mode spawns that server as a subprocess, waits
    for the port, screenshots ``http://127.0.0.1:<port>`` with Playwright, and
    tears the server down.

Usage:
    python scripts/gui_screenshot.py --list
    python scripts/gui_screenshot.py --screen organize_preview --out screenshots
    python scripts/gui_screenshot.py --all --out screenshots

Requires the dev + gui extras plus ``playwright`` and a chromium download
(``python -m playwright install chromium``).
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Per-screen state overrides — the fixtures don't carry multi-work / multi-
# season / built-plan state, so synthesize just enough for a faithful shot.
# ---------------------------------------------------------------------------

def _override_update(app, scenario, tmp) -> None:
    app.state["update_info"] = {
        "tag": "v1.0.2",
        "name": "v1.0.2",
        "url": "https://github.com/AnyCredit5518/riplex/releases/tag/v1.0.2",
        "releases": [
            {
                "tag": "v1.0.2",
                "body": (
                    "### Fixed\n\n"
                    "- **Episodes no longer land in `Other/`.** Organize now honors the "
                    "rip-time `SxxEyy` classification recorded in each disc's manifest, so "
                    "an episode whose title has a parenthetical (*Shawn and Gus in Drag "
                    "(Racing)*) or that dvdcompare files under extras (*Dual Spires*) "
                    "routes to its season folder.\n\n"
                    "### Added\n\n"
                    "- **Durations on the organize preview** highlight a mismatched match "
                    "before you execute."
                ),
            },
            {
                "tag": "v1.0.1",
                "body": (
                    "### Fixed\n\n"
                    "- **Out-of-order episode matching.** Episodes are sorted by their "
                    "canonical `SxxEyy` number before positional alignment, so a disc "
                    "whose titles are in broadcast order maps correctly."
                ),
            },
        ],
    }


def _override_season_select(app, scenario, tmp) -> None:
    """Give the show a full 8-season run so the season picker renders."""
    from riplex.metadata.provider import EpisodeMetadata, SeasonMetadata, ShowDetail

    seasons = []
    for sn in range(1, 9):
        eps = [
            EpisodeMetadata(season_number=sn, episode_number=en,
                            title=f"Episode {en}", runtime_seconds=2580)
            for en in range(1, 17)
        ]
        seasons.append(SeasonMetadata(season_number=sn, episodes=eps, name=f"Season {sn}"))
    app.state["show_detail"] = ShowDetail(
        source_id="tv:1447", title="Psych", year=2006, seasons=seasons,
    )
    # Force the picker to render (not auto-skip).
    app.state["season_number"] = None


def _override_organize_preview(app, scenario, tmp) -> None:
    """Seed a fully-built Psych S5 organize plan (episodes + an extra)."""
    from riplex.organizer import OrganizePlan, FileMove
    from riplex.models import PlannedShow, PlannedSeason, PlannedEpisode

    titles = {
        1: ("Romeo and Juliet and Juliet", 2894, 2898),
        2: ("Feet Don't Kill Me Now", 2577, 2580),
        3: ("Not Even Close... Encounters", 2577, 2580),
        4: ("Chivalry Is Not Dead... But Someone Is", 2581, 2585),
        5: ("Shawn and Gus in Drag (Racket)", 2585, 2590),
        6: ("Viagra Falls", 2499, 2520),
        7: ("Ferry Tale", 2530, 2540),
        8: ("Shawn 2.0", 2578, 2585),
    }
    base = Path("E:/Media/TV Shows/Psych (2006)")
    moves = []
    for ep, (name, file_dur, tgt) in titles.items():
        disc = 1 if ep <= 4 else 2
        idx = (ep - 1) % 4
        delta = abs(file_dur - tgt)
        conf = "high" if delta <= 30 else ("medium" if delta <= 120 else "low")
        moves.append(FileMove(
            source=str(base.parent / f"_MakeMKV/Psych/Disc {disc}/C{idx}_t0{idx}.mkv"),
            destination=str(base / "Season 05" / f"Psych (2006) - s05e{ep:02d} - {name}.mkv"),
            label=f"Disc {disc}: {name}",
            confidence=conf,
            delta_seconds=delta,
            file_duration_seconds=file_dur,
            target_runtime_seconds=tgt,
        ))
    plan = OrganizePlan(
        moves=moves,
        splits=[],
        unmatched=[],
        missing=["Disc 1: No Comment: Behind the Scenes (featurette)"],
    )
    planned = PlannedShow(
        canonical_title="Psych", year=2006,
        seasons=[PlannedSeason(
            season_number=5,
            episodes=[PlannedEpisode(season_number=5, episode_number=ep,
                                     title=name, runtime="43m")
                      for ep, (name, _, _) in titles.items()],
        )],
    )
    app.state["_organize_plan"] = (plan, planned)


_OVERRIDES = {
    "update": _override_update,
    "season_select": _override_season_select,
    "organize_preview": _override_organize_preview,
}

# Which fixture scenario backs each screen (default: a Psych season).
_SCENARIO = {
    "selection": "psych-season-01",
    "season_select": "psych-season-01",
    "disc_overview": "psych-season-01",
    "organize_preview": "psych-season-01",
    "update": "psych-season-01",
    "metadata": "psych-season-01",
    "release": "psych-season-01",
}

SHOTS = ["selection", "season_select", "disc_overview", "organize_preview", "update"]


# ---------------------------------------------------------------------------
# Server (internal --_serve mode)
# ---------------------------------------------------------------------------

def _build_screen(page, scenario_name: str, screen: str) -> None:
    from riplex_app.main import RiplexApp
    from tests.support.fixtures import load_scenario
    from tests.support.seed import populate_state

    app = RiplexApp(page)
    scenario = load_scenario(scenario_name)
    tmp = Path(tempfile.mkdtemp())
    populate_state(app.state, scenario, tmp)
    override = _OVERRIDES.get(screen)
    if override:
        override(app, scenario, tmp)
    app.navigate(screen)
    # Drop the floating bug-report button for a clean marketing shot.
    page.floating_action_button = None
    try:
        page.update()
    except Exception:
        pass


def _serve(scenario_name: str, screen: str, port: int) -> None:
    import flet as ft
    import uvicorn

    def target(page):
        _build_screen(page, scenario_name, screen)

    asgi_app = ft.run(target, export_asgi_app=True)
    uvicorn.Server(
        uvicorn.Config(asgi_app, host="127.0.0.1", port=port, log_level="error")
    ).run()


# ---------------------------------------------------------------------------
# Orchestrator (default mode)
# ---------------------------------------------------------------------------

def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_port(port: int, timeout: float = 40.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def _capture(scenario_name: str, screen: str, out_path: Path, settle_ms: int) -> bool:
    from playwright.sync_api import sync_playwright

    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, __file__, "--_serve",
         "--scenario", scenario_name, "--screen", screen, "--port", str(port)],
    )
    try:
        if not _wait_port(port):
            print(f"  ! server for {screen} did not start")
            return False
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(
                viewport={"width": 900, "height": 650}, device_scale_factor=2,
            )
            page.goto(f"http://127.0.0.1:{port}", wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(settle_ms)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out_path))
            browser.close()
        print(f"  + {screen} -> {out_path}")
        return True
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--_serve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--scenario", default=None)
    parser.add_argument("--screen", default=None)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--out", default="screenshots", help="output directory")
    parser.add_argument("--all", action="store_true", help="capture every mapped screen")
    parser.add_argument("--settle-ms", type=int, default=4500,
                        help="ms to wait for Flutter to paint before capturing")
    parser.add_argument("--list", action="store_true", help="list mapped screens")
    args = parser.parse_args()

    if args.list:
        for s in SHOTS:
            print(f"{s:20} <- {_SCENARIO.get(s, 'psych-season-01')}")
        return 0

    if getattr(args, "_serve"):
        _serve(args.scenario, args.screen, args.port)
        return 0

    out_dir = Path(args.out)
    if args.all:
        screens = SHOTS
    elif args.screen:
        screens = [args.screen]
    else:
        parser.error("specify --screen NAME, --all, or --list")

    ok = True
    for screen in screens:
        scenario_name = args.scenario or _SCENARIO.get(screen, "psych-season-01")
        print(f"capturing {screen} ({scenario_name})...")
        if not _capture(scenario_name, screen, out_dir / f"{screen}.png", args.settle_ms):
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
