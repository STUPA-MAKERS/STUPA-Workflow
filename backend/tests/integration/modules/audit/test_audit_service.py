"""Integration (real Postgres, testcontainers): audit hash chain and append-only.

The tests prove these facts against a real schema (security.md §4). `AuditService.record`
builds a linked chain with no gap. It holds an advisory lock and links each entry
through `prev_hash`, so `verify_chain` reports `valid`. The DB itself enforces
append-only. An UPDATE or a DELETE on `audit_entry` raises an error through the trigger
`audit_entry_append_only` (migration 0005).
"""

from __future__ import annotations

import asyncio
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


async def test_query_cursor_keyset_paginates(session: AsyncSession) -> None:
    svc = AuditService(session)
    for _ in range(5):
        await svc.record(actor="a", action=AuditAction.LOGIN)
    await session.commit()

    first, has_more = await svc.query_cursor(limit=2)
    assert len(first) == 2 and has_more is True
    # newest first (id desc)
    assert first[0].id > first[1].id

    second, has_more2 = await svc.query_cursor(limit=2, before=first[-1].id)
    assert len(second) == 2 and has_more2 is True
    assert second[0].id < first[-1].id  # a real keyset, no overlap

    third, has_more3 = await svc.query_cursor(limit=2, before=second[-1].id)
    assert len(third) == 1 and has_more3 is False  # the end of the list


async def test_resolve_actor_names_and_list_actors(session: AsyncSession) -> None:
    from app.modules.auth.models import Principal

    session.add(Principal(sub="u-1", display_name="User One", email="u1@x.test"))
    session.add(Principal(sub="u-2", email="u2@x.test"))  # email only
    svc = AuditService(session)
    await svc.record(actor="u-1", action=AuditAction.LOGIN)
    await svc.record(actor="u-2", action=AuditAction.LOGIN)
    await svc.record(actor=None, action=AuditAction.EXPORT)  # the system actor
    await session.commit()

    names = await svc.resolve_actor_names(["u-1", "u-2", "unknown", None])
    assert names == {"u-1": "User One", "u-2": "u2@x.test"}

    actors = await svc.list_actors()
    # only actors that are not None, each with a resolved name
    assert ("u-1", "User One") in actors
    assert ("u-2", "u2@x.test") in actors
    assert all(sub is not None for sub, _ in actors)


async def test_resolve_data_ids_resolves_embedded_uuids(session: AsyncSession) -> None:
    """Resolve UUIDs embedded in `data` to names. Unknown and non-UUID values are absent."""
    import uuid as _uuid

    from app.modules.admin.models import Gremium

    g = Gremium(name="Finanzausschuss", slug="finanz")
    session.add(g)
    await session.flush()
    unknown = str(_uuid.uuid4())

    # The scan runs recursively over lists and nested dicts and skips non-UUID values.
    resolved = await AuditService(session).resolve_data_ids(
        [
            {"gremiumId": str(g.id), "note": "kein-uuid"},
            {"members": [{"delegateId": unknown}]},
            None,
        ]
    )
    assert resolved == {str(g.id): "Finanzausschuss"}


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


async def test_truncate_is_rejected(session: AsyncSession, engine: Engine) -> None:
    """TRUNCATE would bypass the row triggers.

    A statement trigger rejects it, which keeps the tamper evidence intact.
    """
    await AuditService(session).record(actor="a", action=AuditAction.LOGIN)
    await session.commit()

    with pytest.raises(DBAPIError, match="append-only"):
        async with session.begin():
            await session.execute(text("TRUNCATE audit_entry"))


async def test_concurrent_records_keep_chain_intact(
    migrated: tuple[str, str], engine: Engine
) -> None:
    """Two parallel `record()` calls in separate sessions keep the chain without a gap.

    The transaction advisory lock serializes the appends. No `prev_hash` interleaves,
    because one transaction waits for the commit of the other.
    """
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)

    async def _one(actor: str) -> None:
        async with maker() as s:
            await AuditService(s).record(actor=actor, action=AuditAction.LOGIN)
            await s.commit()

    try:
        await asyncio.gather(_one("u-1"), _one("u-2"))

        async with maker() as s:
            entries = (
                (await s.execute(select(AuditEntry).order_by(AuditEntry.id)))
                .scalars()
                .all()
            )
            assert len(entries) == 2
            assert entries[0].prev_hash is None
            assert entries[1].prev_hash == entries[0].hash  # a real link
            assert entries[0].hash != entries[1].hash
            assert (await AuditService(s).verify_chain()).valid is True
    finally:
        await eng.dispose()
