"""Tests for organizer module."""

from pathlib import Path

from plex_planner.models import (
    MatchCandidate,
    OrganizeResult,
    PlannedEpisode,
    PlannedMovie,
    PlannedSeason,
    PlannedShow,
    ScannedFile,
)
from plex_planner.organizer import OrganizePlan, SplitMove, build_organize_plan, execute_plan


class TestBuildOrganizePlanMovie:
    def test_movie_main_file(self):
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="Movie_t01.mkv",
                    file_duration_seconds=10822,
                    matched_label="Oppenheimer (movie)",
                    matched_runtime_seconds=10860,
                    delta_seconds=38,
                    confidence="medium",
                ),
            ],
        )
        plan = PlannedMovie(
            canonical_title="Oppenheimer",
            year=2023,
            runtime="3h 1m",
            runtime_seconds=10860,
        )
        output = Path("E:/Media")
        op = build_organize_plan(result, plan, output)
        assert len(op.moves) == 1
        assert "Oppenheimer (2023).mkv" in op.moves[0].destination
        assert "Movies" in op.moves[0].destination

    def test_movie_extras(self):
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="SF_t02.mkv",
                    file_duration_seconds=5238,
                    matched_label="Disc 3: To End All War (documentary)",
                    matched_runtime_seconds=5238,
                    delta_seconds=0,
                    confidence="high",
                ),
                MatchCandidate(
                    file_name="SF_t03.mkv",
                    file_duration_seconds=501,
                    matched_label="Disc 3: Innovations in Film (featurette)",
                    matched_runtime_seconds=501,
                    delta_seconds=0,
                    confidence="high",
                ),
            ],
        )
        plan = PlannedMovie(
            canonical_title="Oppenheimer",
            year=2023,
            runtime="3h 1m",
            runtime_seconds=10860,
        )
        output = Path("E:/Media")
        op = build_organize_plan(result, plan, output)
        assert len(op.moves) == 2
        # Documentary -> Featurettes folder
        assert "Featurettes" in op.moves[0].destination
        assert "To End All War.mkv" in op.moves[0].destination
        # Featurette -> Featurettes folder
        assert "Featurettes" in op.moves[1].destination

    def test_unmatched_and_missing_passthrough(self):
        result = OrganizeResult(
            matched=[],
            unmatched=[ScannedFile(name="unknown.mkv", path="x", duration_seconds=100)],
            missing=["Disc 3: Some Feature"],
        )
        plan = PlannedMovie(
            canonical_title="Test",
            year=2023,
            runtime="2h",
            runtime_seconds=7200,
        )
        op = build_organize_plan(result, plan, Path("E:/Media"))
        assert len(op.unmatched) == 1
        assert len(op.missing) == 1


