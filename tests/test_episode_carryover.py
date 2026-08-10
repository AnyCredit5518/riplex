"""Regressions for alternate TV disc layouts."""

import json

from riplex.disc.analysis import (
    EpisodeCarryover,
    analyze_disc,
    derive_episode_carryover_from_manifest,
)
from riplex.disc.makemkv import DiscInfo, DiscTitle
from riplex.manifest import read_episode_carryover, serialize_episode_carryover
from riplex.metadata.provider import EpisodeMetadata
from riplex.models import PlannedDisc, PlannedEpisode


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
