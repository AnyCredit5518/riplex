"""Tests for the matcher module."""

from riplex.matcher import (
    collect_disc_targets,
    format_match_report,
    map_folders_to_discs,
    match_discs,
    match_files,
    parse_duration,
)
from riplex.models import (
    MatchCandidate,
    PlannedDisc,
    PlannedEpisode,
    PlannedExtra,
    PlannedMovie,
    PlannedSeason,
    PlannedShow,
    ScannedDisc,
    ScannedFile,
)


class TestParseDuration:
    def test_minutes_seconds(self):
        assert parse_duration("48m 12s") == 48 * 60 + 12

    def test_minutes_only(self):
        assert parse_duration("48m") == 48 * 60

    def test_hours_minutes(self):
        assert parse_duration("1h 2m") == 3720

    def test_hours_minutes_seconds(self):
        assert parse_duration("1h 2m 30s") == 3750

    def test_colon_mmss(self):
        assert parse_duration("48:12") == 48 * 60 + 12

    def test_colon_hmmss(self):
        assert parse_duration("1:02:30") == 3750

    def test_raw_seconds(self):
        assert parse_duration("3024") == 3024

    def test_empty(self):
        assert parse_duration("") == 0

    def test_compact_no_spaces(self):
        assert parse_duration("48m12s") == 48 * 60 + 12


class TestMatchFiles:
    def test_matches_episodes_by_runtime(self):
        show = PlannedShow(
            canonical_title="Test Show",
            year=2023,
            seasons=[
                PlannedSeason(
                    season_number=1,
                    episodes=[
                        PlannedEpisode(
                            season_number=1,
                            episode_number=1,
                            title="Pilot",
                            runtime="48m",
                            runtime_seconds=2880,
                        ),
                        PlannedEpisode(
                            season_number=1,
                            episode_number=2,
                            title="Second",
                            runtime="44m",
                            runtime_seconds=2640,
                        ),
                    ],
                )
            ],
        )

        ripped = [
            ("title_t00.mkv", 2878),  # ~48m, close to ep1
            ("title_t01.mkv", 2645),  # ~44m, close to ep2
        ]

        candidates = match_files(ripped, show)
        assert len(candidates) == 2
        assert "Pilot" in candidates[0].matched_label
        assert "Second" in candidates[1].matched_label
        assert candidates[0].confidence == "high"
        assert candidates[1].confidence == "high"

    def test_matches_movie(self):
        movie = PlannedMovie(
            canonical_title="Oppenheimer",
            year=2023,
            runtime="3h 1m",
            runtime_seconds=10860,
            main_file="Oppenheimer (2023).mkv",
        )

        ripped = [("title_t00.mkv", 10850)]
        candidates = match_files(ripped, movie)
        assert len(candidates) == 1
        assert "Oppenheimer" in candidates[0].matched_label
        assert candidates[0].confidence == "high"

    def test_format_report(self):
        show = PlannedShow(
            canonical_title="Show",
            year=2023,
            seasons=[
                PlannedSeason(
                    season_number=1,
                    episodes=[
                        PlannedEpisode(
                            season_number=1,
                            episode_number=1,
                            title="Ep1",
                            runtime="30m",
                            runtime_seconds=1800,
                        ),
                    ],
                )
            ],
        )
        ripped = [("file.mkv", 1810)]
        candidates = match_files(ripped, show)
        report = format_match_report(candidates)
        assert "file.mkv" in report
        assert "Ep1" in report


