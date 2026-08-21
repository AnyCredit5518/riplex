"""Regressions for alternate TV disc layouts."""

import json

from riplex.disc.analysis import (
    EpisodeCarryover,
    analyze_disc,
    derive_episode_carryover_from_manifest,
    print_disc_analysis,
)
from riplex.disc.makemkv import DiscInfo, DiscTitle
from riplex.manifest import read_episode_carryover, serialize_episode_carryover
from riplex.metadata.provider import EpisodeMetadata
from riplex.models import PlannedDisc, PlannedEpisode, PlannedExtra


EPISODE_TITLES = {
    1: "Santabarbaratown 2",
    2: "Juliet Takes a Luvvah",
    3: "Lassie Jerky",
    4: "No Country for Two Old Men",
    5: "100 Clues",
    6: "Cirque Du Soul",
    7: "Deez Nups",
    8: "Right Turn or Left for Dead",
    9: "Juliet Wears the Pantsuit",
    10: "Santa Barbarian Candidate",
}


def _title(index: int, runtime: int = 2580) -> DiscTitle:
    return DiscTitle(
        index=index,
        name=f"Title {index}",
        duration_seconds=runtime,
        chapters=5,
        size_bytes=1_500_000_000 + index * 10_000_000,
        filename=f"title_t{index:02d}.mkv",
        playlist=f"000{index:02d}.mpls",
        resolution="720x480",
        video_codec="Mpeg2",
    )


def _episode(number: int, runtime: int = 2580) -> PlannedEpisode:
    return PlannedEpisode(
        season_number=7,
        episode_number=number,
        title=EPISODE_TITLES[number],
        runtime="43m",
        runtime_seconds=runtime,
    )


def _metadata(numbers: range) -> list[EpisodeMetadata]:
    return [
        EpisodeMetadata(7, number, EPISODE_TITLES[number], 2580)
        for number in numbers
    ]


def test_carryover_precedes_same_length_current_disc_episodes():
    discs = [
        PlannedDisc(1, "DVD", episodes=[_episode(number) for number in range(1, 6)]),
        PlannedDisc(2, "DVD", episodes=[_episode(number) for number in range(6, 11)]),
    ]
    disc_one = DiscInfo("PSYCH", "DVD", [_title(index) for index in range(4)])

    first = analyze_disc(
        disc_one,
        discs,
        disc_number=1,
        is_movie=False,
        tmdb_episodes=_metadata(range(1, 11)),
    )

    assert first.next_episode_carryover == [
        EpisodeCarryover("S07E05 - 100 Clues", 2580, 1),
    ]

    disc_two = DiscInfo("PSYCH", "DVD", [_title(index) for index in range(5)])
    second = analyze_disc(
        disc_two,
        discs,
        disc_number=2,
        is_movie=False,
        tmdb_episodes=_metadata(range(1, 11)),
        episode_carryover=first.next_episode_carryover,
    )

    assert [
        second.classifications[index].split(" - ")[0]
        for index in range(5)
    ] == ["S07E05", "S07E06", "S07E07", "S07E08", "S07E09"]
    assert second.assessments[0].recommendation == "review"
    assert second.assessments[0].identification == "Expected on Disc 1"
    assert all(
        second.assessments[index].recommendation == "review"
        for index in range(5)
    )
    assert second.assessments[1].identification == "Alternate layout sequence"
    assert [title.index for title in second.rippable_titles] == list(range(5))
    assert second.next_episode_carryover == [
        EpisodeCarryover("S07E10 - Santa Barbarian Candidate", 2580, 2),
    ]


