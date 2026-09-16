"""Tests for the config module."""

import os
from pathlib import Path
from unittest import mock

from riplex.config import (
    get_api_key,
    get_archive_root,
    get_output_root,
    get_rip_output,
    load_config,
)


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
                "riplex.config.load_config",
                return_value={"tmdb_api_key": "cfg_key"},
            ):
                # Clear TMDB_API_KEY if present
                os.environ.pop("TMDB_API_KEY", None)
                assert get_api_key(None) == "cfg_key"

    def test_returns_empty_when_nothing_set(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch(
                "riplex.config.load_config", return_value={}
            ):
                os.environ.pop("TMDB_API_KEY", None)
                assert get_api_key(None) == ""


class TestGetMakemkvListTimeout:
    def test_defaults_to_120(self):
        with mock.patch("riplex.config.load_config", return_value={}):
            from riplex.config import get_makemkv_list_timeout

            assert get_makemkv_list_timeout() == 120

    def test_reads_config_override(self):
        with mock.patch(
            "riplex.config.load_config",
            return_value={"makemkv_list_timeout": 300},
        ):
            from riplex.config import get_makemkv_list_timeout

            assert get_makemkv_list_timeout() == 300

    def test_bad_value_falls_back_to_default(self):
        with mock.patch(
            "riplex.config.load_config",
            return_value={"makemkv_list_timeout": "not-a-number"},
        ):
            from riplex.config import get_makemkv_list_timeout

            assert get_makemkv_list_timeout() == 120


class TestOutputPaths:
    def test_configured_roots_expand_user_home(self):
        config = {
            "output_root": "~/Videos",
            "rip_output": "~/Riplex/Raw",
            "archive_root": "~/Riplex/Archive",
        }
        with mock.patch.dict(os.environ, {"PLEX_ROOT": ""}, clear=False):
            with mock.patch("riplex.config.load_config", return_value=config):
                assert get_output_root() == str(Path.home() / "Videos")
                assert get_rip_output() == str(Path.home() / "Riplex" / "Raw")
                assert get_archive_root() == str(Path.home() / "Riplex" / "Archive")

    def test_cli_rip_output_is_expanded_and_wins(self):
        with mock.patch(
            "riplex.config.load_config",
            return_value={"rip_output": "/configured/rips"},
        ):
            assert get_rip_output("~/override") == str(Path.home() / "override")
