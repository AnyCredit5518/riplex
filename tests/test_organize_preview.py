"""Tests for organize-preview presentation helpers."""

from riplex_app.screens.organize_preview import _natural_sort_key


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