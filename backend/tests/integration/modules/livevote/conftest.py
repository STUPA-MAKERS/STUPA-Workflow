"""Shared fixtures of the meeting lifecycle and agenda integration tests (P5a).

``maker`` gives a session factory on the migrated test database. ``api`` gives the real
app wiring with an admin principal and a request session without a pool, so no
connection crosses the event loops of the TestClient. ``seed`` writes a gremium, a
meeting, agenda items, votes and a protocol with the ORM.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import date as _date
from datetime import time as _time

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.main as main_mod
from app.db import get_session
from app.deps import get_current_principal
from app.main import create_app
from app.modules.admin.models import Gremium
from app.modules.audit.models import AuditEntry
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.livevote.broker import InMemoryBroker
from app.modules.livevote.models import Meeting, MeetingAgendaItem
from app.modules.livevote.router import get_broker_rest
from app.modules.protocol.models import Protocol
from app.modules.voting.models import Vote
from app.settings import get_settings, load_settings
from app.shared.config_schemas import VoteConfig

ADMIN_SUB = "admin-p5a"

CONFIG = VoteConfig.model_validate(
    {"options": ["yes", "no", "abstain"], "majorityRule": "simple"}
).model_dump(by_alias=True)


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


@pytest.fixture
def api(migrated: tuple[str, str], monkeypatch: pytest.MonkeyPatch) -> Iterator[FastAPI]:
    settings = load_settings(
        database_url=migrated[1],
        session_secret="session-secret-meeting-p5a-000",
        magic_link_secret="magic-link-secret-meeting-p5a0",
        cookie_secure=False,
    )
    request_maker = async_sessionmaker(
        create_async_engine(migrated[1], poolclass=NullPool), expire_on_commit=False
    )

    async def _request_session() -> AsyncIterator[AsyncSession]:
        async with request_maker() as db:
            yield db

    monkeypatch.setattr(main_mod, "get_sessionmaker", lambda: request_maker)
    application = create_app(settings)
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_session] = _request_session
    # The test stack has no Redis. The broadcasts go to an in-memory broker.
    broker = InMemoryBroker()
    application.dependency_overrides[get_broker_rest] = lambda: broker
    application.dependency_overrides[get_current_principal] = lambda: Principal(
        sub=ADMIN_SUB, roles=["admin"], permissions={"meeting.delete_finalized"}
    )
    try:
        yield application
    finally:
        application.dependency_overrides.clear()


def admin() -> Principal:
    return Principal(sub=ADMIN_SUB, roles=["admin"], permissions={"meeting.delete_finalized"})


@dataclass
class Seed:
    """Ids of one seeded meeting."""

    gremium_id: uuid.UUID
    meeting_id: uuid.UUID
    item_ids: list[uuid.UUID] = field(default_factory=list)
    vote_ids: dict[str, uuid.UUID] = field(default_factory=dict)
    protocol_id: uuid.UUID | None = None


async def seed(
    maker: async_sessionmaker[AsyncSession],
    *,
    status: str = "live",
    items: int = 1,
    votes: tuple[str, ...] = (),
    protocol: str | None = None,
) -> Seed:
    """Write a meeting with free-text agenda items and votes on the first item.

    ``votes`` names the status of each vote. The votes bind to the meeting and to the
    first agenda item. ``protocol`` names the protocol status, or ``None`` for none.
    """
    tag = uuid.uuid4().hex[:8]
    async with maker() as session:
        gremium = Gremium(name="G", slug=f"g-{tag}")
        session.add(gremium)
        await session.flush()
        writer = PrincipalRow(sub=f"w-{tag}", display_name="W", email=f"w-{tag}@x.de")
        session.add(writer)
        await session.flush()
        meeting = Meeting(
            gremium_id=gremium.id,
            title="GV",
            date=_date(2026, 6, 20),
            start_time=_time(18, 0),
            status=status,
            protokollant_id=writer.id,
        )
        session.add(meeting)
        await session.flush()
        out = Seed(gremium_id=gremium.id, meeting_id=meeting.id)
        for n in range(items):
            item = MeetingAgendaItem(meeting_id=meeting.id, title=f"TOP {n + 1}", position=n)
            session.add(item)
            await session.flush()
            out.item_ids.append(item.id)
        for vote_status in votes:
            vote = Vote(
                application_id=None,
                meeting_id=meeting.id,
                agenda_item_id=out.item_ids[0] if out.item_ids else None,
                eligible_group=str(gremium.id),
                config=CONFIG,
                status=vote_status,
                result="passed" if vote_status == "closed" else None,
            )
            session.add(vote)
            await session.flush()
            out.vote_ids[vote_status] = vote.id
        if protocol is not None:
            row = Protocol(meeting_id=meeting.id, gremium_id=gremium.id, status=protocol)
            session.add(row)
            await session.flush()
            out.protocol_id = row.id
        await session.commit()
    return out


async def audit_actions(
    maker: async_sessionmaker[AsyncSession], *, target_id: uuid.UUID | None = None
) -> list[AuditEntry]:
    """Return the audit entries in chain order, optionally for one target."""
    async with maker() as session:
        stmt = select(AuditEntry).order_by(AuditEntry.id)
        if target_id is not None:
            stmt = stmt.where(AuditEntry.target_id == str(target_id))
        return list((await session.scalars(stmt)).all())
