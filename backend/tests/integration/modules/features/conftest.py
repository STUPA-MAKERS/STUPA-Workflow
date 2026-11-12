"""Fixtures of the feature-switch integration tests (real Postgres).

The tests use the app, the session maker and the clean tables of the ticket tests: each
test starts without principals and without a site-config version.
"""

from __future__ import annotations

from tests.integration.modules.tickets.conftest import api, clean, maker, settings

__all__ = ["api", "clean", "maker", "settings"]
