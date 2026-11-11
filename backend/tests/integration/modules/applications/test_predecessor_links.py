"""Folgeanträge on a real Postgres: the Vorgänger link, its checks, the history and the prefill.

§ F/applications/applications/000542 one Vorgänger of the same type, no self link, no
cycle, a delete drops the link. § 000543 the Vorgänger needs a login and the read right.
§ 000544 the prefill copies the fitting answers. § 000545 a later link adds only the
link, needs the edit right on both and writes audit and history. § 000546 the links show
only readable applications.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.deps import get_current_principal
from app.modules.admin.service.forms import FormVersionWriter
from app.modules.application_types.models import ApplicationType
from app.modules.applications.models import (
    Application,
    ApplicationLink,
    ApplicationLinkEvent,
    SubmissionVersion,
)
from app.modules.applications.router import get_magic_link_sender
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.audit.models import AuditEntry
from app.modules.auth.principal import Principal
from app.modules.forms.schemas import FormVersionCreate
from app.settings import Settings
from app.shared.antiabuse import verify_altcha_unless_authenticated
from app.shared.config_schemas import FormFieldDef
from tests._support.guest_apps import GuestSeed, build_api, guest_settings, seed_guest_flow

pytestmark = pytest.mark.integration

_OWNER = Principal(sub="owner-sub", roles=["member"], email="owner@example.org")
_OTHER = Principal(sub="other-sub", roles=["member"], email="other@example.org")
_READER = Principal(
    sub="reader-sub",
    roles=["member"],
    permissions={"application.read"},
    email="reader@example.org",
)
_MANAGER = Principal(
    sub="manager-sub",
    roles=["member"],
    permissions={"application.read", "application.manage"},
    email="manager@example.org",
)
_ADMIN = Principal(sub="admin-sub", roles=["admin"], email="admin@example.org")


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


@pytest.fixture
async def seed(maker: async_sessionmaker[AsyncSession]) -> GuestSeed:
    return await seed_guest_flow(maker)


def _client(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    principal: Principal | None,
) -> TestClient:
    async def _no_mail(*_args: object) -> None:
        return None

    api = build_api(migrated[1], settings, monkeypatch)
    api.dependency_overrides[get_current_principal] = lambda: principal
    api.dependency_overrides[get_magic_link_sender] = lambda: _no_mail
    return TestClient(api)


async def _create(
    maker: async_sessionmaker[AsyncSession],
    type_id: uuid.UUID,
    data: dict[str, Any],
    *,
    owner: Principal = _OWNER,
    predecessor: uuid.UUID | None = None,
) -> uuid.UUID:
    payload = ApplicationCreate.model_validate(
        {
            "typeId": str(type_id),
            "data": data,
            "applicantEmail": owner.email,
            "predecessorId": str(predecessor) if predecessor else None,
        }
    )
    async with maker() as session:
        app, _ = await ApplicationsService(session).create(
            payload, actor=owner.sub, email_confirmed=True
        )
        return app.id


async def _form(
    maker: async_sessionmaker[AsyncSession], type_id: uuid.UUID, fields: list[FormFieldDef]
) -> None:
    async with maker() as session:
        await FormVersionWriter(session).create_form_version(
            type_id, FormVersionCreate(fields=fields, activate=True), "tester"
        )


async def _second_type(maker: async_sessionmaker[AsyncSession], seed: GuestSeed) -> uuid.UUID:
    async with maker() as session:
        other = ApplicationType(
            gremium_id=seed.gremium_id,
            key=f"t2-{uuid.uuid4().hex[:8]}",
            name_i18n={},
            has_budget=False,
        )
        session.add(other)
        await session.commit()
        type_id = other.id
    await _form(
        maker,
        type_id,
        [FormFieldDef(key="title", type="text", label={"de": "Titel"}, required=True)],
    )
    return type_id


async def _count(maker: async_sessionmaker[AsyncSession], stmt: Any) -> int:
    async with maker() as session:
        return int(await session.scalar(stmt) or 0)


def _text(key: str, **extra: Any) -> FormFieldDef:
    return FormFieldDef.model_validate({"key": key, "type": "text", "label": {"de": key}, **extra})


async def test_create_with_predecessor_links_and_records(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 000544: the create saves the Vorgänger with history and audit."""
    old = await _create(maker, seed.type_id, {"title": "Sommerfest 2025"})
    client = _client(migrated, settings, monkeypatch, _OWNER)
    res = client.post(
        "/api/applications",
        json={
            "typeId": str(seed.type_id),
            "data": {"title": "Sommerfest 2026"},
            "predecessorId": str(old),
        },
    )
    assert res.status_code == 201, res.text
    new = uuid.UUID(res.json()["applicationId"])
    async with maker() as session:
        link = await session.get(ApplicationLink, new)
        assert link is not None
        assert link.predecessor_id == old
        assert link.linked_by == _OWNER.sub
    assert (
        await _count(
            maker,
            select(func.count())
            .select_from(AuditEntry)
            .where(AuditEntry.action == "application_link_set", AuditEntry.target_id == str(new)),
        )
        == 1
    )

    links = client.get(f"/api/applications/{new}/links").json()
    assert links["predecessor"]["id"] == str(old)
    assert links["predecessor"]["title"] == "Sommerfest 2025"
    assert [e["action"] for e in links["events"]] == ["set"]
    back = client.get(f"/api/applications/{old}/links").json()
    assert [s["id"] for s in back["successors"]] == [str(new)]


