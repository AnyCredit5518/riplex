"""End-to-end welcome-screen harness smoke test.

Constructing the driver already exercises the riskiest bit of the harness:
``RiplexApp.__init__`` navigates to welcome, which builds a real screen, fires
the (mocked) update + connectivity checks on synchronous threads, and injects
the global Quit button. If any of that throws, the harness is broken.
"""

from __future__ import annotations


def test_welcome_builds_without_crash(gui):
    d = gui("the-matrix-1999")

    assert d.current == "welcome"
    assert d.page.controls, "welcome produced no controls"
    assert not d.crashed()
    # The two workflow entry points are present.
    assert d.has_text("Rip Disc")
    assert d.has_text("Organize Rips")


def test_harness_overrides_welcome_config_alias(gui, monkeypatch):
    from riplex_app.screens import welcome as welcome_mod

    monkeypatch.setattr(welcome_mod, "load_config", lambda: {})
    d = gui("the-matrix-1999")

    d.click("Organize Rips")

    assert d.state["workflow"] == "organize"


def test_welcome_rip_button_starts_orchestrate(gui):
    d = gui("the-matrix-1999")

    d.click("Rip Disc")

    assert d.state["workflow"] == "orchestrate"
    # A single loaded drive auto-picks and reads, routing straight on to the
    # metadata lookup — disc_detection is transient in this happy path.
    assert d.current == "metadata"
    assert d.state.get("disc_info") is not None
    assert not d.crashed()


def test_welcome_blocks_rip_when_output_folder_is_unusable(gui, tmp_path):
    blocked_parent = tmp_path / "Riplex"
    blocked_parent.write_text("not a directory", encoding="utf-8")
    rip_output = blocked_parent / "Raw"
    d = gui("the-matrix-1999", config={"rip_output": str(rip_output)})

    d.click("Rip Disc")

    assert d.current == "welcome"
    assert d.has_text(str(rip_output))
    assert d.has_text("Edit Settings")
    assert d.state["workflow"] is None
    assert d.state.get("disc_info") is None
    assert not d.crashed()


def test_welcome_organize_button_starts_organize(gui):
    d = gui("the-matrix-1999")

    d.click("Organize Rips")

    assert d.state["workflow"] == "organize"
    assert not d.crashed()


def test_welcome_organize_refreshes_stale_output_roots(gui, tmp_path):
    output_root = tmp_path / "Current Media"
    rip_output = tmp_path / "Current Rips"
    d = gui("the-matrix-1999", config={
        "output_root": str(output_root),
        "rip_output": str(rip_output),
    })
    d.state["output_root"] = str(tmp_path / "Stale Media")
    d.state["rip_output"] = str(tmp_path / "Stale Rips")

    d.click("Organize Rips")

    assert d.state["output_root"] == str(output_root.absolute())
    assert "rip_output" not in d.state
    assert not rip_output.exists()
    assert d.state["workflow"] == "organize"
