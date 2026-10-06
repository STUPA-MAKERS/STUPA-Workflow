"""Fixtures of the protocol integration tests.

The API tests reuse the app wiring and the session factory of the meeting tests:
``api`` gives the real app with an admin principal, ``maker`` a session factory on
the migrated test database.
"""

from tests.integration.modules.livevote.conftest import api, maker

__all__ = ["api", "maker"]
