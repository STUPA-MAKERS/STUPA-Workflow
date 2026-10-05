"""Shared fixtures of the delegation integration tests (Z5, O6).

``maker`` gives a session factory. ``api`` gives the real app
wiring with the vote transfer switched on. ``act`` changes the calling principal.
The helpers write gremium members, plain principals and faculty groups with the
ORM.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.main as main_mod
from app.db import get_session
from app.deps import get_current_principal
from app.main import create_app
from app.modules.admin.models import Gremium, GremiumMembership, GremiumRole
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.delegations.models import (
    DelegationSubstitute,
    SubstituteGroup,
    SubstituteGroupMember,
)
from app.modules.livevote.broker import InMemoryBroker
from app.modules.livevote.models import Meeting
from app.modules.livevote.publisher import NullPublisher, get_meeting_publisher
from app.modules.livevote.router import get_broker_rest
from app.settings import get_settings, load_settings

ADMIN_SUB = "admin-p7"


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Give a session factory on the migrated database. `engine` clears the data."""
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


def make_api(migrated: tuple[str, str], monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """Build the real app with an admin principal and the vote transfer switched on.

    The request session has no pool, so no connection crosses the event loops of
    the TestClient.
    """
    settings = load_settings(
        database_url=migrated[1],
        session_secret="session-secret-delegation-p7-00",
        magic_link_secret="magic-link-secret-delegation-p7",
        cookie_secure=False,
        delegation_voting_enabled=True,
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
    # The test stack has no Redis. The broadcasts go to an in-memory broker, and
    # the vote tally of a cast goes nowhere.
    broker = InMemoryBroker()
    application.dependency_overrides[get_broker_rest] = lambda: broker
    application.dependency_overrides[get_meeting_publisher] = NullPublisher
    application.dependency_overrides[get_current_principal] = admin
    return application


@pytest.fixture
def api(migrated: tuple[str, str], monkeypatch: pytest.MonkeyPatch) -> Iterator[FastAPI]:
    application = make_api(migrated, monkeypatch)
    try:
        yield application
    finally:
        application.dependency_overrides.clear()


def admin() -> Principal:
    return Principal(sub=ADMIN_SUB, roles=["admin"])


def act(
    api: FastAPI,
    sub: str | None,
    *,
    permissions: set[str] | None = None,
    scope: frozenset[str] | None = None,
) -> None:
    """Act as `sub`, or as the admin for `None`."""
    if sub is None:
        api.dependency_overrides[get_current_principal] = admin
        return
    principal = Principal(sub=sub, permissions=permissions or set(), scope_permissions=scope)
    api.dependency_overrides[get_current_principal] = lambda: principal


async def gremium(maker: async_sessionmaker[AsyncSession], *, allow: bool = True) -> uuid.UUID:
    """Write a gremium that allows delegations."""
    async with maker() as session:
        row = Gremium(name="StuPa", slug=f"g-{uuid.uuid4().hex[:8]}", allow_vote_delegation=allow)
        session.add(row)
        await session.commit()
        return row.id


async def person(maker: async_sessionmaker[AsyncSession], name: str) -> tuple[str, uuid.UUID]:
    """Write a principal without a membership and return sub and id."""
    sub = f"{name}-{uuid.uuid4().hex[:8]}"
    async with maker() as session:
        row = PrincipalRow(sub=sub, display_name=name, email=f"{sub}@x.de")
        session.add(row)
        await session.commit()
        return sub, row.id


async def member(
    maker: async_sessionmaker[AsyncSession],
    gremium_id: uuid.UUID,
    name: str,
    permissions: tuple[str, ...] = ("vote.cast",),
    *,
    ended: bool = False,
) -> tuple[str, uuid.UUID]:
    """Write a gremium member with a role of `permissions` and return sub and id.

    `ended` writes a membership that ended yesterday, so it is not active.
    """
    sub, pid = await person(maker, name)
    async with maker() as session:
        role = GremiumRole(
            gremium_id=gremium_id,
            key=f"r-{uuid.uuid4().hex[:8]}",
            name_i18n={"de": name},
            permissions=list(permissions),
        )
        session.add(role)
        await session.flush()
        now = datetime.now(UTC)
        session.add(
            GremiumMembership(
                principal_id=pid,
                gremium_id=gremium_id,
                gremium_role_id=role.id,
                valid_from=now - timedelta(days=30) if ended else None,
                valid_until=now - timedelta(days=1) if ended else None,
            )
        )
        await session.commit()
    return sub, pid


async def faculty_group(
    maker: async_sessionmaker[AsyncSession],
    gremium_id: uuid.UUID,
    *,
    members: tuple[uuid.UUID, ...] = (),
    substitutes: tuple[uuid.UUID, ...] = (),
    name: str = "Informatik",
) -> uuid.UUID:
    """Write a faculty group with its members and substitutes."""
    async with maker() as session:
        group = SubstituteGroup(gremium_id=gremium_id, name_i18n={"de": name})
        session.add(group)
        await session.flush()
        for pid in members:
            session.add(
                SubstituteGroupMember(
                    group_id=group.id, principal_id=pid, gremium_id=gremium_id, kind="member"
                )
            )
        for pid in substitutes:
            session.add(
                SubstituteGroupMember(
                    group_id=group.id, principal_id=pid, gremium_id=gremium_id, kind="substitute"
                )
            )
        await session.commit()
        return group.id


async def pool_entry(
    maker: async_sessionmaker[AsyncSession],
    gremium_id: uuid.UUID,
    substitute: uuid.UUID,
    *,
    for_member: uuid.UUID | None = None,
) -> None:
    """Write a pool entry: personal for `for_member`, or gremium-wide for `None`."""
    async with maker() as session:
        session.add(
            DelegationSubstitute(
                gremium_id=gremium_id,
                member_principal_id=for_member,
                substitute_principal_id=substitute,
            )
        )
        await session.commit()


async def meeting(
    maker: async_sessionmaker[AsyncSession],
    gremium_id: uuid.UUID,
    *,
    status: str = "planned",
) -> uuid.UUID:
    """Write a meeting of the gremium in 30 days at 18:00."""
    async with maker() as session:
        row = Meeting(
            gremium_id=gremium_id,
            title="GV",
            date=date.today() + timedelta(days=30),
            status=status,
        )
        session.add(row)
        await session.commit()
        return row.id


async def set_status(
    maker: async_sessionmaker[AsyncSession], meeting_id: uuid.UUID, status: str
) -> None:
    async with maker() as session:
        await session.execute(update(Meeting).where(Meeting.id == meeting_id).values(status=status))
        await session.commit()
