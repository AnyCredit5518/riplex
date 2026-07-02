"""Tests for the per-DiscGroup organize router."""

from __future__ import annotations

from pathlib import Path

import pytest

from riplex.models import (
    DiscGroup,
    FilmSlot,
    ScannedDisc,
    ScannedFile,
)
from riplex.organize_by_group import (
    _match_files_to_film_slots,
    _partition_scanned_by_group,
    apply_group_overrides,
    build_multi_group_plan,
    merge_plans,
)
from riplex.organizer import FileMove, OrganizePlan


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_file(name: str, duration: int, *, path: str | None = None) -> ScannedFile:
    return ScannedFile(
        name=name,
        path=path or f"/rips/{name}",
        duration_seconds=duration,
    )


def _make_scanned_disc(disc_num: int, *files: ScannedFile) -> ScannedDisc:
    return ScannedDisc(folder_name=f"Disc {disc_num}", files=list(files))


class _FakeMatch:
    """Stand-in for a MetadataSearchResult; only the attributes the
    router reads are populated."""

    def __init__(self, title: str, year: int, media_type: str = "movie",
                 source_id: str = "1"):
        self.title = title
        self.year = year
        self.media_type = media_type
        self.source_id = source_id


# ---------------------------------------------------------------------------
# apply_group_overrides
# ---------------------------------------------------------------------------


class TestApplyGroupOverrides:
    def test_group_level_match_written(self):
        g = DiscGroup(id="main_1", label="Main", disc_numbers=[1], kind="main")
        m = _FakeMatch("Psych", 2006, "tv")
        apply_group_overrides([g], {"main_1": {"match": m, "source": "user"}})
        assert g.tmdb_match is m
        assert g.source == "user"

    def test_film_slot_override_written(self):
        slot = FilmSlot(title="Psych 2", runtime_seconds=5300)
        g = DiscGroup(
            id="film_31", label="Films", disc_numbers=[31],
            kind="film", films=[slot],
        )
        m = _FakeMatch("Psych 2: Lassie Come Home", 2020)
        apply_group_overrides([g], {
            "film_31": {"films": {0: {"match": m, "source": "auto"}}},
        })
        assert g.films[0].tmdb_match is m
        assert g.films[0].source == "auto"

    def test_no_override_leaves_group_untouched(self):
        g = DiscGroup(id="main_1", label="Main", disc_numbers=[1], kind="main")
        apply_group_overrides([g], {})
        assert g.tmdb_match is None
        assert g.source is None

    def test_out_of_range_film_idx_ignored(self):
        g = DiscGroup(
            id="film_31", label="Films", disc_numbers=[31],
            kind="film", films=[FilmSlot(title="Only", runtime_seconds=5000)],
        )
        m = _FakeMatch("Bogus", 2020)
        # idx 5 doesn't exist — must not raise, must not touch slot 0.
        apply_group_overrides([g], {
            "film_31": {"films": {5: {"match": m, "source": "auto"}}},
        })
        assert g.films[0].tmdb_match is None


# ---------------------------------------------------------------------------
# _partition_scanned_by_group
# ---------------------------------------------------------------------------


class TestPartitionScannedByGroup:
    def test_folders_route_by_disc_number(self):
        groups = [
            DiscGroup(id="main_1", label="Main",
                      disc_numbers=[1, 2, 3], kind="main"),
            DiscGroup(id="film_31", label="Films",
                      disc_numbers=[31], kind="film"),
        ]
        scanned = [
            _make_scanned_disc(1, _make_file("t1.mkv", 2500)),
            _make_scanned_disc(2, _make_file("t2.mkv", 2500)),
            _make_scanned_disc(31, _make_file("m1.mkv", 5300)),
        ]
        by_group, orphans = _partition_scanned_by_group(scanned, groups)
        assert [sd.folder_name for sd in by_group["main_1"]] == ["Disc 1", "Disc 2"]
        assert [sd.folder_name for sd in by_group["film_31"]] == ["Disc 31"]
        assert orphans == []

    def test_unmapped_folder_becomes_orphan(self):
        groups = [DiscGroup(id="main_1", label="Main", disc_numbers=[1], kind="main")]
        scanned = [
            _make_scanned_disc(1, _make_file("t1.mkv", 2500)),
            ScannedDisc(folder_name="Bonus", files=[_make_file("x.mkv", 500)]),
        ]
        by_group, orphans = _partition_scanned_by_group(scanned, groups)
        assert len(by_group["main_1"]) == 1
        assert [sd.folder_name for sd in orphans] == ["Bonus"]

    def test_disc_number_not_in_any_group_is_orphan(self):
        groups = [DiscGroup(id="main_1", label="Main", disc_numbers=[1], kind="main")]
        scanned = [_make_scanned_disc(99, _make_file("t.mkv", 500))]
        by_group, orphans = _partition_scanned_by_group(scanned, groups)
        assert by_group["main_1"] == []
        assert len(orphans) == 1