def test_next_disc_episode_overflow_is_borrowed_once(capsys):
    episode_titles = {
        1: "Lock, Stock, Some Smoking Barrels and Burton Guster's Goblet of Fire",
        2: "S.E.I.Z.E. the Day",
        3: "Remake A.K.A. Cloudy... With a Chance of Improvement",
        4: "Someone's Got a Woody",
        5: "COG Blocked",
        6: "1967: A Psych Odyssey",
        7: "Shawn and Gus Truck Things Up",
        8: "A Touch of Sweevil",
    }

    def episode(number: int) -> PlannedEpisode:
        return PlannedEpisode(
            8, number, episode_titles[number], "43m", 2580,
        )

    metadata = [
        EpisodeMetadata(8, number, episode_titles[number], 2580)
        for number in range(1, 9)
    ]
    discs = [
        PlannedDisc(
            1,
            "DVD",
            episodes=[episode(number) for number in range(2, 5)],
            extras=[
                PlannedExtra("Episodes"),
                PlannedExtra(
                    episode_titles[1], 2760, "(Extended Version)",
                ),
                PlannedExtra("Deleted Scenes", 300),
            ],
        ),
        PlannedDisc(
            2,
            "DVD",
            episodes=[episode(number) for number in range(5, 9)],
        ),
    ]
    disc_one = DiscInfo(
        "PSYCH",
        "DVD",
        [
            _title(2, 13190),
            _title(3, 2875),
            _title(4, 2583),
            _title(5, 2576),
            _title(6, 2573),
            _title(7, 2583),
            _title(8, 303),
        ],
    )

    first = analyze_disc(
        disc_one,
        discs,
        disc_number=1,
        is_movie=False,
        tmdb_episodes=metadata,
    )

    assert first.classifications[2].startswith("Play-all of 5 titles")
    assert "S08E01" in first.classifications[3]
    assert "Extended Version" in first.classifications[3]
    assert first.classifications[4].startswith("S08E02")
    assert first.classifications[5].startswith("S08E03")
    assert first.classifications[6].startswith("S08E04")
    assert first.classifications[7].startswith("S08E05 - COG Blocked")
    assert "Deleted Scenes" in first.classifications[8]
    assert [title.index for title in first.rippable_titles] == [3, 4, 5, 6, 7, 8]
    assert first.assessments[7].recommendation == "review"
    assert first.assessments[7].identification == "Expected on Disc 2"
    assert first.next_episode_carryover == [
        EpisodeCarryover("S08E05 - COG Blocked", 2580, 2),
    ]

    print_disc_analysis(
        disc_one,
        [discs[0]],
        False,
        None,
        analysis=first,
    )
    printed = capsys.readouterr().out
    assert "S08E05 - COG Blocked" in printed
    assert "Rip titles: 3, 4, 5, 6, 7, 8" in printed

    disc_two = DiscInfo(
        "PSYCH",
        "DVD",
        [_title(index) for index in range(3)],
    )
    second = analyze_disc(
        disc_two,
        discs,
        disc_number=2,
        is_movie=False,
        episode_carryover=first.next_episode_carryover,
    )

    assert [
        second.classifications[index].split(" (480p)")[0]
        for index in range(3)
    ] == [episode_titles[6], episode_titles[7], episode_titles[8]]
    assert second.next_episode_carryover == []


def test_next_disc_overflow_does_not_invent_episode_from_canonical_runtime():
    episode_titles = {
        5: "COG Blocked",
        6: "1967: A Psych Odyssey",
        7: "Shawn and Gus Truck Things Up",
        8: "A Touch of Sweevil",
        9: "A Nightmare on State Street",
        10: "The Break-Up",
    }

    def episode(number: int, runtime: int = 2580) -> PlannedEpisode:
        return PlannedEpisode(
            8, number, episode_titles[number], f"{runtime // 60}m", runtime,
        )

    metadata = [
        EpisodeMetadata(8, number, episode_titles[number], 2580)
        for number in range(5, 11)
    ]
    discs = [
        PlannedDisc(
            2,
            "DVD",
            episodes=[episode(5), episode(6), episode(7, 2520), episode(8)],
            extras=[PlannedExtra("Was It Something I Said?", 199, "music video")],
        ),
        PlannedDisc(
            3,
            "DVD",
            episodes=[episode(10, 2880)],
            extras=[
                PlannedExtra(episode_titles[9], 2580, "(Director's Cut)"),
                PlannedExtra("Psych: The Musical", 5231, "episode"),
            ],
        ),
    ]
    disc_two = DiscInfo(
        "PSYCH",
        "DVD",
        [
            _title(0, 199),
            _title(1, 12816),
            _title(2, 2565),
            _title(3, 2529),
            _title(4, 2566),
            _title(5, 2575),
            _title(6, 2581),
        ],
    )

    second = analyze_disc(
        disc_two,
        discs,
        disc_number=2,
        is_movie=False,
        tmdb_episodes=metadata,
        episode_carryover=[EpisodeCarryover("S08E05 - COG Blocked", 2580, 2)],
    )

    assert [
        second.classifications[index].split(" - ")[0]
        for index in range(2, 5)
    ] == ["S08E06", "S08E07", "S08E08"]
    assert second.classifications[5].startswith("Unmatched content")
    assert second.classifications[6].startswith("S08E09")
    assert "Director's Cut" in second.classifications[6]
    assert second.assessments[6].recommendation == "review"
    assert second.assessments[6].identification == "Expected on Disc 3"
    assert second.next_episode_carryover == [
        EpisodeCarryover(
            "S08E09 - A Nightmare on State Street (Director's Cut)", 2580, 3,
        ),
    ]

    third = analyze_disc(
        DiscInfo("PSYCH", "DVD", [_title(0, 2581), _title(1, 5231)]),
        discs,
        disc_number=3,
        is_movie=False,
        tmdb_episodes=metadata,
        episode_carryover=second.next_episode_carryover,
    )

    assert third.classifications[0].startswith("S08E10 - The Break-Up")
    assert third.classifications[1].startswith("Psych: The Musical")
    assert third.next_episode_carryover == []