class TestBuildOrganizePlanShow:
    def test_tv_episode_disc_label(self):
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="d1_t00.mkv",
                    file_duration_seconds=3141,
                    matched_label="Disc 1: Coasts",
                    matched_runtime_seconds=3141,
                    delta_seconds=0,
                    confidence="high",
                ),
            ],
        )
        plan = PlannedShow(
            canonical_title="Planet Earth III",
            year=2023,
            seasons=[
                PlannedSeason(
                    season_number=1,
                    episodes=[
                        PlannedEpisode(season_number=1, episode_number=1, title="Coasts", runtime="52m"),
                        PlannedEpisode(season_number=1, episode_number=2, title="Ocean", runtime="52m"),
                    ],
                ),
            ],
        )
        output = Path("E:/Media")
        op = build_organize_plan(result, plan, output)
        assert len(op.moves) == 1
        dest = op.moves[0].destination
        assert "Season 01" in dest
        assert "TV Shows" in dest
        assert "Planet Earth III (2023) - s01e01 - Coasts.mkv" in dest

    def test_tv_episode_disc_label_no_tmdb_match_is_unmatched(self):
        """Episode not in TMDb data is treated as unmatched."""
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="d1_t00.mkv",
                    file_duration_seconds=3141,
                    matched_label="Disc 1: Unknown Episode",
                    matched_runtime_seconds=3141,
                    delta_seconds=0,
                    confidence="high",
                ),
            ],
        )
        plan = PlannedShow(
            canonical_title="Planet Earth III",
            year=2023,
        )
        output = Path("E:/Media")
        op = build_organize_plan(result, plan, output)
        assert len(op.moves) == 0
        assert len(op.unmatched) == 1
        assert op.unmatched[0].name == "d1_t00.mkv"

    def test_tv_extra_matching_season0_routes_to_season00(self):
        """A TV extra whose title matches a Season 00 episode goes to Season 00."""
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="making.mkv",
                    file_duration_seconds=2700,
                    matched_label="Disc 3: The Making of Planet Earth III (featurettes)",
                    matched_runtime_seconds=2700,
                    delta_seconds=0,
                    confidence="high",
                ),
            ],
        )
        plan = PlannedShow(
            canonical_title="Planet Earth III",
            year=2023,
            seasons=[
                PlannedSeason(
                    season_number=0,
                    episodes=[
                        PlannedEpisode(
                            season_number=0, episode_number=1,
                            title="The Making of Planet Earth III",
                            runtime="45m", runtime_seconds=2700,
                        ),
                    ],
                ),
            ],
        )
        output = Path("E:/Media")
        op = build_organize_plan(result, plan, output)
        assert len(op.moves) == 1
        dest = op.moves[0].destination
        assert "Season 00" in dest
        assert "s00e01" in dest
        assert "The Making of Planet Earth III" in dest
        assert "Featurettes" not in dest

    def test_tv_extra_not_in_season0_stays_in_extras(self):
        """A TV extra that doesn't match any Season 00 episode stays in extras."""
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="gag.mkv",
                    file_duration_seconds=300,
                    matched_label="Disc 3: Gag Reel (featurettes)",
                    matched_runtime_seconds=300,
                    delta_seconds=0,
                    confidence="high",
                ),
            ],
        )
        plan = PlannedShow(
            canonical_title="Planet Earth III",
            year=2023,
            seasons=[
                PlannedSeason(
                    season_number=0,
                    episodes=[
                        PlannedEpisode(
                            season_number=0, episode_number=1,
                            title="The Making of Planet Earth III",
                            runtime="45m", runtime_seconds=2700,
                        ),
                    ],
                ),
            ],
        )
        output = Path("E:/Media")
        op = build_organize_plan(result, plan, output)
        assert len(op.moves) == 1
        assert "Featurettes" in op.moves[0].destination
        assert "Season 00" not in op.moves[0].destination

    def test_movie_extra_not_affected_by_season0_routing(self):
        """Movie extras always go to extras folders, never Season 00."""
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="doc.mkv",
                    file_duration_seconds=5400,
                    matched_label="Disc 3: To End All War (documentary)",
                    matched_runtime_seconds=5400,
                    delta_seconds=0,
                    confidence="high",
                ),
            ],
        )
        plan = PlannedMovie(
            canonical_title="Oppenheimer",
            year=2023,
            runtime="3h",
            runtime_seconds=10860,
        )
        output = Path("E:/Media")
        op = build_organize_plan(result, plan, output)
        assert len(op.moves) == 1
        assert "Featurettes" in op.moves[0].destination


class TestExecutePlan:
    def test_dry_run(self):
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="t01.mkv",
                    file_duration_seconds=10000,
                    matched_label="Oppenheimer (movie)",
                    matched_runtime_seconds=10860,
                    delta_seconds=860,
                    confidence="low",
                ),
            ],
            unmatched=[ScannedFile(name="extra.mkv", path="y", duration_seconds=50)],
            missing=["Disc 3: Deleted Scene"],
        )
        plan = PlannedMovie(
            canonical_title="Oppenheimer",
            year=2023,
            runtime="3h",
            runtime_seconds=10860,
        )
        op = build_organize_plan(
            result, plan, Path("E:/Media"),
            scanned_files_by_name={"t01.mkv": "E:/rip/t01.mkv"},
        )
        actions = execute_plan(op, dry_run=True)
        text = "\n".join(actions)
        assert "WOULD MOVE" in text
        assert "UNMATCHED" in text
        assert "MISSING" in text
        assert "Deleted Scene" in text
        assert "[ignored]" in text

    def test_unmatched_ignore_policy(self):
        op = OrganizePlan(
            unmatched=[ScannedFile(name="extra.mkv", path="/rip/extra.mkv", duration_seconds=50)],
        )
        actions = execute_plan(op, dry_run=True, unmatched_policy="ignore")
        text = "\n".join(actions)
        assert "[ignored]" in text
        assert "WOULD MOVE" not in text

    def test_unmatched_move_policy_dry_run(self):
        op = OrganizePlan(
            unmatched=[ScannedFile(name="extra.mkv", path="/rip/extra.mkv", duration_seconds=50)],
        )
        actions = execute_plan(
            op, dry_run=True,
            unmatched_policy="move",
            unmatched_dir=Path("E:/Media/_Unmatched/Oppenheimer"),
        )
        text = "\n".join(actions)
        assert "WOULD MOVE" in text
        assert "_Unmatched" in text
        assert "extra.mkv" in text

    def test_unmatched_delete_policy_dry_run(self):
        op = OrganizePlan(
            unmatched=[ScannedFile(name="extra.mkv", path="/rip/extra.mkv", duration_seconds=50)],
        )
        actions = execute_plan(op, dry_run=True, unmatched_policy="delete")
        text = "\n".join(actions)
        assert "WOULD DELETE" in text
        assert "/rip/extra.mkv" in text