async def test_create_refuses_guest_unreadable_and_other_type(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 000543 and § 000542: login, read right and the same type."""
    old = await _create(maker, seed.type_id, {"title": "Alt"})
    body = {"typeId": str(seed.type_id), "data": {"title": "Neu"}, "predecessorId": str(old)}

    stranger = _client(migrated, settings, monkeypatch, _OTHER)
    assert stranger.post("/api/applications", json=body).status_code == 403

    guest_api = build_api(migrated[1], settings, monkeypatch)
    guest_api.dependency_overrides[get_current_principal] = lambda: None
    guest_api.dependency_overrides[verify_altcha_unless_authenticated] = lambda: None
    guest = TestClient(guest_api)
    guest_body = {**body, "applicantEmail": "gast@example.org"}
    res = guest.post("/api/applications", json=guest_body)
    assert res.status_code == 403, res.text

    other_type = await _second_type(maker, seed)
    owner = _client(migrated, settings, monkeypatch, _OWNER)
    res = owner.post(
        "/api/applications",
        json={**body, "typeId": str(other_type)},
    )
    assert res.status_code == 422
    assert res.json()["code"] == "predecessor_type_mismatch"
    assert await _count(maker, select(func.count()).select_from(ApplicationLink)) == 0


async def test_later_link_needs_edit_on_both_and_keeps_answers(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 000545: edit right on both, no new version, audit and history per change."""
    mine = await _create(maker, seed.type_id, {"title": "Meins"})
    foreign = await _create(maker, seed.type_id, {"title": "Fremd"}, owner=_OTHER)
    own_old = await _create(maker, seed.type_id, {"title": "Mein altes"})

    owner = _client(migrated, settings, monkeypatch, _OWNER)
    res = owner.put(f"/api/applications/{mine}/predecessor", json={"predecessorId": str(foreign)})
    assert res.status_code == 403

    res = owner.put(f"/api/applications/{mine}/predecessor", json={"predecessorId": str(own_old)})
    assert res.status_code == 200, res.text
    assert res.json()["predecessor"]["id"] == str(own_old)
    again = owner.put(f"/api/applications/{mine}/predecessor", json={"predecessorId": str(own_old)})
    assert again.status_code == 200
    assert owner.delete(f"/api/applications/{mine}/predecessor").status_code == 204
    assert owner.delete(f"/api/applications/{mine}/predecessor").status_code == 204

    assert (
        await _count(
            maker,
            select(func.count())
            .select_from(SubmissionVersion)
            .where(SubmissionVersion.application_id == mine),
        )
        == 1
    )
    async with maker() as session:
        app = await session.get(Application, mine)
        assert app is not None
        assert app.data == {"title": "Meins"}
        actions = (
            await session.scalars(
                select(AuditEntry.action)
                .where(AuditEntry.target_id == str(mine))
                .order_by(AuditEntry.id)
            )
        ).all()
        events = (
            await session.scalars(
                select(ApplicationLinkEvent.action)
                .where(ApplicationLinkEvent.application_id == mine)
                .order_by(ApplicationLinkEvent.at)
            )
        ).all()
    assert [a for a in actions if a.startswith("application_link")] == [
        "application_link_set",
        "application_link_remove",
    ]
    assert list(events) == ["set", "removed"]

    manager = _client(migrated, settings, monkeypatch, _MANAGER)
    res = manager.put(f"/api/applications/{mine}/predecessor", json={"predecessorId": str(foreign)})
    assert res.status_code == 200
    assert (
        manager.put(
            f"/api/applications/{mine}/predecessor", json={"predecessorId": str(mine)}
        ).json()["code"]
        == "predecessor_self"
    )


async def test_cycle_and_delete(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 000542: a cycle fails; a delete drops the link and keeps the Folgeantrag."""
    first = await _create(maker, seed.type_id, {"title": "Eins"})
    second = await _create(maker, seed.type_id, {"title": "Zwei"}, predecessor=first)
    third = await _create(maker, seed.type_id, {"title": "Drei"}, predecessor=second)

    admin = _client(migrated, settings, monkeypatch, _ADMIN)
    res = admin.put(f"/api/applications/{first}/predecessor", json={"predecessorId": str(third)})
    assert res.status_code == 422
    assert res.json()["code"] == "predecessor_cycle"

    async with maker() as session:
        await session.execute(delete(Application).where(Application.id == second))
        await session.commit()
    async with maker() as session:
        assert await session.get(Application, third) is not None
        assert await session.get(ApplicationLink, third) is None
    links = admin.get(f"/api/applications/{third}/links").json()
    assert links["predecessor"] is None
    assert links["events"][0]["predecessor"] is None


async def test_links_hide_unreadable(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 000546: a linked application that the reader cannot open stays hidden."""
    foreign = await _create(maker, seed.type_id, {"title": "Fremd"}, owner=_OTHER)
    mine = await _create(maker, seed.type_id, {"title": "Meins"})
    admin = _client(migrated, settings, monkeypatch, _ADMIN)
    assert (
        admin.put(
            f"/api/applications/{mine}/predecessor", json={"predecessorId": str(foreign)}
        ).status_code
        == 200
    )

    owner = _client(migrated, settings, monkeypatch, _OWNER)
    links = owner.get(f"/api/applications/{mine}/links").json()
    assert links["predecessor"] is None
    assert links["events"][0]["predecessor"] is None
    reader = _client(migrated, settings, monkeypatch, _READER)
    assert reader.get(f"/api/applications/{mine}/links").json()["predecessor"]["id"] == str(foreign)


async def test_prefill_copies_fitting_answers(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 000544: removed keys, invalid values, files and unreadable PII stay out."""
    await _form(
        maker,
        seed.type_id,
        [
            _text("title", required=True),
            _text("keep"),
            _text("gone"),
            _text("short"),
            FormFieldDef.model_validate(
                {"key": "iban", "type": "iban", "label": {"de": "IBAN"}, "isPII": True}
            ),
        ],
    )
    old = await _create(
        maker,
        seed.type_id,
        {
            "title": "Alt",
            "keep": "bleibt",
            "gone": "weg",
            "short": "viel zu lang",
            "iban": "DE89370400440532013000",
        },
    )
    await _form(
        maker,
        seed.type_id,
        [
            _text("title", required=True),
            _text("keep"),
            _text("short", validation={"maxLen": 3}),
            FormFieldDef.model_validate(
                {"key": "iban", "type": "iban", "label": {"de": "IBAN"}, "isPII": True}
            ),
            FormFieldDef.model_validate({"key": "doc", "type": "file", "label": {"de": "Doc"}}),
        ],
    )

    owner = _client(migrated, settings, monkeypatch, _OWNER)
    res = owner.get(f"/api/applications/{old}/prefill")
    assert res.status_code == 200, res.text
    assert res.json() == {
        "typeId": str(seed.type_id),
        "data": {"title": "Alt", "keep": "bleibt", "iban": "DE89370400440532013000"},
    }

    reader = _client(migrated, settings, monkeypatch, _READER)
    assert "iban" in reader.get(f"/api/applications/{old}/prefill").json()["data"]
    stranger = _client(migrated, settings, monkeypatch, _OTHER)
    assert stranger.get(f"/api/applications/{old}/prefill").status_code == 403