class TestMatchDiscs:
    def test_oppenheimer_like(self):
        """Movie disc + special features disc."""
        movie = PlannedMovie(
            canonical_title="Oppenheimer",
            year=2023,
            runtime="3h 0m",
            runtime_seconds=10822,
            main_file="Oppenheimer (2023).mkv",
        )
        discs = [
            PlannedDisc(number=1, disc_format="Blu-ray 4K", is_film=True),
            PlannedDisc(
                number=3,
                disc_format="Blu-ray",
                extras=[
                    PlannedExtra(title="To End All War", runtime_seconds=5238, feature_type="documentary"),
                    PlannedExtra(title="Innovations in Film", runtime_seconds=501, feature_type="featurette"),
                ],
            ),
        ]
        scanned = [
            ScannedDisc(
                folder_name="Oppenheimer",
                files=[
                    ScannedFile(name="Oppenheimer_t00.mkv", path="x", duration_seconds=325),
                    ScannedFile(name="Oppenheimer_t01.mkv", path="x", duration_seconds=10822),
                ],
            ),
            ScannedDisc(
                folder_name="Special Features",
                files=[
                    ScannedFile(name="SF_t02.mkv", path="x", duration_seconds=5240),
                    ScannedFile(name="SF_t03.mkv", path="x", duration_seconds=498),
                ],
            ),
        ]

        result = match_discs(scanned, discs, movie)

        # Should match the main film and both extras
        assert len(result.matched) == 3
        labels = {c.matched_label for c in result.matched}
        assert "Oppenheimer (movie)" in labels
        assert any("To End All War" in l for l in labels)
        assert any("Innovations" in l for l in labels)

        # The 325s file doesn't match anything well
        assert len(result.unmatched) == 1
        assert result.unmatched[0].name == "Oppenheimer_t00.mkv"

    def test_tv_episodes(self):
        """TV show with episode groups on disc."""
        discs = [
            PlannedDisc(
                number=1,
                disc_format="Blu-ray 4K",
                episodes=[
                    PlannedEpisode(season_number=0, episode_number=1, title="Coasts", runtime="", runtime_seconds=3141),
                    PlannedEpisode(season_number=0, episode_number=2, title="Ocean", runtime="", runtime_seconds=3150),
                ],
            ),
        ]
        scanned = [
            ScannedDisc(
                folder_name="Disc 1",
                files=[
                    ScannedFile(name="d1_t00.mkv", path="x", duration_seconds=3140),
                    ScannedFile(name="d1_t01.mkv", path="x", duration_seconds=3155),
                ],
            ),
        ]

        result = match_discs(scanned, discs)
        assert len(result.matched) == 2
        assert result.matched[0].confidence == "high"
        assert result.unmatched == []
        assert result.missing == []

    def test_missing_content(self):
        """More planned content than scanned files."""
        discs = [
            PlannedDisc(
                number=1,
                disc_format="Blu-ray",
                extras=[
                    PlannedExtra(title="Feature A", runtime_seconds=600),
                    PlannedExtra(title="Feature B", runtime_seconds=300),
                ],
            ),
        ]
        scanned = [
            ScannedDisc(
                folder_name="Disc",
                files=[
                    ScannedFile(name="t00.mkv", path="x", duration_seconds=605),
                ],
            ),
        ]

        result = match_discs(scanned, discs)
        assert len(result.matched) == 1
        assert len(result.missing) == 1
        assert "Feature B" in result.missing[0]

    def test_greedy_optimal_pairing(self):
        """Greedy matching pairs files to closest targets globally."""
        discs = [
            PlannedDisc(
                number=1,
                disc_format="Blu-ray",
                extras=[
                    PlannedExtra(title="Short", runtime_seconds=300),
                    PlannedExtra(title="Long", runtime_seconds=3600),
                ],
            ),
        ]
        scanned = [
            ScannedDisc(
                folder_name="Root",
                files=[
                    ScannedFile(name="a.mkv", path="x", duration_seconds=3590),
                    ScannedFile(name="b.mkv", path="x", duration_seconds=310),
                ],
            ),
        ]

        result = match_discs(scanned, discs)
        assert len(result.matched) == 2
        # a.mkv (3590s) should match Long (3600s)
        a_match = next(c for c in result.matched if c.file_name == "a.mkv")
        assert "Long" in a_match.matched_label
        # b.mkv (310s) should match Short (300s)
        b_match = next(c for c in result.matched if c.file_name == "b.mkv")
        assert "Short" in b_match.matched_label


# ---------------------------------------------------------------------------
# Folder-to-disc mapping
# ---------------------------------------------------------------------------


