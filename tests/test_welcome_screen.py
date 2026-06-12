from riplex_app.screens.welcome import has_complete_config, should_show_setup


class TestHasCompleteConfig:
    def test_requires_api_key_output_root_and_rip_output(self):
        assert has_complete_config({}) is False
        assert has_complete_config({"tmdb_api_key": "key"}) is False
        assert has_complete_config({"tmdb_api_key": "key", "output_root": "E:/Media"}) is False
        assert has_complete_config({
            "tmdb_api_key": "key",
            "output_root": "E:/Media",
            "rip_output": "E:/Media/_MakeMKV",
        }) is True

    def test_archive_root_is_optional(self):
        assert has_complete_config({
            "tmdb_api_key": "key",
            "output_root": "E:/Media",
            "rip_output": "E:/Media/_MakeMKV",
            "archive_root": "",
        }) is True


class TestShouldShowSetup:
    def test_shows_setup_for_incomplete_config(self):
        assert should_show_setup({"tmdb_api_key": "key"}, {}) is True

    def test_hides_setup_for_complete_config(self):
        config = {
            "tmdb_api_key": "key",
            "output_root": "E:/Media",
            "rip_output": "E:/Media/_MakeMKV",
        }
        assert should_show_setup(config, {}) is False

    def test_can_force_show_setup_for_editing(self):
        config = {
            "tmdb_api_key": "key",
            "output_root": "E:/Media",
            "rip_output": "E:/Media/_MakeMKV",
        }
        assert should_show_setup(config, {"_show_setup": True}) is True