"""The conversion of the seeded vendored CD logos on a real Postgres 16.

The seed writes vendored rows only. `convert_builtin_cd_logos` must turn every
one of them into an upload with the same slot and position, rename the seed name
``StuPa`` to ``STUPA``, write one audit entry per variant, and find nothing to do
on a second run. The test restores the seed state afterwards, because the
database lives for the whole session.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.cd_builtin.convert import convert_builtin_cd_logos
from tests._support.files_fakes import FakeStorage

pytestmark = pytest.mark.integration

_LOGOS = (
    'SELECT v.key, l.slot, l."position", l.vendored_name, l.file_name, l.mime '
    "FROM cd_variant_logo l JOIN cd_variant v ON v.id = l.variant_id "
    'ORDER BY v.key, l.slot, l."position"'
)

_RESTORE = (
    "UPDATE cd_variant_logo SET vendored_name = substring(file_name from '^(.*)\\.svg$'), "
    "object_key = NULL, file_name = NULL, mime = NULL, size = NULL "
    "WHERE vendored_name IS NULL AND object_key LIKE 'cd-logos/%' AND mime = 'image/svg+xml'",
    "UPDATE cd_variant SET name = 'StuPa' WHERE key = 'stupa'",
)


@pytest.fixture
async def maker(migrated: tuple[str, str]) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    try:
        yield async_sessionmaker(eng, expire_on_commit=False)
    finally:
        await eng.dispose()


async def test_conversion_of_the_seed(
    engine: Engine, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Convert the seed: slot and position stay, and the vendored name becomes the file name."""
    with engine.connect() as conn:
        before = [tuple(r) for r in conn.execute(text(_LOGOS)).fetchall()]
    storage = FakeStorage()
    try:
        async with maker() as session:
            first = await convert_builtin_cd_logos(session, storage)
        async with maker() as session:
            second = await convert_builtin_cd_logos(session, storage)
        with engine.connect() as conn:
            after = [tuple(r) for r in conn.execute(text(_LOGOS)).fetchall()]
            name = conn.execute(
                text("SELECT name FROM cd_variant WHERE key = 'stupa'")
            ).scalar_one()
            audits = conn.execute(
                text(
                    "SELECT count(*) FROM audit_entry WHERE actor = 'system' "
                    "AND target_type = 'cd_variant' "
                    "AND data->>'reason' = 'builtin_cd_logos_converted'"
                )
            ).scalar_one()
    finally:
        with engine.begin() as conn:
            for stmt in _RESTORE:
                conn.execute(text(stmt))

    assert first.logos == len(before) == 9
    assert first.variants == 5 and first.renamed == 1
    assert second.logos == 0 and second.variants == 0
    assert len(storage.put_calls) == 9
    assert name == "STUPA"
    assert audits >= 5
    assert [(k, s, p, None, f"{v}.svg", "image/svg+xml") for k, s, p, v, _, _ in before] == after
