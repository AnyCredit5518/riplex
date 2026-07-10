"""Helpers for driving the riplex CLI end-to-end in-process.

Runs the real argparse parser and async command dispatch (`_run`) so tests
exercise argument parsing, command routing, and command logic together — the
CLI equivalent of the GUI ``WizardDriver``. External boundaries (config, TMDb,
dvdcompare) are stubbed by the test via monkeypatch.
"""

from __future__ import annotations

import asyncio

from riplex_cli.main import _build_parser, _run

_DEFAULT_CONFIG = {
    "tmdb_api_key": "test-key",
    "output_root": "E:/Media",
    "rip_output": "E:/Media/_MakeMKV",
    "archive_root": "E:/Media/_MakeMKV/_archive",
}


def install_cli_mocks(monkeypatch, config: dict | None = None) -> dict:
    """Stub config + provider construction so commands run offline.

    ``load_config`` is patched at the source (getters resolve it via module
    globals), and the provider classes' ``__init__``/``close`` are neutered so
    ``TmdbProvider(api_key=...)`` never validates a key or opens a client. Tests
    still mock the actual lookup functions (``lookup_metadata`` etc.) to supply
    data.
    """
    cfg = {**_DEFAULT_CONFIG, **(config or {})}
    import riplex.config as config_mod

    monkeypatch.setattr(config_mod, "load_config", lambda: dict(cfg))

    from riplex.metadata.sources.tmdb import TmdbProvider

    async def _aclose(self):
        return None

    monkeypatch.setattr(TmdbProvider, "__init__", lambda self, *a, **k: None)
    monkeypatch.setattr(TmdbProvider, "close", _aclose, raising=False)

    try:
        from riplex.disc.provider import DiscProvider

        monkeypatch.setattr(DiscProvider, "__init__", lambda self, *a, **k: None)
        monkeypatch.setattr(DiscProvider, "close", _aclose, raising=False)
    except ImportError:  # pragma: no cover
        pass

    return cfg


def parse_args(argv):
    """Parse *argv* with the real CLI parser, returning the Namespace."""
    return _build_parser().parse_args(list(argv))


def run_command(argv, *, auto: bool = True) -> int:
    """Run a CLI command end-to-end (real parser + dispatch) and return its
    exit code. Output is captured by pytest's ``capsys``.

    ``auto=True`` puts the shared UI into non-interactive mode so prompts fall
    back to their defaults instead of blocking on stdin.
    """
    from riplex.ui import set_auto_mode

    set_auto_mode(auto)
    args = parse_args(argv)
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run(args))
    finally:
        loop.close()
        set_auto_mode(False)
