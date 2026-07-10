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


def test_welcome_rip_button_starts_orchestrate(gui):
    d = gui("the-matrix-1999")

    d.click("Rip Disc")

    assert d.state["workflow"] == "orchestrate"
    # A single loaded drive auto-picks and reads, routing straight on to the
    # metadata lookup — disc_detection is transient in this happy path.
    assert d.current == "metadata"
    assert d.state.get("disc_info") is not None
    assert not d.crashed()


def test_welcome_organize_button_starts_organize(gui):
    d = gui("the-matrix-1999")

    d.click("Organize Rips")

    assert d.state["workflow"] == "organize"
    assert not d.crashed()
