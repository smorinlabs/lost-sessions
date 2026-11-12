"""Shared fixtures for the whole test suite."""

from hypothesis import settings

# WL-013 — Hypothesis property tests run under load on the CI matrix; the
# default 200ms per-example deadline flakes there. Disable it so a slow shared
# runner never fails a correctness property. Registered once for the suite.
settings.register_profile("lost_sessions", deadline=None)
settings.load_profile("lost_sessions")
