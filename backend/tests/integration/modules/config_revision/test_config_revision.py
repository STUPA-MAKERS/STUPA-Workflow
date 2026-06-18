"""Integration (echte Postgres, testcontainers): config_revision (#config-versioning).

Beweist gegen ein echtes Schema:
* **Append-only**: UPDATE/DELETE/TRUNCATE auf ``config_revision`` → Fehler (Trigger
  ``config_revision_append_only``, Migration 0034) — eine Version ist nie löschbar.
* :meth:`ConfigRevisionService.record` verkettet Snapshots (version+1, prev_revision_id)
  und schreibt den verlinkten Audit-Eintrag; :meth:`diff` rechnet den Feld-Diff.
* Migration 0034 seedet die Permission ``audit.revert`` an die ``admin``-Rolle.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.audit.actions import AuditAction
from app.modules.config_revision.service import (
    ENTITY_FLOW,
    ENTITY_FORM,
    GLOBAL_ID,
    ConfigRevisionService,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def session(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def _seed_one(session: AsyncSession) -> None:
    await ConfigRevisionService(session).record(
        entity_type=ENTITY_FLOW,
        entity_id=GLOBAL_ID,
        snapshot={"a": 1},
        actor="admin",
        action=AuditAction.CONFIG_ACTIVATION,
    )
    await session.commit()


async def test_update_is_rejected(session: AsyncSession) -> None:
    await _seed_one(session)
    with pytest.raises(DBAPIError, match="append-only"):
        async with session.begin():
            await session.execute(text("UPDATE config_revision SET snapshot = '{}'"))


async def test_delete_is_rejected(session: AsyncSession) -> None:
    await _seed_one(session)
    with pytest.raises(DBAPIError, match="append-only"):
        async with session.begin():
            await session.execute(text("DELETE FROM config_revision"))


async def test_truncate_is_rejected(session: AsyncSession) -> None:
    await _seed_one(session)
    with pytest.raises(DBAPIError, match="append-only"):
        async with session.begin():
            await session.execute(text("TRUNCATE config_revision"))


async def test_record_chains_versions_and_diffs(session: AsyncSession) -> None:
    svc = ConfigRevisionService(session)
    r1 = await svc.record(
        entity_type=ENTITY_FORM,
        entity_id="t-int",
        snapshot={"fields": [{"key": "a", "type": "text"}]},
        actor="admin",
    )
    await session.commit()
    r2 = await svc.record(
        entity_type=ENTITY_FORM,
        entity_id="t-int",
        snapshot={"fields": [{"key": "a", "type": "number"}]},
        actor="admin",
    )
    await session.commit()

    assert r2.version == r1.version + 1
    assert r2.prev_revision_id == r1.id
    head = await svc.head(ENTITY_FORM, "t-int")
    assert head is not None and head.id == r2.id
    diff = await svc.diff(r2)
    assert "field:a" in diff["changed"]


async def test_record_links_audit_entry_by_revision_id(session: AsyncSession) -> None:
    rev = await ConfigRevisionService(session).record(
        entity_type=ENTITY_FLOW,
        entity_id=GLOBAL_ID,
        snapshot={"x": 1},
        actor="admin",
        action=AuditAction.CONFIG_ACTIVATION,
    )
    await session.commit()
    linked = (
        await session.execute(
            text(
                "SELECT count(*) FROM audit_entry "
                "WHERE action = 'config_activation' AND data->>'revisionId' = :rid"
            ),
            {"rid": str(rev.id)},
        )
    ).scalar_one()
    assert linked == 1


def test_audit_revert_permission_seeded_to_admin(engine: Engine) -> None:
    with engine.connect() as conn:
        seeded = conn.execute(
            text(
                "SELECT count(*) FROM role_permission rp JOIN role r ON r.id = rp.role_id "
                "WHERE r.key = 'admin' AND rp.permission = 'audit.revert'"
            )
        ).scalar_one()
    assert seeded == 1
