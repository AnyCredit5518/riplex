"""Tests for the normalization layer."""

from riplex.normalize import (
    build_movie_paths,
    build_show_paths,
    episode_file_name,
    format_runtime,
    movie_file_name,
    movie_folder_name,
    sanitize_filename,
    season_folder_name,
    show_folder_name,
)


class TestSanitizeFilename:
    def test_removes_colon_with_space(self):
        assert sanitize_filename("Top Gun: Maverick") == "Top Gun Maverick"

    def test_removes_colon_without_space(self):
        assert sanitize_filename("X-Men:The Animated Series") == "X-MenThe Animated Series"

    def test_removes_colon_with_space_xmen(self):
        assert sanitize_filename("X-Men: The Animated Series") == "X-Men The Animated Series"

    def test_removes_multiple_illegal_chars(self):
        assert sanitize_filename('Movie? <Title> "Sub"') == "Movie Title Sub"

    def test_preserves_hyphens_and_parens(self):
        assert sanitize_filename("Spider-Man (2002)") == "Spider-Man (2002)"

    def test_collapses_spaces(self):
        assert sanitize_filename("A   B") == "A B"

    def test_strips_whitespace(self):
        assert sanitize_filename("  Hello  ") == "Hello"

    def test_empty_string(self):
        assert sanitize_filename("") == ""

    def test_strips_leading_dashes(self):
        assert sanitize_filename('---- "The Bat"') == "The Bat"

    def test_strips_leading_dashes_no_quotes(self):
        assert sanitize_filename("---- Behind the Story") == "Behind the Story"

    def test_preserves_internal_hyphens(self):
        assert sanitize_filename("High-Altitude Hijacking") == "High-Altitude Hijacking"

    def test_strips_surrounding_quotes(self):
        assert sanitize_filename('"A Girl\'s Gotta Eat"') == "A Girl's Gotta Eat"


class TestFormatRuntime:
    def test_minutes_only(self):
        assert format_runtime(48 * 60) == "48m"

    def test_hours_and_minutes(self):
        assert format_runtime(3 * 3600 + 1 * 60) == "3h 1m"

    def test_zero(self):
        assert format_runtime(0) == "unknown"

    def test_negative(self):
        assert format_runtime(-100) == "unknown"

    def test_exact_hour(self):
        assert format_runtime(7200) == "2h 0m"


class TestMovieNaming:
    def test_folder_name(self):
        assert movie_folder_name("Oppenheimer", 2023) == "Oppenheimer (2023)"

    def test_folder_name_with_colon(self):
        assert movie_folder_name("Top Gun: Maverick", 2022) == "Top Gun Maverick (2022)"

    def test_file_name(self):
        assert movie_file_name("Oppenheimer", 2023) == "Oppenheimer (2023).mkv"

    def test_file_name_custom_ext(self):
        assert movie_file_name("Oppenheimer", 2023, ".mp4") == "Oppenheimer (2023).mp4"

    def test_folder_name_with_edition(self):
        assert movie_folder_name("King Kong", 2005, edition="Extended Cut") == "King Kong (2005) {edition-Extended Cut}"

    def test_file_name_with_edition(self):
        assert movie_file_name("King Kong", 2005, edition="Theatrical Cut") == "King Kong (2005) {edition-Theatrical Cut}.mkv"

    def test_folder_name_no_edition(self):
        assert movie_folder_name("King Kong", 2005) == "King Kong (2005)"

    def test_file_name_no_edition(self):
        assert movie_file_name("King Kong", 2005) == "King Kong (2005).mkv"


class TestShowNaming:
    def test_show_folder_name(self):
        assert show_folder_name("A Perfect Planet", 2021) == "A Perfect Planet (2021)"

    def test_season_folder_name(self):
        assert season_folder_name(1) == "Season 01"
        assert season_folder_name(0) == "Season 00"
        assert season_folder_name(10) == "Season 10"

    def test_episode_file_name(self):
        result = episode_file_name("A Perfect Planet", 2021, 1, 1, "Volcano")
        assert result == "A Perfect Planet (2021) - s01e01 - Volcano.mkv"

    def test_episode_file_name_with_colon(self):
        result = episode_file_name(
            "X-Men: The Animated Series", 1992, 1, 3, "Enter Magneto"
        )
        assert result == "X-Men The Animated Series (1992) - s01e03 - Enter Magneto.mkv"


class TestBuildPaths:
    def test_movie_paths_with_extras(self):
        paths = build_movie_paths("Oppenheimer", 2023, include_extras=True)
        assert paths[0] == "\\Movies\\Oppenheimer (2023)\\"
        assert "\\Movies\\Oppenheimer (2023)\\Featurettes\\" in paths
        assert "\\Movies\\Oppenheimer (2023)\\Trailers\\" in paths
        assert len(paths) > 1

    def test_movie_paths_without_extras(self):
        paths = build_movie_paths("Oppenheimer", 2023, include_extras=False)
        assert paths == ["\\Movies\\Oppenheimer (2023)\\"]

    def test_show_paths(self):
        paths = build_show_paths(
            "A Perfect Planet", 2021, [0, 1], include_extras=False
        )
        assert paths == [
            "\\TV Shows\\A Perfect Planet (2021)\\Season 00\\",
            "\\TV Shows\\A Perfect Planet (2021)\\Season 01\\",
        ]

    def test_show_paths_with_extras(self):
        paths = build_show_paths(
            "A Perfect Planet", 2021, [1], include_extras=True
        )
        assert "\\TV Shows\\A Perfect Planet (2021)\\Season 01\\" in paths
        assert "\\TV Shows\\A Perfect Planet (2021)\\Featurettes\\" in paths
