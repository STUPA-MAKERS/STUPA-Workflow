"""The worker discards unconfirmed applications after `confirm_ttl_hours` (Z1, F23).

* The window comes from `guest_application_settings` on every run. A shorter value
  applies to the applications that already wait.
* The discard covers every unconfirmed application, also one that a logged-in person
  submitted for another email address (F23), not only `created_by IS NULL`.
* It deletes the rows, removes the storage objects of the attachments and writes one
  `guest_application_discard` audit entry per application, without PII.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.applications.guest_settings import GuestSettingsService
from app.modules.applications.models import Application
from app.modules.applications.service import ApplicationsService
from app.modules.audit.models import AuditEntry
from app.modules.files.models import Attachment
from app.settings import Settings
from tests._support.guest_apps import (
    GUEST_EMAIL,
    GuestSeed,
    create_guest_application,
    guest_payload,
    guest_settings,
    seed_guest_flow,
)
from worker import deadlines as wd

pytestmark = pytest.mark.integration


class _Storage:
    """Object storage fake that records the removed keys."""

    def __init__(self) -> None:
        self.removed: list[str] = []

    async def remove(self, key: str) -> None:
        self.removed.append(key)


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


@pytest.fixture
def settings(migrated: tuple[str, str]) -> Settings:
    return guest_settings(migrated[1])


async def _age(maker: async_sessionmaker[AsyncSession], app_id: uuid.UUID, hours: float) -> None:
    async with maker() as session:
        await session.execute(
            update(Application)
            .where(Application.id == app_id)
            .values(created_at=datetime.now(UTC) - timedelta(hours=hours))
        )
        await session.commit()


async def _attach(
    maker: async_sessionmaker[AsyncSession], app_id: uuid.UUID, key: str | None
) -> None:
    async with maker() as session:
        session.add(
            Attachment(
                application_id=app_id,
                filename="beleg.pdf",
                mime="application/pdf",
                size=10,
                storage_key=key,
            )
        )
        await session.commit()


async def _logged_in_create(
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
    *,
    email: str,
    confirmed: bool,
) -> uuid.UUID:
    async with maker() as session:
        app, _ = await ApplicationsService(session).create(
            guest_payload(seed.type_id, email),
            actor="member-sub",
            email_confirmed=confirmed,
        )
        return app.id


async def _existing(
    maker: async_sessionmaker[AsyncSession], ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    async with maker() as session:
        return set(
            (await session.scalars(select(Application.id).where(Application.id.in_(ids)))).all()
        )


async def _discards(maker: async_sessionmaker[AsyncSession]) -> list[AuditEntry]:
    async with maker() as session:
        return list(
            (
                await session.scalars(
                    select(AuditEntry)
                    .where(AuditEntry.action == "guest_application_discard")
                    .order_by(AuditEntry.id)
                )
            ).all()
        )


async def test_discard_covers_every_unconfirmed_application(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    seed = await seed_guest_flow(maker)
    old_guest = await create_guest_application(maker, seed)
    fresh_guest = await create_guest_application(maker, seed)
    foreign = await _logged_in_create(
        maker, seed, email="someone-else@example.org", confirmed=False
    )
    confirmed = await _logged_in_create(maker, seed, email=GUEST_EMAIL, confirmed=True)
    for app_id in (old_guest, foreign, confirmed):
        await _age(maker, app_id, hours=13)
    await _age(maker, fresh_guest, hours=11)
    await _attach(maker, old_guest, "obj/old-guest")
    await _attach(maker, old_guest, None)  # quarantined: no object left
    await _attach(maker, foreign, "obj/foreign")

    storage = _Storage()
    ctx: dict[str, Any] = {"deadlines_sessionmaker": maker, "object_storage": storage}
    assert await wd._discard_unconfirmed(ctx, datetime.now(UTC), settings) == 2

    everything = [old_guest, fresh_guest, foreign, confirmed]
    assert await _existing(maker, everything) == {fresh_guest, confirmed}
    async with maker() as session:
        left = (await session.scalars(select(Attachment.application_id))).all()
    assert left == []
    assert sorted(storage.removed) == ["obj/foreign", "obj/old-guest"]

    entries = await _discards(maker)
    assert {e.target_id for e in entries} == {str(old_guest), str(foreign)}
    by_target = {e.target_id: e for e in entries}
    assert by_target[str(old_guest)].data == {
        "typeId": str(seed.type_id),
        "gremiumId": str(seed.gremium_id),
        "attachments": 2,
        "confirmTtlHours": 12,
    }
    for entry in entries:
        assert entry.actor == "system:deadlines"
        assert entry.target_type == "application"
        # No PII: neither the email nor a field value reaches the log.
        text = repr(entry.data)
        assert "@" not in text and "Gastantrag" not in text

    # A second run finds nothing.
    assert await wd._discard_unconfirmed(ctx, datetime.now(UTC), settings) == 0
    assert len(await _discards(maker)) == 2


async def test_discard_reads_the_window_on_every_run(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    seed = await seed_guest_flow(maker)
    waiting = await create_guest_application(maker, seed)
    await _age(maker, waiting, hours=3)
    ctx: dict[str, Any] = {"deadlines_sessionmaker": maker, "object_storage": _Storage()}

    assert await wd._discard_unconfirmed(ctx, datetime.now(UTC), settings) == 0
    assert await _existing(maker, [waiting]) == {waiting}

    async with maker() as session:
        await GuestSettingsService(session).update(
            confirm_ttl_hours=2, link_ttl_days=None, actor="admin"
        )

    assert await wd._discard_unconfirmed(ctx, datetime.now(UTC), settings) == 1
    assert await _existing(maker, [waiting]) == set()
    (entry,) = await _discards(maker)
    assert entry.data["confirmTtlHours"] == 2


async def test_process_deadlines_runs_the_discard(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    seed = await seed_guest_flow(maker)
    stale = await create_guest_application(maker, seed)
    await _age(maker, stale, hours=24)
    ctx: dict[str, Any] = {
        "settings": settings,
        "deadlines_sessionmaker": maker,
        "object_storage": _Storage(),
        "flow_dispatcher": object(),
    }
    summary = await wd.process_deadlines(ctx)
    assert "discarded=1" in summary
    assert await _existing(maker, [stale]) == set()
