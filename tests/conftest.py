"""Shared pytest fixtures for the headless GUI integration tests."""

from __future__ import annotations

import pytest

from tests.support import provider_mocks, sync_runtime
from tests.support.driver import WizardDriver
from tests.support.fixtures import Scenario, load_scenario


@pytest.fixture
def gui(monkeypatch):
    """Return a factory that builds a fully-mocked ``WizardDriver``.

    Usage::

        def test_x(gui):
            d = gui("the-matrix-1999")          # movie scenario
            d = gui("chernobyl-2019", rip_success=False)

    All external boundaries (makemkv, TMDb, dvdcompare, config, network) are
    stubbed from the named scenario before the app is constructed, and all
    background threads run synchronously.
    """

    def _make(scenario: str | Scenario = "the-matrix-1999", **opts) -> WizardDriver:
        sc = scenario if isinstance(scenario, Scenario) else load_scenario(scenario)
        sync_runtime.install(monkeypatch)
        rec = provider_mocks.install(monkeypatch, sc, **opts)
        driver = WizardDriver()
        driver.mocks = rec  # type: ignore[attr-defined]
        driver.scenario = sc  # type: ignore[attr-defined]
        return driver

    return _make
