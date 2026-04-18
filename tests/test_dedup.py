"""Tests for duplicate detection."""

import pytest

from plex_planner.dedup import (
    CompilationGroup,
    DuplicateGroup,
    _dhash,
    _hamming,
    _match_chapters_to_files,
    confirm_duplicates_tier2,
    find_all_redundant,
    find_compilations,
    find_duplicates,
    find_duplicates_tier1,
    remove_duplicates,
)
from plex_planner.models import ScannedDisc, ScannedFile


def _make_file(
    name: str,
    duration: int = 2087,
    size: int = 6_887_000_000,
    fingerprint: str = "h264:1920x1080|ac3:eng:2ch|sub:eng|sub:spa|sub:fra",
    chapters: int = 4,
    chapter_durations: list[int] | None = None,
    path: str | None = None,
) -> ScannedFile:
    return ScannedFile(
        name=name,
        path=path or f"C:\\rip\\{name}",
        duration_seconds=duration,
        size_bytes=size,
        stream_count=5,
        stream_fingerprint=fingerprint,
        chapter_count=chapters,
        chapter_durations=chapter_durations or [],
    )


# ---------------------------------------------------------------------------
# Tier 1 tests
# ---------------------------------------------------------------------------


class TestTier1:
    def test_detects_near_identical_files(self):
        """t17 vs t02 scenario: ~1.5s duration delta, ~0.06% size delta."""
        a = _make_file("t17.mkv", duration=2087, size=6_887_298_291)
        b = _make_file("t02.mkv", duration=2085, size=6_883_114_933)
        groups = find_duplicates_tier1([a, b])
        assert len(groups) == 1
        assert groups[0].keep.name == "t17.mkv"  # larger file kept
        assert groups[0].duplicates[0].name == "t02.mkv"

    def test_no_duplicates_different_duration(self):
        """Files with very different durations are not duplicates."""
        a = _make_file("short.mkv", duration=120, size=500_000_000)
        b = _make_file("long.mkv", duration=2087, size=6_887_000_000)
        groups = find_duplicates_tier1([a, b])
        assert groups == []

    def test_no_duplicates_different_size(self):
        """Same duration but very different file sizes."""
        a = _make_file("a.mkv", duration=2087, size=6_887_000_000)
        b = _make_file("b.mkv", duration=2087, size=1_000_000_000)
        groups = find_duplicates_tier1([a, b])
        assert groups == []

    def test_no_duplicates_different_streams(self):
        """Same duration and size but different stream layouts."""
        a = _make_file("a.mkv", fingerprint="h264:1920x1080|ac3:eng:2ch")
        b = _make_file("b.mkv", fingerprint="h264:1920x1080|ac3:eng:6ch")
        groups = find_duplicates_tier1([a, b])
        assert groups == []

    def test_single_file_no_duplicates(self):
        a = _make_file("only.mkv")
        groups = find_duplicates_tier1([a])
        assert groups == []

    def test_three_way_duplicate(self):
        """Three copies of the same content are grouped together."""
        a = _make_file("a.mkv", size=6_887_000_000, path="C:\\rip\\a.mkv")
        b = _make_file("b.mkv", size=6_885_000_000, path="C:\\rip\\b.mkv")
        c = _make_file("c.mkv", size=6_883_000_000, path="C:\\rip\\c.mkv")
        groups = find_duplicates_tier1([a, b, c])
        assert len(groups) == 1
        assert groups[0].keep.name == "a.mkv"
        assert len(groups[0].duplicates) == 2

    def test_empty_fingerprint_not_matched(self):
        """Files without stream fingerprints are not grouped."""
        a = _make_file("a.mkv", fingerprint="")
        b = _make_file("b.mkv", fingerprint="")
        groups = find_duplicates_tier1([a, b])
        assert groups == []


# ---------------------------------------------------------------------------
# dhash / hamming tests
# ---------------------------------------------------------------------------