def test_next_disc_overflow_rejects_duplicate_title():
    discs = [
        PlannedDisc(1, "DVD", episodes=[_episode(1)]),
        PlannedDisc(2, "DVD", episodes=[_episode(2)]),
    ]
    original = _title(0)
    duplicate = _title(1)
    duplicate.size_bytes = original.size_bytes

    analysis = analyze_disc(
        DiscInfo("PSYCH", "DVD", [original, duplicate]),
        discs,
        disc_number=1,
        is_movie=False,
        tmdb_episodes=_metadata(range(1, 3)),
    )

    assert analysis.classifications[1].startswith("Duplicate of #0")
    assert analysis.next_episode_carryover == []


def test_next_disc_overflow_rejects_lower_resolution_duplicate():
    discs = [
        PlannedDisc(1, "DVD", episodes=[_episode(1)]),
        PlannedDisc(2, "DVD", episodes=[_episode(2)]),
    ]
    original = _title(0)
    original.resolution = "3840x2160"
    duplicate = _title(1)
    duplicate.resolution = "1920x1080"

    analysis = analyze_disc(
        DiscInfo("PSYCH", "DVD", [original, duplicate]),
        discs,
        disc_number=1,
        is_movie=False,
        tmdb_episodes=_metadata(range(1, 3)),
    )

    assert duplicate not in analysis.rippable_titles
    assert analysis.next_episode_carryover == []


def test_next_disc_overflow_rejects_play_all_title():
    discs = [
        PlannedDisc(
            1,
            "DVD",
            episodes=[_episode(1, 1200), _episode(2, 1200)],
        ),
        PlannedDisc(2, "DVD", episodes=[_episode(3, 2520)]),
    ]
    metadata = [
        EpisodeMetadata(7, 1, EPISODE_TITLES[1], 1200),
        EpisodeMetadata(7, 2, EPISODE_TITLES[2], 1200),
        EpisodeMetadata(7, 3, EPISODE_TITLES[3], 2520),
    ]

    analysis = analyze_disc(
        DiscInfo(
            "PSYCH",
            "DVD",
            [_title(0, 1200), _title(1, 1200), _title(2, 2400)],
        ),
        discs,
        disc_number=1,
        is_movie=False,
        tmdb_episodes=metadata,
    )

    assert analysis.classifications[2].startswith("Play-all of 2 titles")
    assert analysis.next_episode_carryover == []


def test_latest_prior_disc_carryover_survives_resume(tmp_path):
    disc_one = tmp_path / "Disc 1"
    disc_one.mkdir()
    carryover = [EpisodeCarryover("S07E05 - 100 Clues", 3191, 1)]
    (disc_one / "_rip_manifest.json").write_text(
        json.dumps({"episode_carryover": serialize_episode_carryover(carryover)}),
        encoding="utf-8",
    )

    assert read_episode_carryover(tmp_path, before_disc=2) == carryover


def test_legacy_manifest_reconstructs_missing_prior_disc_episode():
    disc = PlannedDisc(
        1,
        "DVD",
        episodes=[_episode(number) for number in range(1, 6)],
    )
    manifest = {
        "disc_number": 1,
        "files": [
            {"classification": f"S07E{number:02d} - {EPISODE_TITLES[number]} (480p)"}
            for number in range(1, 5)
        ],
    }

    assert derive_episode_carryover_from_manifest(
        manifest,
        [disc],
        _metadata(range(1, 6)),
    ) == [EpisodeCarryover("S07E05 - 100 Clues", 2580, 1)]
