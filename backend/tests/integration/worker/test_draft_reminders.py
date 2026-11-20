"""Draft reminders on a real Postgres (spec 001711).

A confirmed draft in the initial state gets the mail ``draft_reminder`` once, after 7
days without a change. A draft of 6 days and a draft with a sent reminder get none.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.applications.models import Application
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.settings import Settings
from tests._support.guest_apps import GuestSeed, guest_settings, seed_guest_flow
from worker.drafts import process_draft_reminders

pytestmark = pytest.mark.integration


class _Queue:
    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []

    async def enqueue(self, *args: Any, **kw: Any) -> None:
        self.jobs.append({"args": args, **kw})


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


async def _draft(
    maker: async_sessionmaker[AsyncSession], seed: GuestSeed, *, idle_days: float
) -> uuid.UUID:
    payload = ApplicationCreate.model_validate(
        {
            "typeId": str(seed.type_id),
            "data": {"title": "Entwurf"},
            "applicantEmail": "owner@example.org",
        }
    )
    async with maker() as session:
        app, _ = await ApplicationsService(session).create(
            payload, actor="owner-sub", email_confirmed=True
        )
        await session.execute(
            update(Application)
            .where(Application.id == app.id)
            .values(updated_at=datetime.now(UTC) - timedelta(days=idle_days))
        )
        await session.commit()
        return app.id


async def test_a_draft_gets_one_reminder_after_seven_days(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    seed = await seed_guest_flow(maker)
    fresh = await _draft(maker, seed, idle_days=6)
    idle = await _draft(maker, seed, idle_days=8)
    queue = _Queue()
    ctx: dict[str, Any] = {"sessionmaker": maker, "settings": settings, "mail_queue": queue}

    assert await process_draft_reminders(ctx) == 1
    assert len(queue.jobs) == 1
    async with maker() as session:
        sent = await session.get(Application, idle)
        waiting = await session.get(Application, fresh)
        assert sent is not None and sent.draft_reminder_at is not None
        assert waiting is not None and waiting.draft_reminder_at is None

    assert await process_draft_reminders(ctx) == 0
    assert len(queue.jobs) == 1


async def test_a_submitted_antrag_gets_no_reminder(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    seed = await seed_guest_flow(maker)
    app_id = await _draft(maker, seed, idle_days=10)
    async with maker() as session:
        await session.execute(
            update(Application)
            .where(Application.id == app_id)
            .values(current_state_id=seed.locked_state_id)
        )
        await session.commit()
    queue = _Queue()
    ctx: dict[str, Any] = {"sessionmaker": maker, "settings": settings, "mail_queue": queue}
    assert await process_draft_reminders(ctx) == 0
    assert queue.jobs == []