class TestDhash:
    def test_identical_bytes(self):
        """Identical pixel data produces the same hash."""
        data = bytes(range(72))
        assert _dhash(data) == _dhash(data)

    def test_uniform_images_same_hash(self):
        """Uniform images produce the same hash (no gradient = all zeros)."""
        data_a = bytes([0] * 72)
        data_b = bytes([255] * 72)
        assert _dhash(data_a) == _dhash(data_b) == 0

    def test_gradient_produces_nonzero_hash(self):
        """A gradient image produces a non-zero hash."""
        data = bytes(range(72))
        assert _dhash(data) != 0

    def test_wrong_size_returns_zero(self):
        assert _dhash(b"short") == 0

    def test_hamming_identical(self):
        assert _hamming(0xABCD, 0xABCD) == 0

    def test_hamming_one_bit(self):
        assert _hamming(0b1000, 0b0000) == 1

    def test_hamming_all_different(self):
        assert _hamming(0xFF, 0x00) == 8


# ---------------------------------------------------------------------------
# find_duplicates (full pipeline) tests
# ---------------------------------------------------------------------------


class TestFindDuplicates:
    def test_across_disc_groups(self):
        """Duplicates are detected even when files are in different disc groups."""
        a = _make_file("t17.mkv", duration=2087, size=6_887_298_291, path="C:\\rip\\SF\\t17.mkv")
        b = _make_file("t02.mkv", duration=2085, size=6_883_114_933, path="C:\\rip\\SF\\t02.mkv")
        c = _make_file("main.mkv", duration=10822, size=92_000_000_000, path="C:\\rip\\main.mkv")

        discs = [
            ScannedDisc(folder_name="root", files=[c]),
            ScannedDisc(folder_name="Special Features", files=[a, b]),
        ]
        groups = find_duplicates(discs)
        assert len(groups) == 1
        assert groups[0].keep.name == "t17.mkv"

    def test_no_duplicates(self):
        a = _make_file("a.mkv", duration=120, size=500_000_000)
        b = _make_file("b.mkv", duration=2087, size=6_887_000_000)
        discs = [ScannedDisc(folder_name="root", files=[a, b])]
        groups = find_duplicates(discs)
        assert groups == []


# ---------------------------------------------------------------------------
# remove_duplicates tests
# ---------------------------------------------------------------------------


class TestRemoveDuplicates:
    def test_removes_duplicate_files(self):
        keep = _make_file("t17.mkv", path="C:\\rip\\SF\\t17.mkv")
        dup = _make_file("t02.mkv", path="C:\\rip\\SF\\t02.mkv")
        other = _make_file("main.mkv", duration=10822, size=92_000_000_000, path="C:\\rip\\main.mkv")

        discs = [
            ScannedDisc(folder_name="root", files=[other]),
            ScannedDisc(folder_name="SF", files=[keep, dup]),
        ]
        groups = [DuplicateGroup(keep=keep, duplicates=[dup])]
        result = remove_duplicates(discs, groups)

        assert len(result) == 2
        assert len(result[0].files) == 1  # root: main.mkv
        assert len(result[1].files) == 1  # SF: t17.mkv kept
        assert result[1].files[0].name == "t17.mkv"

    def test_empty_disc_removed(self):
        """If all files in a disc group are duplicates, the group is dropped."""
        keep = _make_file("a.mkv", path="C:\\disc1\\a.mkv")
        dup = _make_file("b.mkv", path="C:\\disc2\\b.mkv")

        discs = [
            ScannedDisc(folder_name="disc1", files=[keep]),
            ScannedDisc(folder_name="disc2", files=[dup]),
        ]
        groups = [DuplicateGroup(keep=keep, duplicates=[dup])]
        result = remove_duplicates(discs, groups)

        assert len(result) == 1
        assert result[0].folder_name == "disc1"

    def test_no_groups_returns_original(self):
        a = _make_file("a.mkv")
        discs = [ScannedDisc(folder_name="root", files=[a])]
        result = remove_duplicates(discs, [])
        assert result is discs  # identity, no copy needed

    def test_removes_compilations(self):
        """remove_duplicates also removes compilation files."""
        teaser = _make_file("teaser.mkv", duration=70, size=100_000_000,
                            chapters=1, path="C:\\rip\\teaser.mkv")
        trailer = _make_file("trailer.mkv", duration=124, size=200_000_000,
                             chapters=1, path="C:\\rip\\trailer.mkv")
        combined = _make_file("combined.mkv", duration=194, size=300_000_000,
                              chapters=2, chapter_durations=[70, 124],
                              path="C:\\rip\\combined.mkv")
        discs = [ScannedDisc(folder_name="SF", files=[teaser, trailer, combined])]
        comps = [CompilationGroup(compilation=combined, parts=[teaser, trailer])]
        result = remove_duplicates(discs, [], comps)
        assert len(result) == 1
        names = [f.name for f in result[0].files]
        assert "combined.mkv" not in names
        assert "teaser.mkv" in names
        assert "trailer.mkv" in names