class TestMapFoldersToDiscs:
    def test_explicit_disc_number(self):
        """Folder name 'Planet Earth III - Disc 2' maps to disc 2."""
        scanned = [
            ScannedDisc(folder_name="Planet Earth III - Disc 1", files=[]),
            ScannedDisc(folder_name="Planet Earth III - Disc 2", files=[]),
        ]
        discs = [
            PlannedDisc(number=1, disc_format="Blu-ray 4K"),
            PlannedDisc(number=2, disc_format="Blu-ray 4K"),
        ]
        mapping = map_folders_to_discs(scanned, discs)
        assert mapping["Planet Earth III - Disc 1"] == 1
        assert mapping["Planet Earth III - Disc 2"] == 2

    def test_short_d_prefix_disc_number(self):
        """Folder name like 'BLUE PLANET II D1' maps via the D# pattern."""
        scanned = [
            ScannedDisc(folder_name="BLUE PLANET II D1", files=[]),
            ScannedDisc(folder_name="BLUE PLANET II D2", files=[]),
        ]
        discs = [
            PlannedDisc(number=1, disc_format="Blu-ray"),
            PlannedDisc(number=2, disc_format="Blu-ray"),
        ]
        mapping = map_folders_to_discs(scanned, discs)
        assert mapping["BLUE PLANET II D1"] == 1
        assert mapping["BLUE PLANET II D2"] == 2

    def test_film_disc_by_runtime(self):
        """Root folder with a file matching movie runtime maps to the film disc."""
        movie = PlannedMovie(
            canonical_title="Oppenheimer",
            year=2023,
            runtime="3h 0m",
            runtime_seconds=10822,
        )
        scanned = [
            ScannedDisc(
                folder_name="Oppenheimer",
                files=[
                    ScannedFile(name="t00.mkv", path="x", duration_seconds=325),
                    ScannedFile(name="t01.mkv", path="x", duration_seconds=10822),
                ],
            ),
            ScannedDisc(
                folder_name="Special Features",
                files=[
                    ScannedFile(name="sf_t02.mkv", path="x", duration_seconds=5238),
                ],
            ),
        ]
        discs = [
            PlannedDisc(number=1, disc_format="Blu-ray 4K", is_film=True),
            PlannedDisc(
                number=3,
                disc_format="Blu-ray",
                extras=[PlannedExtra(title="Doc", runtime_seconds=5238)],
            ),
        ]
        mapping = map_folders_to_discs(scanned, discs, movie)
        assert mapping["Oppenheimer"] == 1
        assert mapping["Special Features"] == 3

    def test_bonus_folder_name(self):
        """'Special Features' maps to the non-film disc with most extras."""
        scanned = [
            ScannedDisc(folder_name="Main", files=[
                ScannedFile(name="m.mkv", path="x", duration_seconds=7200),
            ]),
            ScannedDisc(folder_name="Special Features", files=[]),
        ]
        movie = PlannedMovie(
            canonical_title="Movie", year=2023, runtime="2h", runtime_seconds=7200,
        )
        discs = [
            PlannedDisc(number=1, disc_format="Blu-ray", is_film=True),
            PlannedDisc(
                number=2, disc_format="Blu-ray",
                extras=[PlannedExtra(title="A", runtime_seconds=300)],
            ),
        ]
        mapping = map_folders_to_discs(scanned, discs, movie)
        assert mapping["Main"] == 1
        assert mapping["Special Features"] == 2

    def test_unmapped_folder_is_none(self):
        """Folders that don't match any heuristic get None."""
        scanned = [
            ScannedDisc(folder_name="Random", files=[
                ScannedFile(name="a.mkv", path="x", duration_seconds=100),
            ]),
        ]
        discs = [PlannedDisc(number=1, disc_format="Blu-ray 4K", is_film=True)]
        movie = PlannedMovie(
            canonical_title="Film", year=2023, runtime="2h", runtime_seconds=7200,
        )
        mapping = map_folders_to_discs(scanned, discs, movie)
        assert mapping["Random"] is None

    def test_disc_number_not_in_planned(self):
        """Explicit disc number that doesn't exist in planned discs is ignored."""
        scanned = [
            ScannedDisc(folder_name="Disc 5", files=[]),
        ]
        discs = [PlannedDisc(number=1, disc_format="Blu-ray")]
        mapping = map_folders_to_discs(scanned, discs)
        assert mapping["Disc 5"] is None


