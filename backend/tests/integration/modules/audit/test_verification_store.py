"""Integration (real Postgres): stored audit-chain checks (Z6/O8).

`verify_and_store` writes one `audit_verification` row per check and commits it. A
tampered chain stores the first break. The store keeps the newest rows only. The table
CHECKs reject an unknown trigger, an unknown reason and a valid row with a reason.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.audit.actions import AuditAction
from app.modules.audit.models import AuditVerification
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


async def test_store_a_valid_check(session: AsyncSession) -> None:
    svc = AuditService(session)
    await svc.record(actor="a", action=AuditAction.LOGIN)
    await svc.record(actor="a", action=AuditAction.EXPORT, target_id="x")
    await session.commit()

    row = await svc.verify_and_store(trigger="manual", triggered_by="admin-1")

    stored = await session.get(AuditVerification, row.id)
    assert stored is not None
    assert stored.valid is True
    assert stored.checked == 2
    assert stored.broken_at is None
    assert stored.reason is None
    assert stored.trigger == "manual"
    assert stored.triggered_by == "admin-1"
    assert stored.finished_at is not None and stored.finished_at >= stored.started_at
    latest = await svc.latest_verification()
    assert latest is not None and latest.id == row.id


async def test_store_the_first_break_of_a_tampered_chain(
    session: AsyncSession, engine: Engine
) -> None:
    svc = AuditService(session)
    first = await svc.record(actor="a", action=AuditAction.LOGIN)
    await svc.record(actor="b", action=AuditAction.LOGIN)
    await session.commit()
    # Tamper past the append-only trigger, as a superuser with direct DB access could.
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        conn.execute(
            text("UPDATE audit_entry SET actor = 'evil' WHERE id = :i"), {"i": first.id}
        )

    row = await svc.verify_and_store(trigger="cron")

    assert row.valid is False
    assert row.checked == 0
    assert row.broken_at == first.id
    assert row.reason == "hash_mismatch"
    assert row.triggered_by is None


async def test_latest_is_none_before_the_first_check(session: AsyncSession) -> None:
    assert await AuditService(session).latest_verification() is None


async def test_the_store_keeps_only_the_newest_rows(session: AsyncSession) -> None:
    svc = AuditService(session)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(5):
        session.add(
            AuditVerification(
                started_at=base + timedelta(days=i),
                finished_at=base + timedelta(days=i),
                valid=True,
                checked=i,
                trigger="cron",
            )
        )
    await session.commit()

    row = await svc.verify_and_store(trigger="restore", triggered_by="admin-1", keep=3)

    count = await session.scalar(select(func.count()).select_from(AuditVerification))
    assert count == 3
    kept = (
        await session.scalars(
            select(AuditVerification.checked)
            .where(AuditVerification.id != row.id)
            .order_by(AuditVerification.started_at)
        )
    ).all()
    assert kept == [3, 4]  # the two newest seeded rows survive next to the new one
    latest = await svc.latest_verification()
    assert latest is not None and latest.trigger == "restore"


@pytest.mark.parametrize(
    ("trigger", "valid", "reason"),
    [
        ("nightly", True, None),  # unknown trigger
        ("cron", False, "deleted_row"),  # unknown reason
        ("cron", True, "hash_mismatch"),  # a valid chain has no reason
        ("cron", False, None),  # a broken chain names its reason
    ],
)
def test_table_checks_reject_bad_rows(
    engine: Engine, trigger: str, valid: bool, reason: str | None
) -> None:
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO audit_verification (started_at, valid, checked, reason, trigger) "
                "VALUES (now(), :v, 0, :r, :t)"
            ),
            {"v": valid, "r": reason, "t": trigger},
        )