# ---------------------------------------------------------------------------
# Compilation detection tests
# ---------------------------------------------------------------------------

_SF_FP = "h264:1920x1080|dts:eng:6ch|sub:eng"


class TestMatchChaptersToFiles:
    def test_exact_match(self):
        a = _make_file("a.mkv", duration=70, fingerprint=_SF_FP)
        b = _make_file("b.mkv", duration=124, fingerprint=_SF_FP)
        result = _match_chapters_to_files([70, 124], [a, b])
        assert result is not None
        assert result[0].name == "a.mkv"
        assert result[1].name == "b.mkv"

    def test_within_tolerance(self):
        a = _make_file("a.mkv", duration=71, fingerprint=_SF_FP)
        b = _make_file("b.mkv", duration=120, fingerprint=_SF_FP)
        result = _match_chapters_to_files([70, 124], [a, b])
        assert result is not None

    def test_no_match_outside_tolerance(self):
        a = _make_file("a.mkv", duration=70, fingerprint=_SF_FP)
        b = _make_file("b.mkv", duration=200, fingerprint=_SF_FP)
        result = _match_chapters_to_files([70, 124], [a, b])
        assert result is None

    def test_no_reuse_of_files(self):
        """Each file can only match one chapter."""
        a = _make_file("a.mkv", duration=70, fingerprint=_SF_FP, path="C:\\a.mkv")
        result = _match_chapters_to_files([70, 70], [a])
        assert result is None