class TestDiscConstrainedMatching:
    def test_film_disc_files_dont_steal_bonus_targets(self):
        """Files on the film disc can't match extras from the bonus disc."""
        movie = PlannedMovie(
            canonical_title="Oppenheimer",
            year=2023,
            runtime="3h 0m",
            runtime_seconds=10822,
        )
        discs = [
            PlannedDisc(number=1, disc_format="Blu-ray 4K", is_film=True),
            PlannedDisc(
                number=3,
                disc_format="Blu-ray",
                extras=[
                    PlannedExtra(title="Opening Look", runtime_seconds=307),
                ],
            ),
        ]
        scanned = [
            ScannedDisc(
                folder_name="Oppenheimer",
                files=[
                    ScannedFile(name="t01.mkv", path="x", duration_seconds=10822),
                    ScannedFile(name="t02.mkv", path="x", duration_seconds=307),
                ],
            ),
            ScannedDisc(
                folder_name="Special Features",
                files=[
                    ScannedFile(name="sf_t05.mkv", path="x", duration_seconds=310),
                ],
            ),
        ]
        result = match_discs(scanned, discs, movie)

        # t01.mkv should match the movie
        movie_match = next(c for c in result.matched if c.file_name == "t01.mkv")
        assert "movie" in movie_match.matched_label

        # t02.mkv (on film disc 1) should NOT match "Opening Look" (on disc 3)
        # Instead it should be unmatched
        t02_matched = [c for c in result.matched if c.file_name == "t02.mkv"]
        assert len(t02_matched) == 0

        # sf_t05.mkv (on special features disc 3) should match Opening Look
        sf_match = next(c for c in result.matched if c.file_name == "sf_t05.mkv")
        assert "Opening Look" in sf_match.matched_label

        assert any(f.name == "t02.mkv" for f in result.unmatched)

    def test_unmapped_folder_uses_global_fallback(self):
        """Files in unmapped folders can match any target."""
        discs = [
            PlannedDisc(
                number=1,
                disc_format="Blu-ray",
                extras=[PlannedExtra(title="Feature A", runtime_seconds=600)],
            ),
        ]
        scanned = [
            ScannedDisc(
                folder_name="Unknown",
                files=[
                    ScannedFile(name="a.mkv", path="x", duration_seconds=605),
                ],
            ),
        ]
        result = match_discs(scanned, discs)
        assert len(result.matched) == 1
        assert "Feature A" in result.matched[0].matched_label


class TestPlayAllFiltering:
    """Play-all targets are excluded when individual parts exist on the disc."""

    def test_play_all_filtered_when_parts_exist(self):
        """'Episodes (with Play All)' is excluded when individual episodes exist."""
        discs = [
            PlannedDisc(
                number=1,
                disc_format="Blu-ray 4K",
                extras=[
                    PlannedExtra(title="Episodes (with Play All)", runtime_seconds=9340),
                    PlannedExtra(title="One Ocean", runtime_seconds=3075),
                    PlannedExtra(title="The Deep", runtime_seconds=3211),
                ],
            ),
        ]
        targets = collect_disc_targets(discs)
        labels = [t[0] for t in targets]
        assert not any("Play All" in l for l in labels)
        assert any("One Ocean" in l for l in labels)
        assert any("The Deep" in l for l in labels)

    def test_play_all_kept_when_no_other_content(self):
        """Play-all is kept as target when no individual parts exist."""
        discs = [
            PlannedDisc(
                number=1,
                disc_format="Blu-ray",
                extras=[
                    PlannedExtra(title="Episodes (with Play All)", runtime_seconds=6000),
                ],
            ),
        ]
        targets = collect_disc_targets(discs)
        assert len(targets) == 1
        assert "Play All" in targets[0][0]

    def test_play_all_filtered_with_episodes(self):
        """Play-all is filtered when disc has episodes (from children)."""
        discs = [
            PlannedDisc(
                number=1,
                disc_format="Blu-ray",
                episodes=[
                    PlannedEpisode(season_number=1, episode_number=1, title="Ep1",
                                   runtime="", runtime_seconds=3000),
                ],
                extras=[
                    PlannedExtra(title="Episodes (with Play All)", runtime_seconds=6000),
                ],
            ),
        ]
        targets = collect_disc_targets(discs)
        labels = [t[0] for t in targets]
        assert any("Ep1" in l for l in labels)
        assert not any("Play All" in l for l in labels)


