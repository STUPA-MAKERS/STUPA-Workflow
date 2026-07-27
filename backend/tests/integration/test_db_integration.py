"""Integration tests against a real database that testcontainers starts.

The tests prove that the async SQLAlchemy engine connects to a real Postgres and runs a
query. The default test run skips them through the `integration` marker. The CI stage
`be-integration` runs `-m integration` with Docker. See testing.md section 5: this
repository uses no database mocks.
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
