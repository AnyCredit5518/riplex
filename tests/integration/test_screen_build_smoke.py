"""Screen-build smoke matrix — the broad regression net.

Builds *every* screen with a realistic, fully-populated ``app.state`` and
asserts each ``build()`` renders without raising or surfacing a crash dialog —
including the screens that never appear on the auto-driven orchestrate path
(done, orchestrate_done, organize_done, update, …).

This runs against one representative scenario per media-type category (plus a
no-dvdcompare edge case). Every *individual* fixture is separately driven
through the core screens by ``test_flow_media_types.py``, so between the two the
whole fixture corpus is exercised without an N×M explosion as fixtures grow.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from riplex.disc.makemkv import RipResult
from riplex.normalize import sanitize_filename
from tests.support import provider_mocks
from tests.support.fixtures import ALL_CATEGORIES, load_scenario, scenarios_by_category


def _smoke_scenarios() -> list[str]:
    """One representative per category, plus the first no-dvdcompare movie."""
    reps: list[str] = []
    for category in ALL_CATEGORIES:
        names = scenarios_by_category(category)
        if names:
            reps.append(names[0])
    # A movie whose snapshot recorded no dvdcompare structure exercises the
    # empty-discs rendering paths (disc_overview / selection).
    for name in scenarios_by_category("movie"):
        if not load_scenario(name).planned_discs():
            if name not in reps:
                reps.append(name)
            break
    return reps


SMOKE_SCENARIOS = _smoke_scenarios()

# Every screen registered on the app. Ordering doesn't matter — each is
# navigated to independently from a fully-populated state.
ALL_SCREENS = [
    "welcome",
    "disc_detection",
    "metadata",
    "season_select",
    "release",
    "selection",
    "progress",
    "done",
    "folder_picker",
    "organize_preview",
    "organize_done",
    "disc_overview",
    "disc_swap",
    "orchestrate_done",
    "update",
]


def _populate_state(driver, scenario, tmp_path: Path) -> None:
    """Fill ``app.state`` with realistic values for every screen to read."""
    folder = sanitize_filename(f"{scenario.title} ({scenario.year})")
    out_dir = tmp_path / folder / "Disc 1"
    out_dir.mkdir(parents=True, exist_ok=True)

    discs = scenario.planned_discs()
    disc_info = scenario.disc_info()
    match = scenario.search_result()
    selected = scenario.selected_titles or [t.index for t in disc_info.titles[:1]]
    rip_results = [
        RipResult(title_index=i, success=True,
                  output_file=str(out_dir / f"t{i:02d}.mkv"))
        for i in selected
    ]

    driver.state.update({
        "workflow": "orchestrate",
        "drive": scenario.drive_info(),
        "disc_info": disc_info,
        "title": scenario.title,
        "tmdb_match": match,
        "movie_runtime": (scenario.movie_detail().runtime_seconds
                          if not scenario.is_tv else None),
        "show_detail": scenario.show_detail() if scenario.is_tv else None,
        "release": provider_mocks.FakeRelease(name=scenario.release_name() or "Rel"),
        "dvdcompare_discs": discs,
        "selected_discs": scenario.disc_numbers,
        "selected_titles": selected,
        "output_dir": out_dir,
        "makemkvcon": Path("makemkvcon"),
        "rip_results": rip_results,
        "disc_queue": scenario.disc_numbers or [1],
        "current_disc_idx": 0,
        "_orchestrate_disc_number": (scenario.disc_numbers or [1])[0],
        "ripped_discs": set(),
        "all_rip_results": {n: rip_results for n in (scenario.disc_numbers or [1])},
        "season_number": 1 if scenario.is_tv else None,
        # organize workflow keys
        "source_folder": tmp_path,
        "scanned": [],
        "organize_plan": None,
        "organize_results": None,
        "dvdcompare_film_id": 12345,
        # update screen
        "update_info": {
            "tag": "v9.9.9",
            "name": "Test Release",
            "body": "notes",
            "url": "https://example.com",
        },
    })


@pytest.mark.parametrize("scenario_name", SMOKE_SCENARIOS)
@pytest.mark.parametrize("screen", ALL_SCREENS)
def test_screen_builds_without_crash(gui, tmp_path, scenario_name, screen):
    driver = gui(scenario_name)
    scenario = load_scenario(scenario_name)
    _populate_state(driver, scenario, tmp_path)

    driver.navigate(screen)

    assert driver.page.controls, f"{screen}: produced no controls"
    assert not driver.crashed(), f"{screen}: surfaced a crash dialog"
