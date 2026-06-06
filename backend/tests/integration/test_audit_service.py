"""Integration (echte Postgres, testcontainers): Audit-Hash-Kette + Append-only.

Beweist gegen ein echtes Schema (security.md §4):
* :meth:`AuditService.record` baut eine verkettete, lückenlose Kette (Advisory-Lock,
  ``prev_hash``-Verkettung) → :meth:`verify_chain` ``valid``.
* DB-seitige Append-only-Durchsetzung: UPDATE/DELETE auf ``audit_entry`` → Fehler
  (Trigger ``audit_entry_append_only``, Migration 0005).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.audit.actions import AuditAction
from app.modules.audit.models import AuditEntry
from app.modules.audit.service import AuditService

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


async def test_record_builds_verifiable_chain(session: AsyncSession) -> None:
    svc = AuditService(session)
    first = await svc.record(actor="admin-1", action=AuditAction.LOGIN)
    second = await svc.record(
        actor="admin-1",
        action=AuditAction.CONFIG_ACTIVATION,
        target_type="flow_version",
        target_id="fv-1",
        data={"active": True},
    )
    third = await svc.record(actor=None, action=AuditAction.EXPORT, target_id="app-9")
    await session.commit()

    assert first.prev_hash is None
    assert second.prev_hash == first.hash
    assert third.prev_hash == second.hash

    result = await svc.verify_chain()
    assert result.valid is True
    assert result.checked == 3
    assert result.broken_at is None


async def test_chain_orders_by_generation(session: AsyncSession) -> None:
    svc = AuditService(session)
    for i in range(5):
        await svc.record(actor=f"u-{i}", action=AuditAction.LOGIN)
    await session.commit()

    ids = (
        (await session.execute(select(AuditEntry.id).order_by(AuditEntry.id)))
        .scalars()
        .all()
    )
    assert ids == sorted(ids)
    assert (await svc.verify_chain()).valid is True


async def test_query_filters_by_action(session: AsyncSession) -> None:
    svc = AuditService(session)
    await svc.record(actor="a", action=AuditAction.LOGIN)
    await svc.record(actor="a", action=AuditAction.EXPORT, target_id="x")
    await session.commit()

    page = await svc.query(action=str(AuditAction.EXPORT))
    assert page.total == 1
    assert page.items[0].target_id == "x"


async def test_update_is_rejected(session: AsyncSession, engine: Engine) -> None:
    await AuditService(session).record(actor="a", action=AuditAction.LOGIN)
    await session.commit()

    with pytest.raises(DBAPIError, match="append-only"):
        async with session.begin():
            await session.execute(text("UPDATE audit_entry SET actor = 'evil'"))


async def test_delete_is_rejected(session: AsyncSession, engine: Engine) -> None:
    await AuditService(session).record(actor="a", action=AuditAction.LOGIN)
    await session.commit()

    with pytest.raises(DBAPIError, match="append-only"):
        async with session.begin():
            await session.execute(text("DELETE FROM audit_entry"))