class TestMaxDeltaThreshold:
    """Files beyond the max delta threshold become unmatched."""

    def test_large_delta_rejected(self):
        """A file 3000s away from the only target is not matched."""
        discs = [
            PlannedDisc(
                number=1,
                disc_format="Blu-ray",
                extras=[
                    PlannedExtra(title="Feature", runtime_seconds=6000),
                ],
            ),
        ]
        scanned = [
            ScannedDisc(
                folder_name="Disc 1",
                files=[
                    ScannedFile(name="a.mkv", path="x", duration_seconds=3000),
                ],
            ),
        ]
        result = match_discs(scanned, discs)
        # delta=3000 > 300 max, so file should be unmatched
        assert len(result.matched) == 0
        assert len(result.unmatched) == 1

    def test_within_threshold_still_matches(self):
        """A file 200s away from the target still matches (under 300s)."""
        discs = [
            PlannedDisc(
                number=1,
                disc_format="Blu-ray",
                extras=[
                    PlannedExtra(title="Feature", runtime_seconds=3000),
                ],
            ),
        ]
        scanned = [
            ScannedDisc(
                folder_name="Disc 1",
                files=[
                    ScannedFile(name="a.mkv", path="x", duration_seconds=3200),
                ],
            ),
        ]
        result = match_discs(scanned, discs)
        assert len(result.matched) == 1
        assert result.matched[0].confidence == "low"

    def test_blue_planet_ii_scenario(self):
        """INTO THE BLUE files rejected by max delta and play-all filter."""
        discs = [
            PlannedDisc(
                number=1,
                disc_format="Blu-ray 4K",
                extras=[
                    PlannedExtra(title="Episodes (with Play All)", runtime_seconds=9340),
                    PlannedExtra(title="One Ocean", runtime_seconds=3075),
                    PlannedExtra(title="The Deep", runtime_seconds=3211),
                ],
            ),
            PlannedDisc(
                number=2,
                disc_format="Blu-ray 4K",
                extras=[
                    PlannedExtra(title="Episodes (with Play All)", runtime_seconds=6312),
                    PlannedExtra(title="Big Blue", runtime_seconds=3119),
                    PlannedExtra(title="Green Seas", runtime_seconds=3192),
                ],
            ),
        ]
        scanned = [
            ScannedDisc(
                folder_name="D1",
                files=[
                    ScannedFile(name="d1_t00.mkv", path="x", duration_seconds=3075),
                    ScannedFile(name="d1_t01.mkv", path="x", duration_seconds=3211),
                ],
            ),
            ScannedDisc(
                folder_name="D2",
                files=[
                    ScannedFile(name="d2_t00.mkv", path="x", duration_seconds=3119),
                    ScannedFile(name="d2_t01.mkv", path="x", duration_seconds=3192),
                ],
            ),
            ScannedDisc(
                folder_name="INTO THE BLUE",
                files=[
                    ScannedFile(name="itb_t00.mkv", path="x", duration_seconds=3097),
                    ScannedFile(name="itb_t01.mkv", path="x", duration_seconds=120),
                ],
            ),
        ]
        result = match_discs(scanned, discs)
        # 4 episode files match their targets at high confidence
        assert len(result.matched) == 4
        matched_names = {c.file_name for c in result.matched}
        assert "d1_t00.mkv" in matched_names
        assert "d2_t01.mkv" in matched_names
        # INTO THE BLUE files should be unmatched (play-all targets filtered,
        # no other targets close enough)
        unmatched_names = {f.name for f in result.unmatched}
        assert "itb_t00.mkv" in unmatched_names
        assert "itb_t01.mkv" in unmatched_names
