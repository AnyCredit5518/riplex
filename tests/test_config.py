"""Tests for the config module."""

import os
from unittest import mock

from plex_planner.config import get_api_key, load_config


class TestGetApiKey:
    def test_cli_value_wins(self):
        with mock.patch.dict(os.environ, {"TMDB_API_KEY": "env_key"}):
            assert get_api_key("cli_key") == "cli_key"

    def test_env_var_over_config(self):
        with mock.patch.dict(os.environ, {"TMDB_API_KEY": "env_key"}):
            assert get_api_key(None) == "env_key"

    def test_falls_back_to_config(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch(
                "plex_planner.config.load_config",
                return_value={"tmdb_api_key": "cfg_key"},
            ):
                # Clear TMDB_API_KEY if present
                os.environ.pop("TMDB_API_KEY", None)
                assert get_api_key(None) == "cfg_key"

    def test_returns_empty_when_nothing_set(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch(
                "plex_planner.config.load_config", return_value={}
            ):
                os.environ.pop("TMDB_API_KEY", None)
                assert get_api_key(None) == ""
