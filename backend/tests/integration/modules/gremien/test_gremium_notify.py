"""The message of a Gremium to its members against a real Postgres (specs 001850-001854).

The send needs ``members.notify`` from the own gremium role: no admin bypass, and the OAuth
scope caps it. Each active member and pool substitute with an address gets one mail with
the Reply-To of the sender; a deactivated account gets none, a member in the pool one. Each send
writes one audit entry without addresses and without the text.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.main as main_mod
from app.db import get_session
from app.deps import get_current_principal
from app.main import create_app
from app.modules.audit.models import AuditEntry
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.gremien.models import (
    DelegationSubstitute,
    Gremium,
    GremiumMembership,
    GremiumRole,
)
from app.modules.gremien_overview.router import get_notify_queue
from app.modules.notifications.mail import CapturingMailSender, build_email_message
from app.modules.notifications.queue import DirectMailQueue
from app.settings import get_settings, load_settings

SENT = CapturingMailSender()

pytestmark = pytest.mark.integration


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


@pytest.fixture
def app_for(migrated: tuple[str, str], monkeypatch: pytest.MonkeyPatch) -> Iterator[FastAPI]:
    settings = load_settings(
        database_url=migrated[1],
        session_secret="session-secret-gremium-notify0",
        magic_link_secret="magic-link-secret-gremium-notf",
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
    application.dependency_overrides[get_notify_queue] = lambda: DirectMailQueue(SENT)
    try:
        yield application
    finally:
        application.dependency_overrides.clear()


def _client(app: FastAPI, principal: Principal) -> TestClient:
    app.dependency_overrides[get_current_principal] = lambda: principal
    return TestClient(app)


@dataclass(frozen=True)
class World:
    gremium_id: uuid.UUID
    manager: Principal
    member: Principal
    tag: str


async def _world(maker: async_sessionmaker[AsyncSession]) -> World:
    """Seed a Gremium: a manager, a member (also in the pool), an inactive member, a pool person."""
    tag = uuid.uuid4().hex[:8]
    async with maker() as s:
        g = Gremium(name=f"STUPA {tag}", slug=f"stupa-notify-{tag}")
        s.add(g)
        await s.flush()
        manager_role = GremiumRole(
            gremium_id=g.id,
            key="manager",
            name_i18n={"de": "Manager"},
            permissions=["members.notify"],
        )
        member_role = GremiumRole(
            gremium_id=g.id, key="member", name_i18n={"de": "Mitglied"}, permissions=["vote.cast"]
        )
        manager = PrincipalRow(sub=f"mgr-{tag}", display_name="Mara Keller", email=f"m-{tag}@x.de")
        member = PrincipalRow(sub=f"mem-{tag}", display_name="Jonas", email=f"j-{tag}@x.de")
        gone = PrincipalRow(
            sub=f"off-{tag}", display_name="Off", email=f"o-{tag}@x.de", active=False
        )
        pool = PrincipalRow(sub=f"pool-{tag}", display_name="Pool", email=f"p-{tag}@x.de")
        s.add_all([manager_role, member_role, manager, member, gone, pool])
        await s.flush()
        s.add_all(
            [
                GremiumMembership(
                    principal_id=manager.id, gremium_id=g.id, gremium_role_id=manager_role.id
                ),
                GremiumMembership(
                    principal_id=member.id, gremium_id=g.id, gremium_role_id=member_role.id
                ),
                GremiumMembership(
                    principal_id=gone.id, gremium_id=g.id, gremium_role_id=member_role.id
                ),
                DelegationSubstitute(gremium_id=g.id, substitute_principal_id=pool.id),
                DelegationSubstitute(gremium_id=g.id, substitute_principal_id=member.id),
            ]
        )
        await s.commit()
        return World(
            gremium_id=g.id,
            manager=Principal(sub=manager.sub, display_name="Mara Keller"),
            member=Principal(sub=member.sub, display_name="Jonas"),
            tag=tag,
        )


def _body(**extra: object) -> dict[str, object]:
    return {"subject": "Klausurtagung", "message": "Bitte bis Freitag anmelden.", **extra}


def _mine(tag: str) -> list[tuple[str, ...]]:
    return [m.to for m in SENT.sent if any(tag in addr for addr in m.to)]


async def test_manager_notifies_every_active_member(
    maker: async_sessionmaker[AsyncSession], app_for: FastAPI
) -> None:
    """§ 001850, § 001852, § 001854: one mail per member and pool person, Reply-To, audit."""
    w = await _world(maker)
    resp = _client(app_for, w.manager).post(f"/api/committees/{w.gremium_id}/notify", json=_body())
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"recipients": 3}
    mails = [m for m in SENT.sent if any(w.tag in addr for addr in m.to)]
    assert sorted(m.to for m in mails) == [
        (f"j-{w.tag}@x.de",),
        (f"m-{w.tag}@x.de",),
        (f"p-{w.tag}@x.de",),
    ]
    for mail in mails:
        assert mail.reply_to == f"m-{w.tag}@x.de"
        assert "Klausurtagung" in mail.subject
        assert "Bitte bis Freitag anmelden." in mail.text
        assert "Mara Keller" in mail.text
        assert f"/committees/{w.gremium_id}" in mail.text
        email = build_email_message(mail, get_settings())
        assert email["Reply-To"] == f"m-{w.tag}@x.de"

    async with maker() as s:
        entries = (
            (
                await s.execute(
                    select(AuditEntry).where(
                        AuditEntry.action == "gremium_notify",
                        AuditEntry.target_id == str(w.gremium_id),
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(entries) == 1
    assert entries[0].data == {
        "gremiumId": str(w.gremium_id),
        "subject": "Klausurtagung",
        "recipients": 3,
    }


async def test_only_members_notify_sends(
    maker: async_sessionmaker[AsyncSession], app_for: FastAPI
) -> None:
    """§ 001851: a member, an admin without membership and a capped token get 403."""
    w = await _world(maker)
    admin = Principal(sub=f"admin-{w.tag}", roles=["admin"])
    capped = Principal(
        sub=w.manager.sub, scope_permissions=frozenset({"gremium.view_all", "info.write"})
    )
    for principal in (w.member, admin, capped):
        resp = _client(app_for, principal).post(
            f"/api/committees/{w.gremium_id}/notify", json=_body()
        )
        assert resp.status_code == 403, principal.sub
        assert resp.headers["content-type"].startswith("application/problem+json")
    assert _mine(w.tag) == []
    scoped = Principal(
        sub=w.manager.sub, scope_permissions=frozenset({"members.notify", "gremium.view_all"})
    )
    resp = _client(app_for, scoped).post(f"/api/committees/{w.gremium_id}/notify", json=_body())
    assert resp.status_code == 200


async def test_stranger_gets_404(maker: async_sessionmaker[AsyncSession], app_for: FastAPI) -> None:
    """§ 001850: a principal who does not see the Gremium gets 404."""
    w = await _world(maker)
    resp = _client(app_for, Principal(sub=f"stranger-{w.tag}")).post(
        f"/api/committees/{w.gremium_id}/notify", json=_body()
    )
    assert resp.status_code == 404


@pytest.mark.parametrize(
    "extra",
    [
        {"subject": ""},
        {"subject": "   "},
        {"subject": "x" * 201},
        {"message": ""},
        {"message": "x" * 10_001},
    ],
)
async def test_limits_give_422(
    maker: async_sessionmaker[AsyncSession], app_for: FastAPI, extra: dict[str, object]
) -> None:
    """§ 001854: an empty or long subject or message gives 422 and sends nothing."""
    w = await _world(maker)
    resp = _client(app_for, w.manager).post(
        f"/api/committees/{w.gremium_id}/notify", json=_body(**extra)
    )
    assert resp.status_code == 422
    assert _mine(w.tag) == []
