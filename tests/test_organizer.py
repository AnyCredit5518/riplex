"""Tests for organizer module."""

from pathlib import Path

from riplex.models import (
    MatchCandidate,
    OrganizeResult,
    PlannedEpisode,
    PlannedMovie,
    PlannedSeason,
    PlannedShow,
    ScannedFile,
)
from riplex.organizer import OrganizePlan, SplitMove, build_organize_plan, execute_plan, _infer_extras_folder, _extras_folder


class TestExtrasFolder:
    def test_exact_trailer(self):
        assert _extras_folder("trailer") == "Trailers"

    def test_exact_trailers(self):
        assert _extras_folder("Trailers") == "Trailers"

    def test_compound_trailer(self):
        assert _extras_folder("4K remastered trailer") == "Trailers"

    def test_theatrical_trailer(self):
        assert _extras_folder("theatrical trailer") == "Trailers"

    def test_exact_documentary(self):
        assert _extras_folder("documentary") == "Featurettes"

    def test_documentaries(self):
        assert _extras_folder("documentaries") == "Featurettes"

    def test_documentary_trailing_colon(self):
        assert _extras_folder("documentary:") == "Featurettes"

    def test_archival_featurette(self):
        assert _extras_folder("archival featurette") == "Featurettes"

    def test_short_feature(self):
        assert _extras_folder("short feature") == "Shorts"

    def test_exact_short(self):
        assert _extras_folder("short") == "Shorts"

    def test_behind_the_scenes_montage(self):
        assert _extras_folder("behind-the-scenes montage") == "Behind The Scenes"

    def test_interactive_feature_is_other(self):
        assert _extras_folder("interactive feature") == "Other"

    def test_empty_is_other(self):
        assert _extras_folder("") == "Other"

    def test_none_like_is_other(self):
        assert _extras_folder("Art Gallery") == "Other"


