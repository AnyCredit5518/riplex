"""Tests for shared log-path helpers."""

import logging
from pathlib import Path


def test_cli_log_path_uses_user_log_directory(tmp_path, monkeypatch):
    from riplex.log_path import get_cli_log_path

    monkeypatch.setattr(
        "riplex.log_path.user_log_dir", lambda app_name: str(tmp_path)
    )

    assert get_cli_log_path() == Path(tmp_path) / "riplex.log"


def test_setup_logging_creates_user_log_file(tmp_path, monkeypatch):
    from riplex_cli.formatting import setup_logging

    log_file = tmp_path / "logs" / "riplex.log"
    monkeypatch.setattr(
        "riplex_cli.formatting.get_cli_log_path", lambda: log_file
    )

    logger = logging.getLogger("riplex")
    existing_handlers = set(logger.handlers)
    try:
        assert setup_logging() == log_file
        assert log_file.exists()
    finally:
        for handler in set(logger.handlers) - existing_handlers:
            logger.removeHandler(handler)
            handler.close()