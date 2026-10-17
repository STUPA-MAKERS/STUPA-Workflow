"""Fixtures of the ticket integration tests (real Postgres).

Each test starts without principals, site-config versions and tickets: the
fixtures clear the principal tables (``clear_privacy_tables``) and the site-config
versions before and after, and the ``engine`` fixture truncates ``ticket``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.deps import get_current_principal
from app.modules.auth.models import GroupMapping, Role, RoleAssignment, RolePermission
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.tickets.router import get_ticket_mail_sender
from app.settings import Settings
from tests._support.guest_apps import build_api, guest_settings
from tests.integration.conftest import clear_privacy_tables


def _clear(eng: Engine) -> None:
    clear_privacy_tables(eng)
    with eng.begin() as conn:
        conn.execute(text("DELETE FROM site_config_version"))
        conn.execute(text("DELETE FROM group_mapping WHERE oidc_group LIKE 'tickets-%'"))
        conn.execute(text("DELETE FROM role WHERE key LIKE 'tickets_%'"))


@pytest.fixture
def clean(engine: Engine) -> Iterator[Engine]:
    _clear(engine)
    try:
        yield engine
    finally:
        _clear(engine)


@pytest.fixture
async def maker(
    migrated: tuple[str, str], clean: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


@pytest.fixture
def settings(migrated: tuple[str, str]) -> Settings:
    return guest_settings(migrated[1])


@dataclass
class Mails:
    """The captured mail jobs of ``POST /tickets``."""

    calls: list[uuid.UUID] = field(default_factory=list)

    async def send(self, _settings: Settings, ticket_id: uuid.UUID, _pool: object) -> None:
        self.calls.append(ticket_id)


@dataclass
class Api:
    app: FastAPI
    mails: Mails

    def login(self, principal: Principal | None) -> None:
        self.app.dependency_overrides[get_current_principal] = lambda: principal


@pytest.fixture
def api(
    migrated: tuple[str, str],
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> Api:
    app = build_api(migrated[1], settings, monkeypatch)
    mails = Mails()
    app.dependency_overrides[get_ticket_mail_sender] = lambda: mails.send
    app.dependency_overrides[get_current_principal] = lambda: None
    return Api(app=app, mails=mails)


async def add_principal(
    maker: async_sessionmaker[AsyncSession],
    *,
    sub: str | None = None,
    email: str | None = None,
    name: str | None = None,
    role: str | None = None,
    groups: list[str] | None = None,
    active: bool = True,
) -> uuid.UUID:
    """Insert an account, optionally with a role assignment (``admin``, ``member``)."""
    tag = uuid.uuid4().hex[:8]
    async with maker() as session:
        row = PrincipalRow(
            sub=sub or f"sub-{tag}",
            email=email if email is not None else f"{tag}@example.org",
            display_name=name,
            oidc_groups=groups,
            active=active,
        )
        session.add(row)
        await session.flush()
        if role is not None:
            role_id = await session.scalar(select(Role.id).where(Role.key == role))
            assert role_id is not None
            session.add(RoleAssignment(principal_id=row.id, role_id=role_id))
        await session.commit()
        return row.id


async def add_group_role(
    maker: async_sessionmaker[AsyncSession], group: str, *perms: str
) -> uuid.UUID:
    """Create a role ``tickets_<n>`` with ``perms`` and map the OIDC group ``group`` to it."""
    async with maker() as session:
        role = Role(key=f"tickets_{uuid.uuid4().hex[:6]}", name_i18n={})
        session.add(role)
        await session.flush()
        for perm in perms:
            session.add(RolePermission(role_id=role.id, permission=perm))
        session.add(GroupMapping(oidc_group=group, role_id=role.id))
        await session.commit()
        return role.id


MANAGER = Principal(sub="mgr-sub", email="mgr@example.org", permissions={"ticket.manage"})
ADMIN = Principal(sub="admin-sub", email="admin@example.org", roles=["admin"])
PLAIN = Principal(sub="plain-sub", email="plain@example.org")
