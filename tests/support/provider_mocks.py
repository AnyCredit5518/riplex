"""Install scenario-driven fakes for every external boundary the GUI hits.

The wizard talks to three outside systems: makemkv (disc hardware), TMDb
(metadata), and dvdcompare (disc structure). Plus it reads the on-disk config
and probes for installed tools. ``install()`` patches all of them from a
loaded :class:`~tests.support.fixtures.Scenario` so a flow test never touches
the network, the filesystem config, or a real optical drive.

Patching strategy:

* Provider classes (``TmdbProvider``, ``DiscProvider``) are patched *on the
  class object*, so every ``from ... import X`` alias in the screens sees the
  fake regardless of which module imported it.
* Free functions imported by name into a screen module (``run_rip``,
  ``makemkv_preflight``, ``_convert_release``, the welcome tool-finders) are
  patched in that screen's namespace.
* ``riplex.config.load_config`` is patched at the source; the getters resolve
  it via their module globals, so every ``get_api_key`` / ``get_rip_output``
  caller picks up the fake config.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from riplex.disc.makemkv import RipResult
from riplex.disc.provider import DiscProvider
from riplex.metadata.sources.tmdb import TmdbProvider

from .fixtures import Scenario


# ---------------------------------------------------------------------------
# Fake dvdcompare film / release object graph
# ---------------------------------------------------------------------------

@dataclass
class FakeRelease:
    name: str
    discs: list[Any] = field(default_factory=lambda: [object()])


@dataclass
class FakeFilm:
    title: str
    film_id: int
    releases: list[FakeRelease] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Recorder returned to tests
# ---------------------------------------------------------------------------

@dataclass
class MockProviders:
    scenario: Scenario
    tmdb_searches: list[str] = field(default_factory=list)
    rips: list[int] = field(default_factory=list)
    disc_reads: list[int] = field(default_factory=list)


def install(
    monkeypatch,
    scenario: Scenario,
    *,
    config: dict | None = None,
    rip_success: bool = True,
    tmdb_results: list | None = None,
    tmdb_error: Exception | None = None,
    dvdcompare_error: Exception | None = None,
    preflight_available: bool = True,
    existing_session: Any = None,
) -> MockProviders:
    """Patch every external boundary from *scenario*. Returns a recorder."""
    rec = MockProviders(scenario=scenario)

    _install_config(monkeypatch, config)
    _install_tmdb(monkeypatch, scenario, rec, tmdb_results, tmdb_error)
    _install_dvdcompare(monkeypatch, scenario, rec, dvdcompare_error)
    _install_makemkv(monkeypatch, scenario, rec, rip_success, preflight_available)
    _install_manifest(monkeypatch, existing_session)
    return rec


# ---------------------------------------------------------------------------
# config + tool discovery
# ---------------------------------------------------------------------------

# NOTE: the config roots MUST point at throwaway temp locations. Screens and
# commands derive real filesystem write targets from ``rip_output`` /
# ``output_root`` via ``build_rip_path`` — e.g. the orchestrate flow writes a
# ``_riplex_session.json`` session marker and rip snapshots. If these pointed
# at a real media library, running the tests would litter (and could overwrite)
# it. Every test therefore gets a fresh temp sandbox.

_STATIC_CONFIG = {
    "tmdb_api_key": "test-key",
}


def _sandbox_config() -> dict:
    """Config whose output/rip/archive roots live in a throwaway temp dir."""
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="riplex-test-"))
    return {
        **_STATIC_CONFIG,
        "output_root": str(root / "Media"),
        "rip_output": str(root / "Media" / "_MakeMKV"),
        "archive_root": str(root / "Media" / "_MakeMKV" / "_archive"),
    }


def _install_config(monkeypatch, config: dict | None) -> None:
    cfg = {**_sandbox_config(), **(config or {})}
    import riplex.config as config_mod

    monkeypatch.setattr(config_mod, "load_config", lambda: dict(cfg))

    # Welcome pings TMDb + dvdcompare over httpx on entry — stub the network
    # so no real request fires when the driver lands on the welcome screen.
    import httpx

    class _FakeResp:
        status_code = 200

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResp())

    # Welcome imports the tool-finders by name — patch its namespace so the
    # status checks pass without real tools installed.
    try:
        import riplex_app.screens.welcome as welcome_mod

        monkeypatch.setattr(welcome_mod, "find_makemkvcon", lambda: Path("makemkvcon"))
        monkeypatch.setattr(welcome_mod, "find_ffprobe", lambda: Path("ffprobe"))
        monkeypatch.setattr(welcome_mod, "find_mkvmerge", lambda: Path("mkvmerge"), raising=False)
        monkeypatch.setattr(welcome_mod, "check_for_update", lambda: None)
        # find_mkvmerge is imported lazily inside build(); patch the source too.
        import riplex.splitter as splitter_mod

        monkeypatch.setattr(splitter_mod, "find_mkvmerge", lambda: Path("mkvmerge"))
    except ImportError:  # pragma: no cover
        pass


# ---------------------------------------------------------------------------
# TMDb
# ---------------------------------------------------------------------------

def _install_tmdb(monkeypatch, scenario, rec, tmdb_results, tmdb_error) -> None:
    results = tmdb_results if tmdb_results is not None else scenario.search_results()

    async def _search(self, query, *, year=None, media_type="auto"):
        rec.tmdb_searches.append(query)
        if tmdb_error is not None:
            raise tmdb_error
        return list(results)

    async def _get_movie_detail(self, source_id):
        return scenario.movie_detail()

    async def _get_show_detail(self, source_id, *, include_specials=True):
        return scenario.show_detail()

    async def _close(self):
        return None

    monkeypatch.setattr(TmdbProvider, "__init__", lambda self, *a, **k: None)
    monkeypatch.setattr(TmdbProvider, "search", _search)
    monkeypatch.setattr(TmdbProvider, "get_movie_detail", _get_movie_detail)
    monkeypatch.setattr(TmdbProvider, "get_show_detail", _get_show_detail)
    monkeypatch.setattr(TmdbProvider, "close", _close, raising=False)


# ---------------------------------------------------------------------------
# dvdcompare
# ---------------------------------------------------------------------------

def _install_dvdcompare(monkeypatch, scenario, rec, dvdcompare_error) -> None:
    release = FakeRelease(name=scenario.release_name() or "Default Release")
    film = FakeFilm(title=scenario.title, film_id=12345, releases=[release])

    async def _fetch_film(self, title, disc_format, *, year=None):
        if dvdcompare_error is not None:
            raise dvdcompare_error
        return film

    async def _fetch_film_by_id(self, film_id):
        if dvdcompare_error is not None:
            raise dvdcompare_error
        return film

    async def _fetch_film_cached(self, title, disc_format, *, year=None):
        if dvdcompare_error is not None:
            raise dvdcompare_error
        return film

    async def _close(self):
        return None

    monkeypatch.setattr(DiscProvider, "__init__", lambda self, *a, **k: None)
    monkeypatch.setattr(DiscProvider, "fetch_film", _fetch_film)
    monkeypatch.setattr(DiscProvider, "fetch_film_by_id", _fetch_film_by_id)
    monkeypatch.setattr(DiscProvider, "_fetch_film_cached", _fetch_film_cached, raising=False)
    monkeypatch.setattr(DiscProvider, "close", _close, raising=False)

    # The release screen converts a picked release into PlannedDiscs via a
    # module-level helper — return the scenario's discs so the flow proceeds
    # deterministically without a real dvdcompare page.
    planned = scenario.planned_discs()
    try:
        import riplex_app.screens.release as release_mod

        monkeypatch.setattr(
            release_mod, "_convert_release", lambda _release: [_clone_disc(d) for d in planned]
        )
    except ImportError:  # pragma: no cover
        pass


def _clone_disc(disc):
    import copy

    return copy.deepcopy(disc)


# ---------------------------------------------------------------------------
# makemkv
# ---------------------------------------------------------------------------

def _install_makemkv(monkeypatch, scenario, rec, rip_success, preflight_available) -> None:
    from riplex.disc.makemkv import MakeMKV, MakeMKVPreflight

    preflight = (
        scenario.preflight()
        if preflight_available
        else MakeMKVPreflight(exe=None, version="", available=False,
                              error="makemkvcon not found")
    )

    def _drive_list(self):
        return [scenario.drive_info()]

    def _run_disc_info(drive_index, *, makemkvcon=None):
        rec.disc_reads.append(drive_index)
        return scenario.disc_info(scenario.disc_numbers[0] if scenario.disc_numbers else None)

    def _run_rip(drive, title_index, output_dir, *, makemkvcon=None,
                 progress_callback=None, cancel_event=None):
        rec.rips.append(title_index)
        return RipResult(
            title_index=title_index,
            success=rip_success,
            output_file=str(Path(output_dir) / f"title_{title_index:02d}.mkv"),
            error_message="" if rip_success else "simulated rip failure",
        )

    # MakeMKV.drive_list is a method on the shared class object.
    monkeypatch.setattr(MakeMKV, "drive_list", _drive_list)

    # These are imported by name into individual screen modules.
    for mod_name, names in {
        "riplex_app.screens.disc_detection": {
            "makemkv_preflight": lambda mk=None: preflight,
            "run_disc_info": _run_disc_info,
        },
        "riplex_app.screens.progress": {"run_rip": _run_rip},
        "riplex_app.screens.disc_swap": {
            "run_disc_info": _run_disc_info,
            "run_drive_list": lambda *a, **k: [scenario.drive_info()],
            "eject_disc": lambda *a, **k: None,
        },
    }.items():
        try:
            mod = __import__(mod_name, fromlist=["_"])
        except ImportError:  # pragma: no cover
            continue
        for attr, value in names.items():
            monkeypatch.setattr(mod, attr, value, raising=False)


# ---------------------------------------------------------------------------
# manifest / resume
# ---------------------------------------------------------------------------

def _install_manifest(monkeypatch, existing_session) -> None:
    import riplex.manifest as manifest_mod

    monkeypatch.setattr(
        manifest_mod, "find_existing_session", lambda *a, **k: existing_session,
        raising=False,
    )
