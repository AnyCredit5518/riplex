"""Tests for organize-preview presentation helpers."""

from types import SimpleNamespace

from riplex_app.background import capture_screen_lease, start_background_once
from riplex_app.screens.organize_preview import OrganizePreviewScreen, _natural_sort_key


class _App:
    def __init__(self):
        self.state = {}
        self.page = SimpleNamespace(update=lambda: None)


class _DeferredThread:
    created: list["_DeferredThread"] = []

    def __init__(self, *, target, daemon, name=None, args=()):
        self.target = target
        self.args = args
        self.created.append(self)

    def start(self):
        pass


def test_destination_order_groups_seasons_and_sorts_episodes():
    destinations = [
        "Season 01/Firefly (2002) - s01e08 - Ariel.mkv",
        "Season 00/Firefly (2002) - s00e04 - Making of Firefly.mkv",
        "Season 01/Firefly (2002) - s01e11 - Serenity.mkv",
        "Season 01/Firefly (2002) - s01e01 - The Train Job.mkv",
    ]

    assert sorted(destinations, key=_natural_sort_key) == [
        "Season 00/Firefly (2002) - s00e04 - Making of Firefly.mkv",
        "Season 01/Firefly (2002) - s01e01 - The Train Job.mkv",
        "Season 01/Firefly (2002) - s01e08 - Ariel.mkv",
        "Season 01/Firefly (2002) - s01e11 - Serenity.mkv",
    ]


def test_natural_order_handles_unpadded_numbers():
    labels = ["Disc 10: Extra", "Disc 2: Extra", "Disc 1: Extra"]

    assert sorted(labels, key=_natural_sort_key) == [
        "Disc 1: Extra",
        "Disc 2: Extra",
        "Disc 10: Extra",
    ]


def test_repeated_loading_build_starts_one_plan_worker(monkeypatch):
    _DeferredThread.created = []
    monkeypatch.setattr("riplex_app.background.threading.Thread", _DeferredThread)
    screen = OrganizePreviewScreen(_App())

    first = screen.build()
    second = screen.build()

    assert second is first
    assert len(_DeferredThread.created) == 1


def test_duplicate_organize_click_starts_one_execution_worker(monkeypatch):
    _DeferredThread.created = []
    monkeypatch.setattr("riplex_app.background.threading.Thread", _DeferredThread)
    screen = OrganizePreviewScreen(_App())
    screen.organize_btn = SimpleNamespace(
        disabled=False,
        content="Organize",
        update=lambda: None,
    )

    screen._execute(None)
    screen._execute(None)

    assert len(_DeferredThread.created) == 1
    assert screen.organize_btn.disabled
    assert screen.organize_btn.content == "Organizing..."


def test_rejected_organize_launch_restores_button(monkeypatch):
    _DeferredThread.created = []
    monkeypatch.setattr("riplex_app.background.threading.Thread", _DeferredThread)
    app = _App()
    start_background_once(app, "organize-execute", lambda: None)
    screen = OrganizePreviewScreen(app)
    screen.organize_plan = SimpleNamespace(moves=[object()], splits=[])
    screen.organize_btn = SimpleNamespace(
        disabled=False,
        content="Organize",
        update=lambda: None,
    )

    screen._execute(None)

    assert screen._executing is False
    assert screen.organize_btn.disabled is False
    assert screen.organize_btn.content == "Organize"


def test_late_organize_execution_does_not_mutate_new_workflow(monkeypatch, tmp_path):
    _DeferredThread.created = []
    monkeypatch.setattr("riplex_app.background.threading.Thread", _DeferredThread)
    app = _App()
    app._current_screen_name = "organize_preview"
    app._navigation_epoch = 1
    old_source = tmp_path / "old"
    new_source = tmp_path / "new"
    old_output = tmp_path / "old-library"
    new_output = tmp_path / "new-library"
    app.state.update({
        "source_folder": old_source,
        "title": "Old title",
        "output_root": old_output,
    })
    screen = OrganizePreviewScreen(app)
    old_plan = SimpleNamespace(moves=[object()], splits=[])
    new_plan = SimpleNamespace(moves=[], splits=[])
    screen.organize_plan = old_plan
    screen.planned = "old planned"
    screen.organize_btn = SimpleNamespace(
        disabled=False,
        content="Organize",
        update=lambda: None,
    )
    markers = []

    def _execute_plan(plan, *, dry_run):
        assert plan is old_plan
        assert dry_run is False
        app._current_screen_name = "folder_picker"
        app._navigation_epoch = 2
        app.state.update({
            "source_folder": new_source,
            "title": "New title",
            "output_root": new_output,
            "organize_results": ["new workflow"],
        })
        screen.organize_plan = new_plan
        screen.planned = "new planned"
        return ["old result"]

    monkeypatch.setattr(
        "riplex_app.screens.organize_preview.execute_plan",
        _execute_plan,
    )
    monkeypatch.setattr(
        "riplex_app.screens.organize_preview.save_organized_marker",
        lambda source, **kwargs: markers.append((source, kwargs)),
    )
    app.page.run_task = lambda _handler: None

    screen._execute(None)
    worker = _DeferredThread.created[-1]
    worker.target(*worker.args)

    assert app.state["organize_results"] == ["new workflow"]
    assert markers == [(
        old_source,
        {
            "title": "Old title",
            "file_count": 1,
            "output_root": str(old_output),
        },
    )]


def test_late_plan_does_not_restore_organize_preview(monkeypatch, tmp_path):
    app = _App()
    app.state.update({
        "tmdb_match": SimpleNamespace(media_type="movie", title="Movie"),
        "scanned": [],
    })
    app._current_screen_name = "organize_preview"
    app._navigation_epoch = 4
    screen = OrganizePreviewScreen(app)
    monkeypatch.setattr("riplex_app.screens.organize_preview.get_api_key", lambda: "key")
    monkeypatch.setattr(
        "riplex_app.screens.organize_preview.get_output_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        screen,
        "_build_single_plan",
        lambda *_args: (object(), object()),
    )
    lease = capture_screen_lease(app)

    app._current_screen_name = "release"
    app._navigation_epoch += 1
    screen._build_plan(lease)

    assert "_organize_plan" not in app.state