"""Shared ``app.state`` seeding for headless screen rendering.

Extracted from ``tests/integration/test_screen_build_smoke.py`` so both the
smoke matrix and the ``scripts/gui_screenshot.py`` debug launcher fill state the
same way. Given a loaded :class:`~tests.support.fixtures.Scenario`, populate a
plain ``state`` dict with realistic values every screen can read.
"""

from __future__ import annotations

from pathlib import Path

from riplex.disc.makemkv import RipResult
from riplex.normalize import sanitize_filename
from tests.support import provider_mocks


def populate_state(state: dict, scenario, tmp_path: Path) -> None:
    """Fill *state* with realistic values for every screen to read."""
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

    state.update({
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
