"""Integration: echte DB via testcontainers (testing.md §5 — keine DB-Mocks).

Beweist, dass die async SQLAlchemy-Engine gegen einen echten Postgres connecten und
queryn kann. Default-Lauf überspringt das (Marker `integration`); CI-Stage
`be-integration` läuft `-m integration` mit Docker.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration


async def test_engine_roundtrip(postgres_url: str) -> None:
    engine = create_async_engine(postgres_url, future=True)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            assert result.scalar_one() == 1
    finally:
        await engine.dispose()
