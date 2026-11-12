"""Shared fixtures for the whole test suite."""

import pytest
from hypothesis import settings

# WL-013 — Hypothesis property tests run under load on the CI matrix; the
# default 200ms per-example deadline flakes there. Disable it so a slow shared
# runner never fails a correctness property. Registered once for the suite.
settings.register_profile("lost_sessions", deadline=None)
settings.load_profile("lost_sessions")


@pytest.fixture(autouse=True)
def _no_third_party_plugins(monkeypatch):
    """Test mode (design 0006, TS-1): installed third-party plugins never load.

    The built-ins still load; a test that needs entry-point loading unsets it.
    """
    monkeypatch.setenv("LOST_SESSIONS_LOAD_PLUGINS", "")