class TestInferExtrasFolder:
    def test_trailer(self):
        assert _infer_extras_folder("Trailer 1") == "Trailers"

    def test_teaser(self):
        assert _infer_extras_folder("Teaser") == "Trailers"

    def test_promo(self):
        assert _infer_extras_folder("Promo clip") == "Trailers"

    def test_tv_spot(self):
        assert _infer_extras_folder("TV Spot 3") == "Trailers"

    def test_promoting_is_featurette(self):
        assert _infer_extras_folder("Promoting Dystopia: Rendering the Poster Art") == "Featurettes"

    def test_promotional_is_featurette(self):
        assert _infer_extras_folder("Promotional featurette") == "Featurettes"

    def test_regular_featurette(self):
        assert _infer_extras_folder("Making Of") == "Featurettes"

    def test_quoted_trailer(self):
        assert _infer_extras_folder('"Trailer"') == "Trailers"


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

    def test_movie_with_edition_from_classification(self):
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="KK_t00.mkv",
                    file_duration_seconds=11236,
                    matched_label="King Kong (movie)",
                    matched_runtime_seconds=11280,
                    delta_seconds=44,
                    confidence="high",
                    classification="Theatrical Cut (4K)",
                ),
                MatchCandidate(
                    file_name="KK_t02.mkv",
                    file_duration_seconds=12008,
                    matched_label="King Kong (movie)",
                    matched_runtime_seconds=11280,
                    delta_seconds=728,
                    confidence="low",
                    classification="Extended Cut (4K)",
                ),
            ],
        )
        plan = PlannedMovie(
            canonical_title="King Kong",
            year=2005,
            runtime="3h 8m",
            runtime_seconds=11280,
        )
        output = Path("E:/Media")
        op = build_organize_plan(result, plan, output)
        assert len(op.moves) == 2
        assert "{edition-Theatrical Cut}" in op.moves[0].destination
        assert "{edition-Extended Cut}" in op.moves[1].destination
        assert "King Kong (2005)" in op.moves[0].destination
        assert "King Kong (2005)" in op.moves[1].destination

    def test_movie_with_edition_from_disc_label(self):
        """Edition tag extracted from multi-edition disc target label."""
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="KK_t00.mkv",
                    file_duration_seconds=11236,
                    matched_label="Disc 1: Theatrical Cut (movie)",
                    matched_runtime_seconds=11236,
                    delta_seconds=0,
                    confidence="high",
                ),
                MatchCandidate(
                    file_name="KK_t02.mkv",
                    file_duration_seconds=12008,
                    matched_label="Disc 1: Extended Cut (movie)",
                    matched_runtime_seconds=12008,
                    delta_seconds=0,
                    confidence="high",
                ),
            ],
        )
        plan = PlannedMovie(
            canonical_title="King Kong",
            year=2005,
            runtime="3h 7m",
            runtime_seconds=11236,
        )
        output = Path("E:/Media")
        op = build_organize_plan(result, plan, output)
        assert len(op.moves) == 2
        dests = [m.destination for m in op.moves]
        assert any("{edition-Theatrical Cut}" in d for d in dests)
        assert any("{edition-Extended Cut}" in d for d in dests)
        assert all("King Kong (2005)" in d for d in dests)

    def test_movie_with_3d_and_2d_uses_3d_edition_and_base_folder(self):
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="Butterflies_t00.mkv",
                    file_duration_seconds=2653,
                    matched_label="Disc 2: 3D (movie)",
                    matched_runtime_seconds=2653,
                    delta_seconds=0,
                    confidence="medium",
                ),
                MatchCandidate(
                    file_name="Butterflies_t03.mkv",
                    file_duration_seconds=2653,
                    matched_label="Disc 2: 2D (movie)",
                    matched_runtime_seconds=2653,
                    delta_seconds=0,
                    confidence="medium",
                ),
            ],
        )
        plan = PlannedMovie(
            canonical_title="Flight of the Butterflies",
            year=2012,
            runtime="45m",
            runtime_seconds=2700,
        )
        scanned = {
            "Butterflies_t00.mkv": ScannedFile(
                name="Butterflies_t00.mkv", path="/rip/Butterflies_t00.mkv",
                duration_seconds=2653, max_width=1920, max_height=1080,
            ),
            "Butterflies_t03.mkv": ScannedFile(
                name="Butterflies_t03.mkv", path="/rip/Butterflies_t03.mkv",
                duration_seconds=2653, max_width=1920, max_height=1080,
            ),
        }

        op = build_organize_plan(result, plan, Path("E:/Media"), scanned_files=scanned)

        assert len(op.moves) == 2
        dests = [m.destination for m in op.moves]
        assert any(
            "Flight of the Butterflies (2012) {edition-3D}"
            in d and "Flight of the Butterflies (2012) - 1080p {edition-3D}.mkv" in d
            for d in dests
        )
        assert any(
            "Flight of the Butterflies (2012) {edition-" not in d
            and "Flight of the Butterflies (2012) - 1080p.mkv" in d
            for d in dests
        )

    def test_movie_with_only_3d_uses_edition_folder(self):
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="Butterflies_3d.mkv",
                    file_duration_seconds=2653,
                    matched_label="Disc 2: 3D (movie)",
                    matched_runtime_seconds=2653,
                    delta_seconds=0,
                    confidence="medium",
                ),
            ],
        )
        plan = PlannedMovie(
            canonical_title="Flight of the Butterflies",
            year=2012,
            runtime="45m",
            runtime_seconds=2700,
        )
        scanned = {
            "Butterflies_3d.mkv": ScannedFile(
                name="Butterflies_3d.mkv", path="/rip/Butterflies_3d.mkv",
                duration_seconds=2653, max_width=1920, max_height=1080,
            ),
        }

        op = build_organize_plan(result, plan, Path("E:/Media"), scanned_files=scanned)

        assert len(op.moves) == 1
        dest = op.moves[0].destination
        assert "Flight of the Butterflies (2012) {edition-3D}" in dest
        assert "Flight of the Butterflies (2012) - 1080p {edition-3D}.mkv" in dest

    def test_movie_with_4k_1080p_and_3d_versions(self):
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="Butterflies_4k.mkv",
                    file_duration_seconds=2653,
                    matched_label="Flight of the Butterflies (movie)",
                    matched_runtime_seconds=2700,
                    delta_seconds=47,
                    confidence="medium",
                    classification="MAIN FILM (4K)",
                ),
                MatchCandidate(
                    file_name="Butterflies_2d.mkv",
                    file_duration_seconds=2653,
                    matched_label="Disc 1: 2D (movie)",
                    matched_runtime_seconds=2653,
                    delta_seconds=0,
                    confidence="medium",
                ),
                MatchCandidate(
                    file_name="Butterflies_3d.mkv",
                    file_duration_seconds=2653,
                    matched_label="Disc 2: 3D (movie)",
                    matched_runtime_seconds=2653,
                    delta_seconds=0,
                    confidence="medium",
                ),
            ],
        )
        plan = PlannedMovie(
            canonical_title="Flight of the Butterflies",
            year=2012,
            runtime="45m",
            runtime_seconds=2700,
        )
        scanned = {
            "Butterflies_2d.mkv": ScannedFile(
                name="Butterflies_2d.mkv", path="/rip/Butterflies_2d.mkv",
                duration_seconds=2653, max_width=1920, max_height=1080,
            ),
            "Butterflies_3d.mkv": ScannedFile(
                name="Butterflies_3d.mkv", path="/rip/Butterflies_3d.mkv",
                duration_seconds=2653, max_width=1920, max_height=1080,
            ),
        }

        op = build_organize_plan(result, plan, Path("E:/Media"), scanned_files=scanned)

        assert len(op.moves) == 3
        dests = [m.destination for m in op.moves]
        assert any("Flight of the Butterflies (2012) - 4k.mkv" in d for d in dests)
        assert any(
            "Flight of the Butterflies (2012) {edition-" not in d
            and "Flight of the Butterflies (2012) - 1080p.mkv" in d
            for d in dests
        )
        assert any(
            "Flight of the Butterflies (2012) {edition-3D}"
            in d and "Flight of the Butterflies (2012) - 1080p {edition-3D}.mkv" in d
            for d in dests
        )

    def test_movie_4k_version_suffix_from_classification(self):
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="Butterflies_4k.mkv",
                    file_duration_seconds=2653,
                    matched_label="Flight of the Butterflies (movie)",
                    matched_runtime_seconds=2700,
                    delta_seconds=47,
                    confidence="medium",
                    classification="MAIN FILM (4K)",
                ),
            ],
        )
        plan = PlannedMovie(
            canonical_title="Flight of the Butterflies",
            year=2012,
            runtime="45m",
            runtime_seconds=2700,
        )

        op = build_organize_plan(result, plan, Path("E:/Media"))

        assert len(op.moves) == 1
        assert "Flight of the Butterflies (2012) - 4k.mkv" in op.moves[0].destination

    def test_movie_1080p_version_suffix_from_scan(self):
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="Butterflies_bluray.mkv",
                    file_duration_seconds=2653,
                    matched_label="Flight of the Butterflies (movie)",
                    matched_runtime_seconds=2700,
                    delta_seconds=47,
                    confidence="medium",
                ),
            ],
        )
        plan = PlannedMovie(
            canonical_title="Flight of the Butterflies",
            year=2012,
            runtime="45m",
            runtime_seconds=2700,
        )
        scanned = {
            "Butterflies_bluray.mkv": ScannedFile(
                name="Butterflies_bluray.mkv", path="/rip/Butterflies_bluray.mkv",
                duration_seconds=2653, max_width=1920, max_height=1080,
            ),
        }

        op = build_organize_plan(result, plan, Path("E:/Media"), scanned_files=scanned)

        assert len(op.moves) == 1
        dest = op.moves[0].destination
        assert "Flight of the Butterflies (2012) {edition-" not in dest
        assert "Flight of the Butterflies (2012) - 1080p.mkv" in dest

    def test_movie_no_edition_without_classification(self):
        """No edition tag when classification is empty or has no edition."""
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="Movie_t01.mkv",
                    file_duration_seconds=7200,
                    matched_label="Test Movie (movie)",
                    matched_runtime_seconds=7200,
                    delta_seconds=0,
                    confidence="high",
                    classification="MAIN FILM (4K)",
                ),
            ],
        )
        plan = PlannedMovie(
            canonical_title="Test Movie",
            year=2023,
            runtime="2h",
            runtime_seconds=7200,
        )
        op = build_organize_plan(result, plan, Path("E:/Media"))
        assert len(op.moves) == 1
        assert "{edition-" not in op.moves[0].destination

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

    def test_tv_extra_without_feature_type_suffix_routes_via_classification(self):
        """dvdcompare extra with blank ``feature_type`` still routes.

        Some dvdcompare listings leave ``feature_type`` empty on
        extras (e.g. Psych S3 D1 "Start-up Trailers"), which strips
        the ``(type)`` suffix from the target label so the disc-label
        branch of ``_compute_destination`` can't tell it's an extra.
        Without the classification-prefix fallback the file gets
        dropped as unmatched even though the rip-time classifier
        already tagged it ``[extra] Start-up Trailers``.
        """
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="A1_t11.mkv",
                    file_duration_seconds=267,
                    matched_label="Disc 1: Start-up Trailers",
                    matched_runtime_seconds=267,
                    delta_seconds=0,
                    confidence="high",
                    classification="[extra] Start-up Trailers (1080p)",
                ),
            ],
        )
        plan = PlannedShow(canonical_title="Psych", year=2006)
        output = Path("E:/Media")
        op = build_organize_plan(result, plan, output)
        assert len(op.unmatched) == 0
        assert len(op.moves) == 1
        dest = op.moves[0].destination
        # "extra" maps to "Other" -> title-based inference kicks in;
        # "Start-up Trailers" doesn't match the trailer pattern
        # (leading "trailer"/"teaser"/"tv spot"/"promo") so it lands
        # in Featurettes.
        assert "Featurettes" in dest
        assert dest.endswith("Start-up Trailers.mkv")

    def test_tv_extra_with_trailer_classification_routes_to_trailers(self):
        """Rip-time ``[trailer]`` prefix maps cleanly to Trailers/."""
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="d1_t01.mkv",
                    file_duration_seconds=120,
                    matched_label="Disc 1: Teaser Reel",
                    matched_runtime_seconds=120,
                    delta_seconds=0,
                    confidence="high",
                    classification="[trailer] Teaser Reel (1080p)",
                ),
            ],
        )
        plan = PlannedShow(canonical_title="Psych", year=2006)
        output = Path("E:/Media")
        op = build_organize_plan(result, plan, output)
        assert len(op.moves) == 1
        assert "Trailers" in op.moves[0].destination

    def test_tv_episode_with_parenthetical_title_routes_by_se_classification(self):
        """Psych S5: an episode whose *title* contains a parenthetical
        (``Shawn and Gus in Drag (Racing)``) — or an episode dvdcompare
        files under a disc's extras (``Romeo and Juliet and Juliet
        (Extended Version)``, ``Dual Spires (Extended Version)``) — must
        still route to its Plex episode path. The dvdcompare match label
        looks like an extra (trailing parenthetical), so the pre-fix code
        sent these to ``Other/``. The rip-time ``SxxEyy`` classification
        recorded in the manifest is authoritative and now wins.
        """
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="C1_t00.mkv",
                    file_duration_seconds=2585,
                    matched_label="Disc 2: Shawn and Gus in Drag (Racing)",
                    matched_runtime_seconds=2590,
                    delta_seconds=5,
                    confidence="high",
                    classification="S05E05 - Shawn and Gus in Drag (Racing) (1080p)",
                ),
                MatchCandidate(
                    file_name="C1_t00.mkv",
                    file_duration_seconds=2894,
                    matched_label="Disc 1: Romeo and Juliet and Juliet ((Extended Version))",
                    matched_runtime_seconds=2898,
                    delta_seconds=4,
                    confidence="high",
                    classification="S05E01 - Romeo and Juliet and Juliet (1080p)",
                ),
                MatchCandidate(
                    file_name="D2_t03.mkv",
                    file_duration_seconds=3275,
                    matched_label="Disc 3: Dual Spires ((Extended Version))",
                    matched_runtime_seconds=3279,
                    delta_seconds=4,
                    confidence="high",
                    classification="S05E12 - Dual Spires (1080p)",
                ),
            ],
        )
        plan = PlannedShow(
            canonical_title="Psych",
            year=2006,
            seasons=[
                PlannedSeason(
                    season_number=5,
                    episodes=[
                        PlannedEpisode(season_number=5, episode_number=1, title="Romeo and Juliet and Juliet", runtime="48m"),
                        PlannedEpisode(season_number=5, episode_number=5, title="Shawn and Gus in Drag (Racket)", runtime="43m"),
                        PlannedEpisode(season_number=5, episode_number=12, title="Dual Spires", runtime="54m"),
                    ],
                ),
            ],
        )
        output = Path("E:/Media")
        op = build_organize_plan(result, plan, output)
        dests = sorted(m.destination for m in op.moves)
        assert len(op.moves) == 3
        # None land in Other/.
        assert all("Other" not in d for d in dests)
        assert all("Season 05" in d for d in dests)
        assert any(d.endswith("s05e01 - Romeo and Juliet and Juliet.mkv") for d in dests)
        assert any(d.endswith("s05e05 - Shawn and Gus in Drag (Racket).mkv") for d in dests)
        assert any(d.endswith("s05e12 - Dual Spires.mkv") for d in dests)

    def test_tv_episode_fuzzy_title_match(self):
        """dvdcompare titles diverging from TMDb still route correctly.

        Real-world cases from Psych S1: dvdcompare uses ``Domestic
        Pilot`` where TMDb has ``Pilot``, and ``Spellingg Bee`` where
        TMDb has ``Spelling Bee``. Exact match fails; fuzzy fallback
        must pick the right episode.
        """
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="d1_t00.mkv",
                    file_duration_seconds=3964,
                    matched_label="Disc 1: Domestic Pilot",
                    matched_runtime_seconds=3964,
                    delta_seconds=0,
                    confidence="high",
                ),
                MatchCandidate(
                    file_name="d2_t00.mkv",
                    file_duration_seconds=2588,
                    matched_label="Disc 2: Spellingg Bee",
                    matched_runtime_seconds=2588,
                    delta_seconds=0,
                    confidence="high",
                ),
            ],
        )
        plan = PlannedShow(
            canonical_title="Psych",
            year=2006,
            seasons=[
                PlannedSeason(
                    season_number=1,
                    episodes=[
                        PlannedEpisode(
                            season_number=1, episode_number=1,
                            title="Pilot", runtime="66m",
                        ),
                        PlannedEpisode(
                            season_number=1, episode_number=2,
                            title="Spelling Bee", runtime="43m",
                        ),
                    ],
                ),
            ],
        )
        output = Path("E:/Media")
        op = build_organize_plan(result, plan, output)
        assert len(op.moves) == 2
        destinations = [m.destination for m in op.moves]
        assert any("s01e01 - Pilot" in d for d in destinations)
        assert any("s01e02 - Spelling Bee" in d for d in destinations)

    def test_tv_episode_se_prefix_in_classification_routes_directly(self):
        """Rip-time SE tag on the classification bypasses fuzzy title lookup.

        The analysis step's TMDb enrichment stamps the classification
        with the resolved ``SxxEyy`` (e.g. ``"S01E03 - Spellingg Bee
        (1080p)"``). The organizer must trust that tag over any fuzzy
        re-derivation from the matched_label, keeping SE-known-at-rip-time
        routing fully deterministic even if the disc label's title
        differs from TMDb's canonical episode title.
        """
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="d1_t03.mkv",
                    file_duration_seconds=2588,
                    matched_label="Disc 1: Spellingg Bee",
                    matched_runtime_seconds=2588,
                    delta_seconds=0,
                    confidence="high",
                    classification="S01E03 - Spellingg Bee (1080p)",
                ),
            ],
        )
        plan = PlannedShow(
            canonical_title="Psych",
            year=2006,
            seasons=[
                PlannedSeason(
                    season_number=1,
                    episodes=[
                        PlannedEpisode(
                            season_number=1, episode_number=1,
                            title="Pilot", runtime="66m",
                        ),
                        PlannedEpisode(
                            season_number=1, episode_number=2,
                            title="Spelling Bee", runtime="43m",
                        ),
                        PlannedEpisode(
                            season_number=1, episode_number=3,
                            title="Speak Now or Forever Hold Your Piece",
                            runtime="43m",
                        ),
                    ],
                ),
            ],
        )
        output = Path("E:/Media")
        op = build_organize_plan(result, plan, output)
        assert len(op.moves) == 1
        dest = op.moves[0].destination
        assert "Season 01" in dest
        # SE from classification (E03) — canonical TMDb title used for
        # the filename, not the matched_label's dvdcompare title.
        assert "s01e03 - Speak Now or Forever Hold Your Piece" in dest

    def test_tv_episode_se_prefix_missing_season_falls_back_to_title(self):
        """Nonexistent SE in classification falls through to fuzzy lookup.

        Guards against silently misrouting when a manifest has a stale
        SE tag that no longer matches the current TMDb plan.
        """
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="d1_t00.mkv",
                    file_duration_seconds=2588,
                    matched_label="Disc 1: Spellingg Bee",
                    matched_runtime_seconds=2588,
                    delta_seconds=0,
                    confidence="high",
                    classification="S09E99 - Spellingg Bee (1080p)",
                ),
            ],
        )
        plan = PlannedShow(
            canonical_title="Psych",
            year=2006,
            seasons=[
                PlannedSeason(
                    season_number=1,
                    episodes=[
                        PlannedEpisode(
                            season_number=1, episode_number=2,
                            title="Spelling Bee", runtime="43m",
                        ),
                    ],
                ),
            ],
        )
        output = Path("E:/Media")
        op = build_organize_plan(result, plan, output)
        assert len(op.moves) == 1
        assert "s01e02 - Spelling Bee" in op.moves[0].destination

    def test_extra_classification_does_not_clobber_episode(self):
        """A ``[extra]`` file whose label matches an episode routes to extras.

        dvdcompare occasionally lists the same episode name twice (real
        episode + a bonus re-edit); the rip-time enrichment demotes the
        shorter duplicate to ``extra`` and stamps the classification
        with ``[extra] Title``. The matcher still pairs the extra file
        to a same-named target label, so if the organizer fuzzy-looks-up
        the label as an episode it clobbers the real episode's
        destination. Route by the classifier's verdict instead: extras
        go to an extras folder, the real episode keeps its Season NN
        slot.
        """
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="c2_t01.mkv",
                    file_duration_seconds=2588,
                    matched_label="Disc 1: Murder? Bueller?",
                    matched_runtime_seconds=2585,
                    delta_seconds=3,
                    confidence="high",
                    classification="S03E02 - Murder? Bueller? (1080p)",
                ),
                MatchCandidate(
                    file_name="c4_t06.mkv",
                    file_duration_seconds=2593,
                    matched_label="Disc 1: Murder? Bueller?",
                    matched_runtime_seconds=2585,
                    delta_seconds=8,
                    confidence="high",
                    classification="[extra] Murder? Bueller? (1080p)",
                ),
            ],
        )
        plan = PlannedShow(
            canonical_title="Psych",
            year=2006,
            seasons=[
                PlannedSeason(
                    season_number=3,
                    episodes=[
                        PlannedEpisode(
                            season_number=3, episode_number=2,
                            title="Murder? Bueller?", runtime="43m",
                        ),
                    ],
                ),
            ],
        )
        output = Path("E:/Media")
        op = build_organize_plan(result, plan, output)
        assert len(op.moves) == 2
        destinations = [m.destination for m in op.moves]
        # Real episode keeps the Season 03 slot.
        episode_moves = [d for d in destinations if "s03e02" in d]
        assert len(episode_moves) == 1, (
            f"expected exactly one file routed to s03e02, got {destinations}"
        )
        # The [extra] duplicate is diverted to an extras folder, not
        # a second copy of the episode.
        extra_moves = [d for d in destinations if "s03e02" not in d]
        assert len(extra_moves) == 1
        assert (
            "Featurettes" in extra_moves[0]
            or "Other" in extra_moves[0]
            or "Behind The Scenes" in extra_moves[0]
        )

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
        assert "Would organize to" in text
        assert "Unmatched" in text
        assert "Not Found" in text
        assert "Deleted Scene" in text
        assert "left in place" in text

    def test_unmatched_ignore_policy(self):
        op = OrganizePlan(
            unmatched=[ScannedFile(name="extra.mkv", path="/rip/extra.mkv", duration_seconds=50)],
        )
        actions = execute_plan(op, dry_run=True, unmatched_policy="ignore")
        text = "\n".join(actions)
        assert "left in place" in text
        assert "extra.mkv" in text

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
        assert "would move to" in text
        assert "_Unmatched" in text
        assert "extra.mkv" in text

    def test_unmatched_delete_policy_dry_run(self):
        op = OrganizePlan(
            unmatched=[ScannedFile(name="extra.mkv", path="/rip/extra.mkv", duration_seconds=50)],
        )
        actions = execute_plan(op, dry_run=True, unmatched_policy="delete")
        text = "\n".join(actions)
        assert "would delete" in text
        assert "extra.mkv" in text


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
        assert "Diaries - Ep6" in split.chapter_destinations[5]

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
        assert "split" in text.lower()
        assert "diaries.mkv" in text
        assert "s00e01" in text
        assert "s00e02" in text


