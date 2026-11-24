"""Fixtures of the web push integration tests (real Postgres).

The tests use the app, the session maker and the clean tables of the ticket tests: each
test starts without principals, so without devices and push switches either.
"""

from __future__ import annotations

from tests.integration.modules.tickets.conftest import api, clean, maker, settings

__all__ = ["api", "clean", "maker", "settings"]
