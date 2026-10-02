"""Integration (real Postgres): stored audit-chain checks (Z6/O8).

`verify_and_store` writes one `audit_verification` row per check and commits it. A
tampered chain stores the first break. The store keeps the newest rows, every failed
check and the newest check of each trigger. A manual run refuses while another check
holds the lock and inside the cooldown. The table CHECKs reject an unknown trigger, an
unknown reason and a valid row with a reason.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.audit.actions import AuditAction
from app.modules.audit.models import VERIFICATION_KEEP, AuditVerification
from app.modules.audit.service import _VERIFY_LOCK_KEY, AuditService
from app.shared.errors import ConflictError, RateLimitedError

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


async def test_many_manual_runs_keep_a_failed_cron_check(session: AsyncSession) -> None:
    svc = AuditService(session)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    failed = AuditVerification(
        started_at=base,
        finished_at=base,
        valid=False,
        checked=3,
        broken_at=4,
        reason="hash_mismatch",
        trigger="cron",
    )
    restore = AuditVerification(
        started_at=base + timedelta(days=1),
        finished_at=base + timedelta(days=1),
        valid=True,
        checked=9,
        trigger="restore",
        triggered_by="admin-1",
    )
    session.add_all([failed, restore])
    await session.commit()

    for _ in range(VERIFICATION_KEEP + 1):
        await svc.verify_and_store(trigger="manual", triggered_by="reader")

    ids = set(await session.scalars(select(AuditVerification.id)))
    assert failed.id in ids  # the failed check is evidence and stays
    assert restore.id in ids  # the newest check of its trigger stays
    manual = await session.scalar(
        select(func.count())
        .select_from(AuditVerification)
        .where(AuditVerification.trigger == "manual")
    )
    assert manual == VERIFICATION_KEEP
    assert len(ids) == VERIFICATION_KEEP + 2


async def test_the_prune_keeps_old_failed_checks_and_drops_old_valid_ones(
    session: AsyncSession,
) -> None:
    svc = AuditService(session)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [
        AuditVerification(
            started_at=base + timedelta(days=i),
            finished_at=base + timedelta(days=i),
            valid=valid,
            checked=i,
            broken_at=None if valid else 1,
            reason=None if valid else "prev_hash_mismatch",
            trigger="cron",
        )
        for i, valid in enumerate([False, True, False, True, True, True])
    ]
    session.add_all(rows)
    await session.commit()

    await svc.prune_verifications(keep=2)
    await session.commit()

    kept = (
        await session.scalars(
            select(AuditVerification.checked).order_by(AuditVerification.started_at)
        )
    ).all()
    assert kept == [0, 2, 4, 5]


async def test_a_manual_run_refuses_inside_the_cooldown(session: AsyncSession) -> None:
    svc = AuditService(session)
    first = await svc.run_manual_verification(triggered_by="admin-1")
    assert first.trigger == "manual"

    with pytest.raises(RateLimitedError):
        await svc.run_manual_verification(triggered_by="admin-1")

    # The cron does not wait for the cooldown.
    cron = await svc.verify_and_store(trigger="cron")
    assert cron.trigger == "cron"
    count = await session.scalar(select(func.count()).select_from(AuditVerification))
    assert count == 2


async def test_a_manual_run_refuses_while_a_check_holds_the_lock(
    session: AsyncSession, engine: Engine
) -> None:
    with engine.connect() as conn:
        conn.execute(text(f"SELECT pg_advisory_lock({_VERIFY_LOCK_KEY})"))
        try:
            with pytest.raises(ConflictError):
                await AuditService(session).run_manual_verification(triggered_by="admin-1")
        finally:
            conn.execute(text(f"SELECT pg_advisory_unlock({_VERIFY_LOCK_KEY})"))
    count = await session.scalar(select(func.count()).select_from(AuditVerification))
    assert count == 0
    # The refused run released its transaction; a new run gets the lock.
    row = await AuditService(session).run_manual_verification(triggered_by="admin-1")
    assert row.valid is True


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