class TestFindCompilations:
    def test_oppenheimer_trailers(self):
        """Two trailers + their play-all compilation."""
        teaser = _make_file("t08.mkv", duration=71, size=80_000_000,
                            chapters=1, fingerprint=_SF_FP, path="C:\\rip\\t08.mkv")
        trailer2 = _make_file("t09.mkv", duration=124, size=150_000_000,
                              chapters=1, fingerprint=_SF_FP, path="C:\\rip\\t09.mkv")
        combined = _make_file("t12.mkv", duration=194, size=230_000_000,
                              chapters=2, chapter_durations=[70, 124],
                              fingerprint=_SF_FP, path="C:\\rip\\t12.mkv")
        other = _make_file("interview.mkv", duration=2087, size=6_887_000_000,
                           chapters=4, chapter_durations=[500, 500, 500, 587],
                           fingerprint=_SF_FP, path="C:\\rip\\interview.mkv")

        groups = find_compilations([teaser, trailer2, combined, other])
        assert len(groups) == 1
        assert groups[0].compilation.name == "t12.mkv"
        parts_names = {p.name for p in groups[0].parts}
        assert parts_names == {"t08.mkv", "t09.mkv"}

    def test_no_compilation_without_chapter_durations(self):
        """Files without chapter_durations are not considered compilations."""
        a = _make_file("a.mkv", duration=70, chapters=1, fingerprint=_SF_FP,
                        path="C:\\a.mkv")
        b = _make_file("b.mkv", duration=124, chapters=1, fingerprint=_SF_FP,
                        path="C:\\b.mkv")
        c = _make_file("c.mkv", duration=194, chapters=2, chapter_durations=[],
                        fingerprint=_SF_FP, path="C:\\c.mkv")
        groups = find_compilations([a, b, c])
        assert groups == []

    def test_no_compilation_different_fingerprints(self):
        """Files with different stream layouts are not grouped."""
        a = _make_file("a.mkv", duration=70, chapters=1,
                        fingerprint="h264:1920x1080|ac3:eng:2ch",
                        path="C:\\a.mkv")
        b = _make_file("b.mkv", duration=124, chapters=1,
                        fingerprint="h264:1920x1080|ac3:eng:2ch",
                        path="C:\\b.mkv")
        c = _make_file("c.mkv", duration=194, chapters=2, chapter_durations=[70, 124],
                        fingerprint="h264:1920x1080|dts:eng:6ch",
                        path="C:\\c.mkv")
        groups = find_compilations([a, b, c])
        assert groups == []

    def test_too_few_files(self):
        """Need at least 3 files (1 compilation + 2 parts)."""
        a = _make_file("a.mkv", duration=194, chapters=2,
                        chapter_durations=[70, 124], fingerprint=_SF_FP)
        b = _make_file("b.mkv", duration=70, chapters=1, fingerprint=_SF_FP)
        groups = find_compilations([a, b])
        assert groups == []

    def test_does_not_flag_normal_multi_chapter_file(self):
        """A multi-chapter file where chapters don't match other files is not a compilation."""
        doc = _make_file("doc.mkv", duration=5238, chapters=8,
                          chapter_durations=[600, 700, 650, 680, 620, 710, 640, 638],
                          fingerprint=_SF_FP, size=10_000_000_000, path="C:\\doc.mkv")
        short1 = _make_file("s1.mkv", duration=120, chapters=1, fingerprint=_SF_FP,
                             size=100_000_000, path="C:\\s1.mkv")
        short2 = _make_file("s2.mkv", duration=180, chapters=1, fingerprint=_SF_FP,
                             size=150_000_000, path="C:\\s2.mkv")
        short3 = _make_file("s3.mkv", duration=90, chapters=1, fingerprint=_SF_FP,
                             size=80_000_000, path="C:\\s3.mkv")
        groups = find_compilations([doc, short1, short2, short3])
        assert groups == []


class TestFindAllRedundant:
    def test_finds_both_duplicates_and_compilations(self):
        """Integration test: exact duplicates and compilations detected together."""
        # Duplicate pair
        keep = _make_file("t17.mkv", duration=2087, size=6_887_298_291,
                          fingerprint=_SF_FP, path="C:\\rip\\t17.mkv")
        dup = _make_file("t02.mkv", duration=2085, size=6_883_114_933,
                         fingerprint=_SF_FP, path="C:\\rip\\t02.mkv")
        # Compilation trio
        teaser = _make_file("t08.mkv", duration=71, size=80_000_000,
                            chapters=1, fingerprint=_SF_FP, path="C:\\rip\\t08.mkv")
        trailer = _make_file("t09.mkv", duration=124, size=150_000_000,
                             chapters=1, fingerprint=_SF_FP, path="C:\\rip\\t09.mkv")
        combined = _make_file("t12.mkv", duration=194, size=230_000_000,
                              chapters=2, chapter_durations=[70, 124],
                              fingerprint=_SF_FP, path="C:\\rip\\t12.mkv")

        discs = [ScannedDisc(folder_name="SF", files=[keep, dup, teaser, trailer, combined])]
        dups, comps = find_all_redundant(discs)
        assert len(dups) == 1
        assert dups[0].keep.name == "t17.mkv"
        assert len(comps) == 1
        assert comps[0].compilation.name == "t12.mkv"