# ---------------------------------------------------------------------------
# _match_files_to_film_slots
# ---------------------------------------------------------------------------


class TestMatchFilesToFilmSlots:
    def test_exact_runtime_matches_each_slot(self):
        m1 = _FakeMatch("Psych: The Movie", 2017)
        m2 = _FakeMatch("Psych 2", 2020)
        slots = [
            FilmSlot(title="Psych: The Movie", runtime_seconds=5280, tmdb_match=m1),
            FilmSlot(title="Psych 2", runtime_seconds=5300, tmdb_match=m2),
        ]
        scanned = [_make_scanned_disc(
            31,
            _make_file("a.mkv", 5280),
            _make_file("b.mkv", 5300),
        )]
        matches, leftover = _match_files_to_film_slots(scanned, slots)
        assert len(matches) == 2
        pairing = {m[0].title: m[1].name for m in matches}
        assert pairing == {"Psych: The Movie": "a.mkv", "Psych 2": "b.mkv"}
        assert leftover == []

    def test_short_file_excluded_from_all_slots(self):
        m = _FakeMatch("Psych: The Movie", 2017)
        slots = [FilmSlot(title="Movie", runtime_seconds=5280, tmdb_match=m)]
        scanned = [_make_scanned_disc(
            31,
            _make_file("main.mkv", 5280),
            _make_file("menu.mkv", 30),  # too short — outside tolerance
        )]
        matches, leftover = _match_files_to_film_slots(scanned, slots)
        assert len(matches) == 1
        assert matches[0][1].name == "main.mkv"
        assert [f.name for f in leftover] == ["menu.mkv"]

    def test_slot_without_tmdb_match_is_skipped(self):
        slots = [
            FilmSlot(title="Assigned", runtime_seconds=5000,
                     tmdb_match=_FakeMatch("Assigned", 2020)),
            FilmSlot(title="Unassigned", runtime_seconds=5100),  # no match
        ]
        scanned = [_make_scanned_disc(
            31,
            _make_file("a.mkv", 5000),
            _make_file("b.mkv", 5100),
        )]
        matches, leftover = _match_files_to_film_slots(scanned, slots)
        assert len(matches) == 1
        assert matches[0][0].title == "Assigned"
        # b.mkv would have gone to the unassigned slot — stays as leftover.
        assert [f.name for f in leftover] == ["b.mkv"]

    def test_greedy_smallest_delta_wins(self):
        # Two slots close in runtime; the closest file wins each pairing.
        m1 = _FakeMatch("A", 2020)
        m2 = _FakeMatch("B", 2021)
        slots = [
            FilmSlot(title="A", runtime_seconds=5000, tmdb_match=m1),
            FilmSlot(title="B", runtime_seconds=5010, tmdb_match=m2),
        ]
        scanned = [_make_scanned_disc(
            31,
            _make_file("f1.mkv", 5000),  # exact for A
            _make_file("f2.mkv", 5010),  # exact for B
        )]
        matches, _leftover = _match_files_to_film_slots(scanned, slots)
        pairing = {m[0].title: m[1].name for m in matches}
        assert pairing == {"A": "f1.mkv", "B": "f2.mkv"}


# ---------------------------------------------------------------------------
# merge_plans
# ---------------------------------------------------------------------------


class TestMergePlans:
    def test_concatenates_all_lists(self):
        p1 = OrganizePlan(
            moves=[FileMove(source="a", destination="b", label="A",
                            confidence="high")],
            unmatched=[_make_file("u1.mkv", 100)],
            missing=["m1"],
        )
        p2 = OrganizePlan(
            moves=[FileMove(source="c", destination="d", label="B",
                            confidence="high")],
            missing=["m2"],
        )
        merged = merge_plans([p1, p2])
        assert len(merged.moves) == 2
        assert len(merged.unmatched) == 1
        assert merged.missing == ["m1", "m2"]

    def test_empty_input_yields_empty_plan(self):
        merged = merge_plans([])
        assert merged.moves == []
        assert merged.splits == []
        assert merged.unmatched == []
        assert merged.missing == []


# ---------------------------------------------------------------------------
# build_multi_group_plan — integration around film-slot routing
# ---------------------------------------------------------------------------


class _NullProvider:
    """Provider that must never be called for pure film-slot routing."""

    async def search(self, *a, **kw):
        raise AssertionError("provider.search should not be called")

    async def get_movie_detail(self, *a, **kw):
        raise AssertionError("provider.get_movie_detail should not be called")

    async def get_show_detail(self, *a, **kw):
        raise AssertionError("provider.get_show_detail should not be called")

    async def close(self):
        pass


