"""Offline disc cases that exercise the real DVDCompare conversion path."""

import json
from pathlib import Path

from dvdcompare.models import Disc, Feature, Release

from riplex.disc.makemkv import DiscInfo, DiscTitle
from riplex.disc.provider import _convert_release
from riplex.metadata.provider import EpisodeMetadata, SeasonMetadata, ShowDetail


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _build_features(features_data: list) -> list[Feature]:
    return [
        Feature(
            title=feature["title"],
            runtime_seconds=feature.get("runtime_seconds"),
            feature_type=feature.get("feature_type"),
            is_play_all=feature.get("is_play_all", False),
            children=_build_features(feature.get("children", [])),
        )
        for feature in features_data
    ]


def load_disc_fixture(name: str):
    """Return live titles, genuinely converted release discs, and expectations."""
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    titles = [
        DiscTitle(
            index=title["index"],
            name=title.get("name", f"Title {title['index']}"),
            duration_seconds=title["duration_seconds"],
            chapters=title.get("chapters", 1),
            size_bytes=title["size_bytes"],
            filename=title.get("filename", f"title_t{title['index']:02d}.mkv"),
            playlist=title.get("playlist", ""),
            resolution=title["resolution"],
            video_codec=title.get("video_codec", ""),
            segment_count=title.get("segment_count", 1),
            segment_map=title.get("segment_map", ""),
        )
        for title in data["titles"]
    ]
    info = DiscInfo(
        disc_name=data.get("disc_name", ""),
        disc_type=data.get("disc_type", "Blu-ray disc"),
        titles=titles,
    )
    source = data.get("dvdcompare", {})
    release = Release(
        name=source.get("release_name", "Test Release"),
        discs=[
            Disc(
                number=disc["number"],
                format=disc.get("format", "Blu-ray"),
                is_film=disc.get("is_film", False),
                features=_build_features(disc.get("features", [])),
            )
            for disc in source.get("discs", [])
        ],
    )
    return info, _convert_release(release), data.get("expected", {})


def load_show_detail(name: str) -> ShowDetail:
    """Rebuild canonical TMDb episode metadata without network or local caches."""
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))["tmdb"]
    return ShowDetail(
        source_id=data["source_id"],
        title=data["title"],
        year=data["year"],
        seasons=[
            SeasonMetadata(
                season_number=season["season_number"],
                episodes=[EpisodeMetadata(**episode) for episode in season["episodes"]],
            )
            for season in data["seasons"]
        ],
    )