class TestSplitDetection:
    """Test chapter-based split detection for TV specials."""

    def _make_plan_with_season0(self, n_episodes: int) -> PlannedShow:
        eps = [
            PlannedEpisode(
                season_number=0, episode_number=i + 1,
                title=f"Diaries: Ep{i + 1}", runtime="10m", runtime_seconds=600,
            )
            for i in range(n_episodes)
        ]
        return PlannedShow(
            canonical_title="Planet Earth II",
            year=2016,
            seasons=[
                PlannedSeason(season_number=0, episodes=eps),
                PlannedSeason(
                    season_number=1,
                    episodes=[
                        PlannedEpisode(season_number=1, episode_number=1, title="Islands", runtime="50m"),
                    ],
                ),
            ],
        )

    def test_split_detected_when_chapters_match_season0(self):
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="diaries.mkv",
                    file_duration_seconds=3600,
                    matched_label="Disc 3: Planet Earth Diaries (featurettes)",
                    matched_runtime_seconds=3600,
                    delta_seconds=0,
                    confidence="high",
                ),
            ],
        )
        plan = self._make_plan_with_season0(6)
        scanned = {
            "diaries.mkv": ScannedFile(
                name="diaries.mkv", path="/rip/diaries.mkv",
                duration_seconds=3600, chapter_count=6,
            ),
        }
        op = build_organize_plan(result, plan, Path("E:/Media"), scanned_files=scanned)
        assert len(op.moves) == 0
        assert len(op.splits) == 1
        split = op.splits[0]
        assert split.source == "/rip/diaries.mkv"
        assert len(split.chapter_destinations) == 6
        assert "Season 00" in split.chapter_destinations[0]
        assert "s00e01" in split.chapter_destinations[0]
        assert "s00e06" in split.chapter_destinations[5]
        assert "Diaries Ep6" in split.chapter_destinations[5]

    def test_no_split_when_chapters_dont_match(self):
        """Chapters != Season 00 count falls through to extras folder."""
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="diaries.mkv",
                    file_duration_seconds=3600,
                    matched_label="Disc 3: Planet Earth Diaries (featurettes)",
                    matched_runtime_seconds=3600,
                    delta_seconds=0,
                    confidence="high",
                ),
            ],
        )
        plan = self._make_plan_with_season0(4)  # 4 eps but 6 chapters
        scanned = {
            "diaries.mkv": ScannedFile(
                name="diaries.mkv", path="/rip/diaries.mkv",
                duration_seconds=3600, chapter_count=6,
            ),
        }
        op = build_organize_plan(result, plan, Path("E:/Media"), scanned_files=scanned)
        assert len(op.splits) == 0
        assert len(op.moves) == 1
        assert "Featurettes" in op.moves[0].destination

    def test_no_split_when_single_chapter(self):
        """Single-chapter file is not a split candidate."""
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="extra.mkv",
                    file_duration_seconds=600,
                    matched_label="Disc 3: Some Extra (featurettes)",
                    matched_runtime_seconds=600,
                    delta_seconds=0,
                    confidence="high",
                ),
            ],
        )
        plan = self._make_plan_with_season0(1)
        scanned = {
            "extra.mkv": ScannedFile(
                name="extra.mkv", path="/rip/extra.mkv",
                duration_seconds=600, chapter_count=1,
            ),
        }
        op = build_organize_plan(result, plan, Path("E:/Media"), scanned_files=scanned)
        assert len(op.splits) == 0
        assert len(op.moves) == 1

    def test_no_split_without_scanned_files(self):
        """Without ScannedFile objects, no split detection occurs."""
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="diaries.mkv",
                    file_duration_seconds=3600,
                    matched_label="Disc 3: Planet Earth Diaries (featurettes)",
                    matched_runtime_seconds=3600,
                    delta_seconds=0,
                    confidence="high",
                ),
            ],
        )
        plan = self._make_plan_with_season0(6)
        # Only pass path map, not ScannedFile objects
        op = build_organize_plan(
            result, plan, Path("E:/Media"),
            scanned_files_by_name={"diaries.mkv": "/rip/diaries.mkv"},
        )
        assert len(op.splits) == 0
        assert len(op.moves) == 1

    def test_no_split_when_duration_ratio_too_low(self):
        """Single special whose chapter count coincidentally matches Season 00
        but whose duration is far shorter than the Season 00 total."""
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="making_of.mkv",
                    file_duration_seconds=2700,  # 45 min single special
                    matched_label="Disc 3: The Making Of (featurettes)",
                    matched_runtime_seconds=2700,
                    delta_seconds=0,
                    confidence="high",
                ),
            ],
        )
        # 6 Season 00 eps at 600s each = 3600s total; 2700/3600 = 0.75 boundary
        plan = self._make_plan_with_season0(6)
        scanned = {
            "making_of.mkv": ScannedFile(
                name="making_of.mkv", path="/rip/making_of.mkv",
                duration_seconds=2700, chapter_count=6,
            ),
        }
        op = build_organize_plan(result, plan, Path("E:/Media"), scanned_files=scanned)
        # Duration ratio 0.75 is at boundary; 2699 would be below.
        # This is a borderline case; the file goes to Featurettes, not split.
        # Actually 2700/3600 = 0.75 exactly which IS in range. Use 2600 instead.
        scanned["making_of.mkv"] = ScannedFile(
            name="making_of.mkv", path="/rip/making_of.mkv",
            duration_seconds=2600, chapter_count=6,
        )
        op = build_organize_plan(result, plan, Path("E:/Media"), scanned_files=scanned)
        assert len(op.splits) == 0
        assert len(op.moves) == 1
        assert "Featurettes" in op.moves[0].destination

    def test_no_split_when_duration_ratio_too_high(self):
        """File duration much longer than Season 00 total is not a compilation."""
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="long.mkv",
                    file_duration_seconds=5400,  # 90 min
                    matched_label="Disc 3: Long Feature (featurettes)",
                    matched_runtime_seconds=5400,
                    delta_seconds=0,
                    confidence="high",
                ),
            ],
        )
        plan = self._make_plan_with_season0(6)  # 6 eps * 600s = 3600s
        scanned = {
            "long.mkv": ScannedFile(
                name="long.mkv", path="/rip/long.mkv",
                duration_seconds=5400, chapter_count=6,
            ),
        }
        op = build_organize_plan(result, plan, Path("E:/Media"), scanned_files=scanned)
        assert len(op.splits) == 0
        assert len(op.moves) == 1

    def test_no_split_for_movie_extras(self):
        """Movies never get split, even with matching chapters."""
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="extras.mkv",
                    file_duration_seconds=3600,
                    matched_label="Disc 3: All Features (featurettes)",
                    matched_runtime_seconds=3600,
                    delta_seconds=0,
                    confidence="high",
                ),
            ],
        )
        plan = PlannedMovie(
            canonical_title="Test Movie", year=2023,
            runtime="2h", runtime_seconds=7200,
        )
        scanned = {
            "extras.mkv": ScannedFile(
                name="extras.mkv", path="/rip/extras.mkv",
                duration_seconds=3600, chapter_count=6,
            ),
        }
        op = build_organize_plan(result, plan, Path("E:/Media"), scanned_files=scanned)
        assert len(op.splits) == 0
        assert len(op.moves) == 1


