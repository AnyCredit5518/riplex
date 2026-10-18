"""Explicit release corrections must never be undone by automatic selection."""

from __future__ import annotations

import pytest

from dvdcompare.models import Disc, FilmComparison, Release

from riplex.disc.provider import DiscProvider, _convert_release
from riplex_app.screens import release as release_mod


@pytest.mark.parametrize("change_release", [True, False])
def test_back_from_overview_can_override_wrong_single_release(
    gui, monkeypatch, change_release, caplog,
):
    driver = gui("chernobyl-2019")
    wrong_release = Release(
        name="Wrong documentary release",
        discs=[Disc(number=1, format="Blu-ray", is_film=True)],
    )
    wrong = FilmComparison(
        title="Hell in the Pacific: The True Stories - Season 1 (TV)",
        film_id=44020, releases=[wrong_release],
    )
    correct = FilmComparison(
        title="Pacific (The) (Mini-series)", film_id=27242,
        releases=[
            Release(
                name="Pacific standard release",
                discs=[Disc(number=n, format="Blu-ray", is_film=True) for n in range(1, 7)],
            ),
            Release(
                name="Pacific exclusive release",
                discs=[Disc(number=n, format="Blu-ray", is_film=True) for n in range(1, 8)],
            ),
        ],
    )
    calls = []
    saved = []

    async def _fetch_film(self, title, disc_format, *, year=None):
        calls.append(("title", title))
        return wrong

    async def _fetch_by_id(self, film_id):
        calls.append(("id", film_id))
        assert film_id == 27242
        return correct

    screen = driver.app.screens["release"]
    monkeypatch.setattr(DiscProvider, "fetch_film", _fetch_film)
    monkeypatch.setattr(DiscProvider, "fetch_film_by_id", _fetch_by_id)
    monkeypatch.setattr(release_mod, "_convert_release", _convert_release)
    monkeypatch.setattr(screen, "_load_persisted_override", lambda: None)
    monkeypatch.setattr(
        screen, "_save_persisted_override",
        lambda fid, key=None: saved.append(fid),
    )
    caplog.set_level("DEBUG", logger="riplex_app.screens.release")

    driver.click("Rip Disc")
    driver.click("Next")
    assert driver.current == "disc_overview"
    assert driver.state["release"] is wrong_release

    driver.click("Back")
    assert driver.current == "release"
    if change_release:
        driver.click("Change release")

    assert driver.current == "release"
    assert any(control is screen._fid_field for control in driver.controls())
    assert calls == [("title", "Chernobyl")]
    screen._fid_field.value = "https://www.dvdcompare.net/comparisons/film.php?fid=27242"
    driver.click("Use this")

    assert calls[-1] == ("id", 27242)
    assert driver.current == "release"
    assert driver.has_text("Pacific (The) (Mini-series)")
    screen.release_radio_group.value = "1"
    screen.release_radio_group.on_change(None)
    driver.click("Next")

    assert driver.current == "disc_overview"
    assert len(driver.page.controls) == 1
    assert driver.state["dvdcompare_film_id"] == 27242
    assert driver.state["_dvdcompare_film"] is correct
    assert driver.state["release"] is correct.releases[1]
    assert [disc.number for disc in driver.state["dvdcompare_discs"]] == list(range(1, 8))
    assert saved == [27242]
    assert "manual-override" in caplog.text
    assert "highlight index=1 fid=27242" in caplog.text
    assert "Pacific exclusive release" in caplog.text
    assert not driver.crashed()


def test_single_release_correction_remains_a_picker_across_rebuilds(gui, monkeypatch):
    driver = gui("chernobyl-2019")
    screen = driver.app.screens["release"]
    monkeypatch.setattr(screen, "_load_persisted_override", lambda: None)
    driver.click("Rip Disc")
    driver.click("Next")
    assert driver.current == "disc_overview"
    selected = driver.state["release"]
    driver.click("Back")
    driver.click("Change release")

    assert driver.current == "release"
    assert driver.state["release"] is None
    assert any(control is screen._fid_field for control in driver.controls())
    assert any(control is screen._search_field for control in driver.controls())

    driver.navigate("release")

    assert driver.current == "release"
    assert driver.state["release"] is None
    assert any(control is screen._fid_field for control in driver.controls())
    driver.click("Next")
    assert driver.current == "disc_overview"
    assert driver.state["release"] is selected