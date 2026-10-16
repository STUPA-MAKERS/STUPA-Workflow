"""Fixtures of the to-do integration tests (real Postgres).

Each test starts without principals and boards: ``clear_privacy_tables`` truncates
``principal`` (and with it every board and card through CASCADE) before and after,
and the ``engine`` fixture truncates ``todo_board``. A test writes the accounts,
the gremien and the boards it needs with the helpers below.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.deps import get_current_principal
from app.modules.admin.models import Gremium, GremiumMembership, GremiumRole
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.todos.boards import ensure_gremium_board
from app.modules.todos.models import TodoBoard
from app.modules.todos.router import get_todo_mail_sender
from app.modules.todos.service import TodoMail
from app.settings import Settings
from tests._support.guest_apps import build_api, guest_settings
from tests.integration.conftest import clear_privacy_tables


def _clear(eng: Engine) -> None:
    clear_privacy_tables(eng)
    with eng.begin() as conn:
        conn.execute(text("DELETE FROM gremium WHERE slug LIKE 'todo-%'"))


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
class Api:
    app: FastAPI
    mails: list[TodoMail] = field(default_factory=list)

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
    state = Api(app=app)

    async def _send(_settings: Settings, mails: list[TodoMail], _pool: object) -> None:
        state.mails.extend(mails)

    app.dependency_overrides[get_todo_mail_sender] = lambda: _send
    app.dependency_overrides[get_current_principal] = lambda: None
    return state


async def add_person(
    maker: async_sessionmaker[AsyncSession], name: str, *, sub: str | None = None
) -> tuple[Principal, uuid.UUID]:
    """Write an account and return its session principal and its id."""
    sub = sub or f"{name.lower()}-{uuid.uuid4().hex[:8]}"
    async with maker() as session:
        row = PrincipalRow(sub=sub, display_name=name, email=f"{sub}@example.org")
        session.add(row)
        await session.commit()
        return Principal(sub=sub, email=row.email, display_name=name), row.id


async def add_gremium(
    maker: async_sessionmaker[AsyncSession], name: str = "StuPa"
) -> tuple[uuid.UUID, uuid.UUID]:
    """Write a gremium with its board and return both ids."""
    async with maker() as session:
        row = Gremium(name=name, slug=f"todo-{uuid.uuid4().hex[:8]}")
        session.add(row)
        await session.flush()
        await ensure_gremium_board(session, row.id, name)
        await session.commit()
        board_id = (
            await session.execute(
                text("SELECT id FROM todo_board WHERE gremium_id = :g"), {"g": row.id}
            )
        ).scalar_one()
        return row.id, board_id


async def add_member(
    maker: async_sessionmaker[AsyncSession],
    gremium_id: uuid.UUID,
    person_id: uuid.UUID,
    *permissions: str,
) -> None:
    """Give an account a membership with a role of ``permissions`` in the gremium."""
    async with maker() as session:
        role = GremiumRole(
            gremium_id=gremium_id,
            key=f"r-{uuid.uuid4().hex[:8]}",
            name_i18n={"de": "Rolle"},
            permissions=list(permissions),
        )
        session.add(role)
        await session.flush()
        session.add(
            GremiumMembership(
                principal_id=person_id,
                gremium_id=gremium_id,
                gremium_role_id=role.id,
                valid_from=datetime(2020, 1, 1, tzinfo=UTC),
            )
        )
        await session.commit()


async def add_team_board(maker: async_sessionmaker[AsyncSession], permission: str) -> uuid.UUID:
    """Write a team board with the default columns."""
    from app.modules.todos.boards import add_default_columns

    async with maker() as session:
        row = TodoBoard(name="Plattform", kind="team", permission=permission)
        session.add(row)
        await session.flush()
        add_default_columns(session, row.id)
        await session.commit()
        return row.id