class TestSplitDryRun:
    def test_dry_run_output(self):
        op = OrganizePlan(
            splits=[
                SplitMove(
                    source="/rip/diaries.mkv",
                    chapter_destinations=[
                        "E:/Media/TV Shows/Show (2020)/Season 00/Show (2020) - s00e01 - Ep1.mkv",
                        "E:/Media/TV Shows/Show (2020)/Season 00/Show (2020) - s00e02 - Ep2.mkv",
                    ],
                    chapter_labels=["s00e01 - Ep1", "s00e02 - Ep2"],
                    confidence="high",
                    original_label="Disc 3: Diaries (featurettes)",
                ),
            ],
        )
        actions = execute_plan(op, dry_run=True)
        text = "\n".join(actions)
        assert "WOULD SPLIT" in text
        assert "/rip/diaries.mkv" in text
        assert "CHAPTER ->" in text
        assert "s00e01" in text
        assert "s00e02" in text


class TestChapterToMissingSplits:
    """Test converting matched files to splits when chapters match missing entries."""

    def test_basic_movie_split(self):
        """File matched as Trailer 3, but chapters match Teaser + Trailer 2."""
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="t12.mkv",
                    file_duration_seconds=194,
                    matched_label="Disc 3: Trailer 3",
                    matched_runtime_seconds=191,
                    delta_seconds=3,
                    confidence="high",
                ),
            ],
            missing=["Disc 3: Teaser", "Disc 3: Trailer 2"],
        )
        plan = PlannedMovie(
            canonical_title="Oppenheimer", year=2023,
            runtime="3h", runtime_seconds=10860,
        )
        disc_targets = [
            ("Disc 3: Teaser", 71, 3),
            ("Disc 3: Trailer 2", 124, 3),
            ("Disc 3: Trailer 3", 191, 3),
        ]
        scanned = {
            "t12.mkv": ScannedFile(
                name="t12.mkv", path="/rip/t12.mkv",
                duration_seconds=194, chapter_count=2,
                chapter_durations=[70, 124],
            ),
        }
        op = build_organize_plan(
            result, plan, Path("E:/Media"),
            scanned_files=scanned, disc_targets=disc_targets,
        )
        assert len(op.moves) == 0
        assert len(op.splits) == 1
        split = op.splits[0]
        assert split.source == "/rip/t12.mkv"
        assert len(split.chapter_destinations) == 2
        assert "Teaser.mkv" in split.chapter_destinations[0]
        assert "Trailer 2.mkv" in split.chapter_destinations[1]
        # Original match released back to missing
        assert "Disc 3: Trailer 3" in op.missing
        # Consumed entries removed from missing
        assert "Disc 3: Teaser" not in op.missing
        assert "Disc 3: Trailer 2" not in op.missing

    def test_cascading_splits(self):
        """Converting file A releases a label that enables file B's split."""
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="t12.mkv",
                    file_duration_seconds=194,
                    matched_label="Disc 3: Trailer 3",
                    matched_runtime_seconds=191,
                    delta_seconds=3,
                    confidence="high",
                ),
                MatchCandidate(
                    file_name="t13.mkv",
                    file_duration_seconds=497,
                    matched_label="Disc 3: Other Feature",
                    matched_runtime_seconds=501,
                    delta_seconds=4,
                    confidence="high",
                ),
            ],
            missing=[
                "Disc 3: Teaser",
                "Disc 3: Trailer 2",
                "Disc 3: Opening Look",
            ],
        )
        plan = PlannedMovie(
            canonical_title="Oppenheimer", year=2023,
            runtime="3h", runtime_seconds=10860,
        )
        disc_targets = [
            ("Disc 3: Teaser", 71, 3),
            ("Disc 3: Trailer 2", 124, 3),
            ("Disc 3: Trailer 3", 191, 3),
            ("Disc 3: Opening Look", 307, 3),
            ("Disc 3: Other Feature", 501, 3),
        ]
        scanned = {
            "t12.mkv": ScannedFile(
                name="t12.mkv", path="/rip/t12.mkv",
                duration_seconds=194, chapter_count=2,
                chapter_durations=[70, 124],
            ),
            "t13.mkv": ScannedFile(
                name="t13.mkv", path="/rip/t13.mkv",
                duration_seconds=497, chapter_count=2,
                chapter_durations=[191, 307],
            ),
        }
        op = build_organize_plan(
            result, plan, Path("E:/Media"),
            scanned_files=scanned, disc_targets=disc_targets,
        )
        assert len(op.moves) == 0
        assert len(op.splits) == 2
        # t12 split: Teaser + Trailer 2
        labels_0 = op.splits[0].chapter_labels
        assert "Disc 3: Teaser" in labels_0
        assert "Disc 3: Trailer 2" in labels_0
        # t13 split: Trailer 3 (released by t12) + Opening Look
        labels_1 = op.splits[1].chapter_labels
        assert "Disc 3: Trailer 3" in labels_1
        assert "Disc 3: Opening Look" in labels_1
        # Both original labels released back
        assert "Disc 3: Trailer 3" not in op.missing  # consumed by t13
        assert "Disc 3: Other Feature" in op.missing

    def test_no_split_partial_chapter_match(self):
        """File with 3 chapters but only 2 match missing entries stays as move."""
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="t05.mkv",
                    file_duration_seconds=300,
                    matched_label="Disc 1: Some Feature",
                    matched_runtime_seconds=300,
                    delta_seconds=0,
                    confidence="high",
                ),
            ],
            missing=["Disc 1: Item A", "Disc 1: Item B"],
        )
        plan = PlannedMovie(
            canonical_title="Test", year=2023,
            runtime="2h", runtime_seconds=7200,
        )
        disc_targets = [
            ("Disc 1: Item A", 100, 1),
            ("Disc 1: Item B", 100, 1),
            ("Disc 1: Some Feature", 300, 1),
        ]
        scanned = {
            "t05.mkv": ScannedFile(
                name="t05.mkv", path="/rip/t05.mkv",
                duration_seconds=300, chapter_count=3,
                chapter_durations=[100, 100, 100],  # 3 chapters, only 2 missing
            ),
        }
        op = build_organize_plan(
            result, plan, Path("E:/Media"),
            scanned_files=scanned, disc_targets=disc_targets,
        )
        assert len(op.moves) == 1
        assert len(op.splits) == 0

    def test_no_split_without_disc_targets(self):
        """Without disc_targets, no chapter-to-missing detection occurs."""
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="t12.mkv",
                    file_duration_seconds=194,
                    matched_label="Disc 3: Trailer 3",
                    matched_runtime_seconds=191,
                    delta_seconds=3,
                    confidence="high",
                ),
            ],
            missing=["Disc 3: Teaser", "Disc 3: Trailer 2"],
        )
        plan = PlannedMovie(
            canonical_title="Oppenheimer", year=2023,
            runtime="3h", runtime_seconds=10860,
        )
        scanned = {
            "t12.mkv": ScannedFile(
                name="t12.mkv", path="/rip/t12.mkv",
                duration_seconds=194, chapter_count=2,
                chapter_durations=[70, 124],
            ),
        }
        # No disc_targets passed
        op = build_organize_plan(
            result, plan, Path("E:/Media"), scanned_files=scanned,
        )
        assert len(op.moves) == 1
        assert len(op.splits) == 0

    def test_no_split_single_chapter(self):
        """Single chapter file is not a split candidate."""
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="t01.mkv",
                    file_duration_seconds=120,
                    matched_label="Disc 1: Trailer",
                    matched_runtime_seconds=120,
                    delta_seconds=0,
                    confidence="high",
                ),
            ],
            missing=["Disc 1: Teaser"],
        )
        plan = PlannedMovie(
            canonical_title="Test", year=2023,
            runtime="2h", runtime_seconds=7200,
        )
        disc_targets = [
            ("Disc 1: Teaser", 120, 1),
            ("Disc 1: Trailer", 120, 1),
        ]
        scanned = {
            "t01.mkv": ScannedFile(
                name="t01.mkv", path="/rip/t01.mkv",
                duration_seconds=120, chapter_count=1,
                chapter_durations=[120],
            ),
        }
        op = build_organize_plan(
            result, plan, Path("E:/Media"),
            scanned_files=scanned, disc_targets=disc_targets,
        )
        assert len(op.moves) == 1
        assert len(op.splits) == 0

    def test_tv_show_chapter_to_missing(self):
        """Chapter-to-missing works for TV show extras too."""
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="extras.mkv",
                    file_duration_seconds=600,
                    matched_label="Disc 2: Wrong Extra (featurette)",
                    matched_runtime_seconds=590,
                    delta_seconds=10,
                    confidence="high",
                ),
            ],
            missing=["Disc 2: Extra A (featurette)", "Disc 2: Extra B (featurette)"],
        )
        plan = PlannedShow(
            canonical_title="Test Show", year=2023,
            seasons=[
                PlannedSeason(
                    season_number=1,
                    episodes=[
                        PlannedEpisode(
                            season_number=1, episode_number=1,
                            title="Pilot", runtime="45m",
                        ),
                    ],
                ),
            ],
        )
        disc_targets = [
            ("Disc 2: Extra A (featurette)", 290, 2),
            ("Disc 2: Extra B (featurette)", 310, 2),
            ("Disc 2: Wrong Extra (featurette)", 590, 2),
        ]
        scanned = {
            "extras.mkv": ScannedFile(
                name="extras.mkv", path="/rip/extras.mkv",
                duration_seconds=600, chapter_count=2,
                chapter_durations=[290, 310],
            ),
        }
        op = build_organize_plan(
            result, plan, Path("E:/Media"),
            scanned_files=scanned, disc_targets=disc_targets,
        )
        assert len(op.moves) == 0
        assert len(op.splits) == 1
        split = op.splits[0]
        assert "Featurettes" in split.chapter_destinations[0]
        assert "Extra A.mkv" in split.chapter_destinations[0]
        assert "Extra B.mkv" in split.chapter_destinations[1]


