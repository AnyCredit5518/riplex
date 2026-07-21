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

from tests.support.fixtures import ALL_CATEGORIES, load_scenario, scenarios_by_category
from tests.support.seed import populate_state


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
    populate_state(driver.state, scenario, tmp_path)


@pytest.mark.parametrize("scenario_name", SMOKE_SCENARIOS)
@pytest.mark.parametrize("screen", ALL_SCREENS)
def test_screen_builds_without_crash(gui, tmp_path, scenario_name, screen):
    driver = gui(scenario_name)
    scenario = load_scenario(scenario_name)
    _populate_state(driver, scenario, tmp_path)

    driver.navigate(screen)

    assert driver.page.controls, f"{screen}: produced no controls"
    assert not driver.crashed(), f"{screen}: surfaced a crash dialog"
