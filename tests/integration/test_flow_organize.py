"""Organize flow: welcome -> folder_picker (scan) -> results -> metadata ->
release -> organize_preview.

The scanner and layout detector are mocked so no ffprobe / real files are
needed; TMDb + dvdcompare come from the scenario. This asserts the organize
workflow's screens hand off correctly and the plan preview builds.
"""

from __future__ import annotations

import pytest

from riplex.detect import OrganizeLayout
from riplex.models import ScannedDisc, ScannedFile


@pytest.fixture
def organize(gui, tmp_path, monkeypatch):
    d = gui("the-matrix-1999")
    import riplex_app.screens.folder_picker as fp

    disc = ScannedDisc(
        folder_name="Disc 1",
        files=[ScannedFile(
            name="t00.mkv", path=str(tmp_path / "t00.mkv"),
            duration_seconds=8100, max_width=1920, max_height=1080,
        )],
    )
    monkeypatch.setattr(fp, "detect_organize_layout", lambda root: OrganizeLayout(mode="single"))
    monkeypatch.setattr(fp, "scan_folder", lambda folder, **k: [disc])
    d.tmp_path = tmp_path  # type: ignore[attr-defined]
    return d


def test_organize_enters_folder_picker(organize):
    organize.click("Organize Rips")

    assert organize.state["workflow"] == "organize"
    assert organize.current == "folder_picker"
    assert not organize.crashed()


def test_organize_scan_reaches_results(organize):
    organize.click("Organize Rips")
    organize.screen.folder_field.value = str(organize.tmp_path)

    organize.click("Scan")

    assert organize.current == "folder_picker"  # results view
    assert organize.has_text("Scanned 1 disc")
    assert organize.state.get("source_folder") is not None
    assert not organize.crashed()


def test_organize_full_flow_reaches_preview(organize):
    organize.click("Organize Rips")
    organize.screen.folder_field.value = str(organize.tmp_path)
    organize.click("Scan")
    organize.click("Next")  # results -> metadata

    assert organize.current == "metadata"
    organize.click("Next")  # accept TMDb match -> release -> organize_preview

    assert organize.current in {"release", "organize_preview"}
    assert not organize.crashed()
