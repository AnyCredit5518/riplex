"""Integration-test package config: auto-tag everything here as integration.

Lets ``pytest -m integration`` (or ``-m "not integration"``) select or skip the
GUI flow suite without decorating each test.
"""

import pytest


def pytest_collection_modifyitems(items):
    for item in items:
        if "tests/integration/" in item.nodeid or "tests\\integration\\" in item.nodeid:
            item.add_marker(pytest.mark.integration)