class TestBuildMultiGroupPlanFilmSlots:
    """The per-film routing path doesn't touch the planner, so we can
    exercise it end-to-end without mocking the TMDb network."""

    @pytest.mark.asyncio
    async def test_three_films_each_route_to_their_own_movie_folder(self, tmp_path):
        # Psych disc 31 shape: three standalone films.
        m1 = _FakeMatch("Psych: The Movie", 2017)
        m2 = _FakeMatch("Psych 2: Lassie Come Home", 2020)
        m3 = _FakeMatch("Psych 3: This Is Gus", 2021)
        group = DiscGroup(
            id="film_31", label="3 feature films (disc 31)",
            disc_numbers=[31], kind="film",
            films=[
                FilmSlot(title="The Film", runtime_seconds=5280, tmdb_match=m1),
                FilmSlot(title="Psych 2", runtime_seconds=5300, tmdb_match=m2),
                FilmSlot(title="Psych 3", runtime_seconds=5760, tmdb_match=m3),
            ],
        )
        scanned = [_make_scanned_disc(
            31,
            _make_file("t01.mkv", 5280),
            _make_file("t02.mkv", 5300),
            _make_file("t03.mkv", 5760),
        )]

        merged, group_plans = await build_multi_group_plan(
            scanned, dvdcompare_discs=[], disc_groups=[group],
            provider=_NullProvider(),
            output_root=tmp_path,
        )

        assert len(merged.moves) == 3
        destinations = {Path(m.destination).parent.name for m in merged.moves}
        assert destinations == {
            "Psych - The Movie (2017)",
            "Psych 2 - Lassie Come Home (2020)",
            "Psych 3 - This Is Gus (2021)",
        }
        # Each destination lives under Movies/, not TV Shows/
        for mv in merged.moves:
            assert Path(mv.destination).parts[-3] == "Movies"

        assert len(group_plans) == 1
        assert group_plans[0].group_id == "film_31"
        assert group_plans[0].planned is None  # bypasses planner

    @pytest.mark.asyncio
    async def test_slot_without_match_becomes_missing(self, tmp_path):
        group = DiscGroup(
            id="film_31", label="Films", disc_numbers=[31], kind="film",
            films=[
                FilmSlot(title="Assigned", runtime_seconds=5280,
                         tmdb_match=_FakeMatch("Assigned", 2020)),
                FilmSlot(title="Unassigned", runtime_seconds=5300),  # no match
            ],
        )
        scanned = [_make_scanned_disc(
            31,
            _make_file("t01.mkv", 5280),
            _make_file("t02.mkv", 5300),
        )]

        merged, _ = await build_multi_group_plan(
            scanned, dvdcompare_discs=[], disc_groups=[group],
            provider=_NullProvider(),
            output_root=tmp_path,
        )

        assert len(merged.moves) == 1
        # t02.mkv couldn't be assigned to a slot with a match → leftover.
        assert any(f.name == "t02.mkv" for f in merged.unmatched)

    @pytest.mark.asyncio
    async def test_group_with_no_scanned_files_is_skipped(self, tmp_path):
        group = DiscGroup(
            id="film_31", label="Films", disc_numbers=[31], kind="film",
            films=[FilmSlot(title="F", runtime_seconds=5280,
                            tmdb_match=_FakeMatch("F", 2020))],
        )
        merged, group_plans = await build_multi_group_plan(
            scanned=[], dvdcompare_discs=[], disc_groups=[group],
            provider=_NullProvider(),
            output_root=tmp_path,
        )
        assert merged.moves == []
        assert group_plans[0].skipped_reason.startswith("no ripped files")

    @pytest.mark.asyncio
    async def test_group_without_any_assigned_match_is_skipped(self, tmp_path):
        # Film group with slots but none of the slots got a match — the
        # entire branch is skipped (no planner fallback for this case).
        group = DiscGroup(
            id="film_31", label="Films", disc_numbers=[31], kind="film",
            films=[FilmSlot(title="F", runtime_seconds=5280)],
        )
        scanned = [_make_scanned_disc(31, _make_file("t.mkv", 5280))]
        merged, group_plans = await build_multi_group_plan(
            scanned, dvdcompare_discs=[], disc_groups=[group],
            provider=_NullProvider(),
            output_root=tmp_path,
        )
        # No slot has a match — the film branch is skipped, and
        # group.tmdb_match is also None so we short-circuit with a
        # "no TMDb match assigned" reason.
        assert merged.moves == []
        assert group_plans[0].skipped_reason == "no TMDb match assigned"