class TestUnmatchedExtrasPolicy:
    """Test --unmatched extras routing to Other/ folder."""

    def test_movie_unmatched_to_extras(self):
        """Unmatched movie files >= 60s route to Other/ folder."""
        result = OrganizeResult(
            matched=[],
            unmatched=[
                ScannedFile(name="bonus.mkv", path="/rip/bonus.mkv", duration_seconds=3097),
                ScannedFile(name="trailer.mkv", path="/rip/trailer.mkv", duration_seconds=120),
            ],
        )
        plan = PlannedMovie(
            canonical_title="Oppenheimer", year=2023,
            runtime="3h", runtime_seconds=10860,
        )
        op = build_organize_plan(
            result, plan, Path("E:/Media"), unmatched_policy="extras",
        )
        assert len(op.moves) == 2
        assert len(op.unmatched) == 0
        assert "Other" in op.moves[0].destination
        assert "Extra 1.mkv" in op.moves[0].destination
        assert "Oppenheimer (2023)" in op.moves[0].destination
        assert "Extra 2.mkv" in op.moves[1].destination
        assert "Other" in op.moves[1].destination
        assert op.moves[0].confidence == "none"

    def test_tv_unmatched_to_extras(self):
        """Unmatched TV files >= 60s route to show-level Other/ folder."""
        result = OrganizeResult(
            matched=[],
            unmatched=[
                ScannedFile(name="INTO THE BLUE_t00.mkv", path="/rip/itb.mkv", duration_seconds=3097),
            ],
        )
        plan = PlannedShow(
            canonical_title="Blue Planet II", year=2017,
        )
        op = build_organize_plan(
            result, plan, Path("E:/Media"), unmatched_policy="extras",
        )
        assert len(op.moves) == 1
        assert len(op.unmatched) == 0
        assert "Other" in op.moves[0].destination
        assert "Blue Planet II (2017)" in op.moves[0].destination
        assert "Extra 1.mkv" in op.moves[0].destination

    def test_short_files_excluded(self):
        """Files < 60s stay unmatched even with extras policy."""
        result = OrganizeResult(
            matched=[],
            unmatched=[
                ScannedFile(name="menu.mkv", path="/rip/menu.mkv", duration_seconds=30),
                ScannedFile(name="bumper.mkv", path="/rip/bumper.mkv", duration_seconds=5),
            ],
        )
        plan = PlannedMovie(
            canonical_title="Test", year=2023,
            runtime="2h", runtime_seconds=7200,
        )
        op = build_organize_plan(
            result, plan, Path("E:/Media"), unmatched_policy="extras",
        )
        assert len(op.moves) == 0
        assert len(op.unmatched) == 2

    def test_ignore_policy_unchanged(self):
        """Default ignore policy leaves unmatched files alone."""
        result = OrganizeResult(
            matched=[],
            unmatched=[
                ScannedFile(name="bonus.mkv", path="/rip/bonus.mkv", duration_seconds=3097),
            ],
        )
        plan = PlannedMovie(
            canonical_title="Test", year=2023,
            runtime="2h", runtime_seconds=7200,
        )
        op = build_organize_plan(
            result, plan, Path("E:/Media"), unmatched_policy="ignore",
        )
        assert len(op.moves) == 0
        assert len(op.unmatched) == 1
