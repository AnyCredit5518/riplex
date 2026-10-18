"""Focused tests for title-selection screen presets."""

from types import SimpleNamespace

from riplex.disc.makemkv import DiscTitle
from riplex_app.screens import selection as selection_module
from riplex_app.screens.selection import SelectionScreen
from tests.support.disc_fixtures import load_disc_fixture, load_show_detail
from tests.support.fake_page import FakePage


def _title(index: int, size_gb: int = 1) -> DiscTitle:
    return DiscTitle(
        index=index,
        name=f"Title {index}",
        duration_seconds=3600 + index,
        chapters=6,
        size_bytes=size_gb * 1024 ** 3,
        filename=f"title_t{index:02d}.mkv",
        playlist=f"000{index:02d}.mpls",
        resolution="1920x1080",
        video_codec="Mpeg4",
        segment_count=1,
    )


def _build_screen(monkeypatch, *, media_type: str):
    titles = [_title(0), _title(1), _title(2)]
    analysis = SimpleNamespace(
        disc_number=1,
        dvd_entries=[],
        total_episode_runtime=0,
        episode_count=0,
        rippable_titles=[titles[0], titles[2]],
        primary_title_indices={titles[0].index},
        classifications={
            0: "MAIN FILM (1080p)" if media_type == "movie" else "S01E01 - Pilot (1080p)",
            1: "Duplicate of #0 (1080p)",
            2: "[featurette] Making Of (1080p)",
        },
        assessments={
            0: SimpleNamespace(
                recommendation="rip",
                identification="Main feature" if media_type == "movie" else "Matched episode",
                name="Test Title" if media_type == "movie" else "Pilot",
            ),
            1: SimpleNamespace(
                recommendation="skip",
                identification="Duplicate",
                name="Unknown",
            ),
            2: SimpleNamespace(
                recommendation="rip",
                identification="Matched featurette",
                name="Making Of",
            ),
        },
        recovered_carryover_indices=set(),
    )
    monkeypatch.setattr(selection_module, "analyze_disc", lambda *_args, **_kwargs: analysis)

    page = FakePage()
    app = SimpleNamespace(
        page=page,
        state={
            "disc_info": SimpleNamespace(titles=titles, disc_name="TEST_DISC"),
            "tmdb_match": SimpleNamespace(
                media_type=media_type,
                title="Test Title",
                year=2020,
            ),
            "dvdcompare_discs": [],
        },
        navigate=lambda _route: None,
    )
    screen = SelectionScreen(app)
    monkeypatch.setattr(screen, "_save_selection_snapshot", lambda *_args, **_kwargs: None)
    screen.build()
    return screen, page


def test_movie_presets_apply_counts_and_disable_empty_start(monkeypatch):
    screen, page = _build_screen(monkeypatch, media_type="movie")

    assert screen._preset_buttons["all"].content == "All (3)"
    assert screen._preset_buttons["recommended"].content == "Recommended (2)"
    assert screen._preset_buttons["primary"].content == "Main film (1)"

    screen._preset_buttons["clear"].on_click(None)
    assert [checkbox.value for checkbox in screen.checkboxes] == [False, False, False]
    assert screen.summary_text.value == "No titles selected"
    assert screen._start_btn.disabled

    screen._preset_buttons["primary"].on_click(None)
    assert [checkbox.value for checkbox in screen.checkboxes] == [True, False, False]
    assert screen.summary_text.value == "1 title selected (1.0 GB)"
    assert not screen._start_btn.disabled
    assert page.update_count == 2


def test_tv_primary_preset_is_labeled_episodes(monkeypatch):
    screen, _page = _build_screen(monkeypatch, media_type="tv")

    assert screen._preset_buttons["primary"].content == "Episodes (1)"


def test_pacific_real_analysis_populates_episode_names_and_presets(monkeypatch):
    info, discs, _expected = load_disc_fixture("pacific_disc1.json")
    detail = load_show_detail("pacific_disc1.json")
    app = SimpleNamespace(
        page=FakePage(),
        state={
            "workflow": "orchestrate",
            "disc_info": info,
            "tmdb_match": SimpleNamespace(
                media_type="tv", title=detail.title, year=detail.year,
                source_id=detail.source_id,
            ),
            "dvdcompare_discs": discs,
            "dvdcompare_film_title": "Pacific (The) (Mini-series)",
            "show_detail": detail,
            "_orchestrate_disc_number": 1,
            "disc_queue": [1, 2, 3, 4, 5, 6],
            "episode_carryover_scope": (detail.source_id, None),
            "episode_carryover": [],
        },
        navigate=lambda _route: None,
    )
    screen = SelectionScreen(app)
    monkeypatch.setattr(screen, "_save_selection_snapshot", lambda *_args, **_kwargs: None)

    screen.build()

    assert screen._preset_buttons["all"].content == "All (19)"
    assert screen._preset_buttons["recommended"].content == "Recommended (2)"
    assert screen._preset_buttons["primary"].content == "Episodes (2)"
    assert not screen._preset_buttons["primary"].disabled
    assert [cb.data for cb in screen.checkboxes if cb.value] == [0, 1]
    assert screen._analysis.assessments[0].name == "Guadalcanal/Leckie"
    assert screen._analysis.assessments[1].name == "Basilone"
    assert screen._analysis.assessments[4].name == "Unknown"

    screen._preset_buttons["all"].on_click(None)
    assert all(cb.value for cb in screen.checkboxes)
    screen._preset_buttons["primary"].on_click(None)
    assert [cb.data for cb in screen.checkboxes if cb.value] == [0, 1]
    assert screen.summary_text.value == "2 titles selected (27.5 GB)"