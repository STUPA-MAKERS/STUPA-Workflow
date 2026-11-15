"""The Info tab of a Gremium against a real Postgres (specs 001010-001014).

The read follows the gate of the tab "Gremien" (member, ``gremium.view_all``, admin,
else 404). The save needs ``info.write`` from the own gremium role: no admin bypass, and
the OAuth scope caps it. A stale version gives 409, every save writes one audit entry.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.main as main_mod
from app.db import get_session
from app.deps import get_current_principal
from app.main import create_app
from app.modules.audit.models import AuditEntry
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.gremien.models import Gremium, GremiumMembership, GremiumRole
from app.settings import get_settings, load_settings

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
        session_secret="session-secret-gremium-info-00",
        magic_link_secret="magic-link-secret-gremium-info",
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
    manager_id: uuid.UUID


async def _world(maker: async_sessionmaker[AsyncSession]) -> World:
    """Seed one Gremium with a manager (``info.write``) and a plain member."""
    tag = uuid.uuid4().hex[:8]
    async with maker() as s:
        g = Gremium(name=f"STUPA {tag}", slug=f"stupa-info-{tag}")
        s.add(g)
        await s.flush()
        manager_role = GremiumRole(
            gremium_id=g.id, key="manager", name_i18n={"de": "Manager"}, permissions=["info.write"]
        )
        member_role = GremiumRole(
            gremium_id=g.id, key="member", name_i18n={"de": "Mitglied"}, permissions=["vote.cast"]
        )
        manager = PrincipalRow(sub=f"mgr-{tag}", display_name="Mara Keller", email=f"m-{tag}@x.de")
        member = PrincipalRow(sub=f"mem-{tag}", display_name="Jonas", email=f"j-{tag}@x.de")
        s.add_all([manager_role, member_role, manager, member])
        await s.flush()
        s.add_all(
            [
                GremiumMembership(
                    principal_id=manager.id, gremium_id=g.id, gremium_role_id=manager_role.id
                ),
                GremiumMembership(
                    principal_id=member.id, gremium_id=g.id, gremium_role_id=member_role.id
                ),
            ]
        )
        await s.commit()
        return World(
            gremium_id=g.id,
            manager=Principal(sub=manager.sub, display_name="Mara Keller"),
            member=Principal(sub=member.sub, display_name="Jonas"),
            manager_id=manager.id,
        )


def _body(version: int, **extra: object) -> dict[str, object]:
    return {
        "bodyMd": "# Willkommen\n\nDas Wiki ist verlinkt.",
        "links": [
            {"label": "Wiki", "url": "https://wiki.example.org/stupa"},
            {"label": "Chat", "url": "https://chat.example.org/stupa"},
            {"label": "Vorsitz", "url": "mailto:vorsitz@example.org"},
        ],
        "version": version,
        **extra,
    }


async def test_empty_info_reads_for_member_and_view_all(
    maker: async_sessionmaker[AsyncSession], app_for: FastAPI
) -> None:
    """§ 001010: an unsaved Info is empty with version 0; a member cannot edit it."""
    w = await _world(maker)
    out = _client(app_for, w.member).get(f"/api/committees/{w.gremium_id}/info").json()
    assert out == {
        "bodyMd": "",
        "links": [],
        "version": 0,
        "updatedAt": None,
        "updatedByName": None,
        "canEdit": False,
    }
    viewer = Principal(sub="viewer-info", permissions={"gremium.view_all"})
    resp = _client(app_for, viewer).get(f"/api/committees/{w.gremium_id}/info")
    assert resp.status_code == 200
    assert resp.json()["canEdit"] is False
    assert _client(app_for, w.manager).get(f"/api/committees/{w.gremium_id}/info").json()["canEdit"]


async def test_stranger_gets_404(maker: async_sessionmaker[AsyncSession], app_for: FastAPI) -> None:
    """§ 001010: a principal who does not see the Gremium gets 404 for read and save."""
    w = await _world(maker)
    client = _client(app_for, Principal(sub="stranger-info"))
    for resp in (
        client.get(f"/api/committees/{w.gremium_id}/info"),
        client.put(f"/api/committees/{w.gremium_id}/info", json=_body(0)),
    ):
        assert resp.status_code == 404
        assert resp.json()["code"] == "gremium_not_found"


async def test_manager_saves_and_member_reads(
    maker: async_sessionmaker[AsyncSession], app_for: FastAPI
) -> None:
    """§ 001011, § 001012, § 001014: a save keeps the order, bumps the version, writes the audit."""
    w = await _world(maker)
    resp = _client(app_for, w.manager).put(f"/api/committees/{w.gremium_id}/info", json=_body(0))
    assert resp.status_code == 200, resp.text
    saved = resp.json()
    assert saved["version"] == 1
    assert saved["canEdit"] is True
    assert saved["updatedByName"] == "Mara Keller"
    assert [link["label"] for link in saved["links"]] == ["Wiki", "Chat", "Vorsitz"]

    read = _client(app_for, w.member).get(f"/api/committees/{w.gremium_id}/info").json()
    assert read["bodyMd"].startswith("# Willkommen")
    assert read["links"] == saved["links"]
    assert read["canEdit"] is False
    assert read["updatedAt"] is not None

    second = _client(app_for, w.manager).put(
        f"/api/committees/{w.gremium_id}/info", json=_body(1, links=[])
    )
    assert second.json()["version"] == 2
    assert second.json()["links"] == []

    async with maker() as s:
        entries = (
            (
                await s.execute(
                    select(AuditEntry).where(
                        AuditEntry.action == "gremium_info_update",
                        AuditEntry.target_id == str(w.gremium_id),
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(entries) == 2
    assert {e.data["links"] for e in entries} == {3, 0}
    assert all("bodyMd" not in e.data for e in entries)


async def test_stale_version_conflicts(
    maker: async_sessionmaker[AsyncSession], app_for: FastAPI
) -> None:
    """§ 001014: a save against an older version gives 409 and changes nothing."""
    w = await _world(maker)
    client = _client(app_for, w.manager)
    assert client.put(f"/api/committees/{w.gremium_id}/info", json=_body(0)).status_code == 200
    resp = client.put(f"/api/committees/{w.gremium_id}/info", json=_body(0, bodyMd="neu"))
    assert resp.status_code == 409
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["code"] == "gremium_info_version_conflict"
    assert client.get(f"/api/committees/{w.gremium_id}/info").json()["version"] == 1


async def test_only_info_write_saves(
    maker: async_sessionmaker[AsyncSession], app_for: FastAPI
) -> None:
    """§ 001011: a member, an admin without membership and a token without the scope get 403."""
    w = await _world(maker)
    admin = Principal(sub="admin-info", roles=["admin"])
    capped = Principal(
        sub=w.manager.sub, scope_permissions=frozenset({"gremium.view_all", "application.read"})
    )
    for principal in (w.member, admin, capped):
        resp = _client(app_for, principal).put(
            f"/api/committees/{w.gremium_id}/info", json=_body(0)
        )
        assert resp.status_code == 403, principal.sub
        assert resp.headers["content-type"].startswith("application/problem+json")
    scoped = Principal(
        sub=w.manager.sub, scope_permissions=frozenset({"info.write", "gremium.view_all"})
    )
    resp = _client(app_for, scoped).put(f"/api/committees/{w.gremium_id}/info", json=_body(0))
    assert resp.status_code == 200


@pytest.mark.parametrize(
    "links",
    [
        [{"label": "x", "url": "javascript:alert(1)"}],
        [{"label": "x", "url": "data:text/html,hi"}],
        [{"label": "x", "url": "https://"}],
        [{"label": "", "url": "https://a.de"}],
        [{"label": "x" * 81, "url": "https://a.de"}],
        [{"label": "x", "url": "https://a.de"}] * 31,
    ],
)
async def test_invalid_links_give_422(
    maker: async_sessionmaker[AsyncSession], app_for: FastAPI, links: list[dict[str, str]]
) -> None:
    """§ 001012: an unknown scheme, an empty or long label and more than 30 links give 422."""
    w = await _world(maker)
    resp = _client(app_for, w.manager).put(
        f"/api/committees/{w.gremium_id}/info", json=_body(0, links=links)
    )
    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/problem+json")


async def test_long_text_gives_422(
    maker: async_sessionmaker[AsyncSession], app_for: FastAPI
) -> None:
    """§ 001013: a text over 20 000 characters gives 422."""
    w = await _world(maker)
    resp = _client(app_for, w.manager).put(
        f"/api/committees/{w.gremium_id}/info", json=_body(0, bodyMd="x" * 20_001)
    )
    assert resp.status_code == 422


async def test_deleted_editor_leaves_no_name(
    maker: async_sessionmaker[AsyncSession], app_for: FastAPI
) -> None:
    """§ 001014: the last editor's name goes when the account goes (``SET NULL``)."""
    w = await _world(maker)
    _client(app_for, w.manager).put(f"/api/committees/{w.gremium_id}/info", json=_body(0))
    async with maker() as s:
        await s.execute(sa_delete(PrincipalRow).where(PrincipalRow.id == w.manager_id))
        await s.commit()
    viewer = Principal(sub="viewer-info-2", permissions={"gremium.view_all"})
    out = _client(app_for, viewer).get(f"/api/committees/{w.gremium_id}/info").json()
    assert out["version"] == 1
    assert out["updatedByName"] is None