class TestChapterToMissingSplits:
    """Test converting matched files to splits when chapters match missing entries."""

    def test_basic_movie_split(self):
        """File matched as Play All, but chapters match Teaser + Trailer 2."""
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="t12.mkv",
                    file_duration_seconds=194,
                    matched_label="Disc 3: Trailers: Play All",
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
            ("Disc 3: Trailers: Play All", 191, 3),
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
        assert "Disc 3: Trailers: Play All" in op.missing
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
                    matched_label="Disc 3: Trailers: Play All",
                    matched_runtime_seconds=191,
                    delta_seconds=3,
                    confidence="high",
                ),
                MatchCandidate(
                    file_name="t13.mkv",
                    file_duration_seconds=497,
                    matched_label="Disc 3: Features: Play All",
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
            ("Disc 3: Trailers: Play All", 191, 3),
            ("Disc 3: Opening Look", 307, 3),
            ("Disc 3: Features: Play All", 501, 3),
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
        # t13 split: Trailers Play All (released by t12) + Opening Look
        labels_1 = op.splits[1].chapter_labels
        assert "Disc 3: Trailers: Play All" in labels_1
        assert "Disc 3: Opening Look" in labels_1
        # Both original labels released back
        assert "Disc 3: Trailers: Play All" not in op.missing  # consumed by t13
        assert "Disc 3: Features: Play All" in op.missing

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
        """Chapter-to-missing splits play-all entries for TV show extras."""
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="extras.mkv",
                    file_duration_seconds=600,
                    matched_label="Disc 2: Extras: Play All (featurette)",
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
            ("Disc 2: Extras: Play All (featurette)", 590, 2),
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

    def test_standalone_featurette_not_split(self):
        """A standalone featurette with chapters should NOT be split even if
        its chapters match missing entries by runtime."""
        result = OrganizeResult(
            matched=[
                MatchCandidate(
                    file_name="rabbit.mkv",
                    file_duration_seconds=600,
                    matched_label="Disc 2: Follow the White Rabbit (featurette)",
                    matched_runtime_seconds=590,
                    delta_seconds=10,
                    confidence="high",
                ),
            ],
            missing=["Disc 2: Extra A (featurette)", "Disc 2: Extra B (featurette)"],
        )
        plan = PlannedMovie(
            canonical_title="The Matrix", year=1999,
            runtime="2h 16m", runtime_seconds=8160,
        )
        disc_targets = [
            ("Disc 2: Extra A (featurette)", 290, 2),
            ("Disc 2: Extra B (featurette)", 310, 2),
            ("Disc 2: Follow the White Rabbit (featurette)", 590, 2),
        ]
        scanned = {
            "rabbit.mkv": ScannedFile(
                name="rabbit.mkv", path="/rip/rabbit.mkv",
                duration_seconds=600, chapter_count=2,
                chapter_durations=[290, 310],
            ),
        }
        op = build_organize_plan(
            result, plan, Path("E:/Media"),
            scanned_files=scanned, disc_targets=disc_targets,
        )
        # The file should remain as a regular move, not be split
        assert len(op.splits) == 0
        assert len(op.moves) == 1
        assert "Follow the White Rabbit" in op.moves[0].destination


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


class TestArchiveSourceFolder:
    """Verify archive_source_folder moves the folder and prunes
    empty parents up to (but not including) the rip output root."""

    def test_prunes_empty_parent_up_to_stop(self, tmp_path):
        from riplex.organizer import archive_source_folder

        rip_root = tmp_path / "_MakeMKV"
        source = rip_root / "Psych (2006)" / "Season 02"
        source.mkdir(parents=True)
        (source / "file.mkv").write_text("x")
        archive_root = tmp_path / "_archive"

        dest = archive_source_folder(
            source, str(archive_root), prune_stop=rip_root,
        )

        assert dest == archive_root / "Season 02"
        assert dest.exists()
        # Empty ``Psych (2006)/`` shell should be pruned.
        assert not (rip_root / "Psych (2006)").exists()
        # Rip root itself must survive.
        assert rip_root.exists()

    def test_does_not_prune_stop_directory(self, tmp_path):
        from riplex.organizer import archive_source_folder

        rip_root = tmp_path / "_MakeMKV"
        source = rip_root / "Movie (2020)"
        source.mkdir(parents=True)
        (source / "file.mkv").write_text("x")
        archive_root = tmp_path / "_archive"

        archive_source_folder(
            source, str(archive_root), prune_stop=rip_root,
        )

        assert rip_root.exists()  # never removed even when empty

    def test_stops_at_non_empty_ancestor(self, tmp_path):
        from riplex.organizer import archive_source_folder

        rip_root = tmp_path / "_MakeMKV"
        source = rip_root / "Show" / "Season 01"
        source.mkdir(parents=True)
        (source / "file.mkv").write_text("x")
        # Sibling season keeps ``Show/`` non-empty after archive.
        (rip_root / "Show" / "Season 02").mkdir()
        archive_root = tmp_path / "_archive"

        archive_source_folder(
            source, str(archive_root), prune_stop=rip_root,
        )

        assert (rip_root / "Show").exists()
        assert (rip_root / "Show" / "Season 02").exists()
        assert not (rip_root / "Show" / "Season 01").exists()

    def test_no_prune_stop_still_moves(self, tmp_path):
        from riplex.organizer import archive_source_folder

        source = tmp_path / "Rip"
        source.mkdir()
        (source / "file.mkv").write_text("x")
        archive_root = tmp_path / "_archive"

        dest = archive_source_folder(source, str(archive_root))

        assert dest == archive_root / "Rip"
        assert dest.exists()
        assert not source.exists()

    def test_empty_archive_root_returns_none(self, tmp_path):
        from riplex.organizer import archive_source_folder

        source = tmp_path / "Rip"
        source.mkdir()

        assert archive_source_folder(source, "") is None
        assert source.exists()

