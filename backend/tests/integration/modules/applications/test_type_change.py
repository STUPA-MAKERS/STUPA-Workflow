"""Change of the Antragsart on a real Postgres (specs 001660-001663).

§ F/applications/applications/001660 the change writes a new version in the new form and
carries the values with the same key and type. § 001661 a missing required value needs a
transition into an editable state, and its note names the missing fields. § 001662 the old
version keeps every value. § 001663 the version history and the audit show both types.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.deps import get_current_principal
from app.modules.admin.service.forms import FormVersionWriter
from app.modules.application_types.models import ApplicationType
from app.modules.applications.models import Application, StatusEvent, SubmissionVersion
from app.modules.applications.router import get_magic_link_sender
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.audit.models import AuditEntry
from app.modules.auth.principal import Principal
from app.modules.flow.models import Transition
from app.modules.forms.schemas import FormVersionCreate
from app.settings import Settings
from app.shared.config_schemas import FormFieldDef
from tests._support.guest_apps import GuestSeed, build_api, guest_settings, seed_guest_flow

pytestmark = pytest.mark.integration

_CHANGER = Principal(
    sub="changer-sub",
    roles=["member"],
    permissions={"application.read_all", "application.transition", "application.change_type"},
    email="changer@example.org",
)
_READER = Principal(
    sub="reader-sub",
    roles=["member"],
    permissions={"application.read_all", "application.transition"},
    email="reader@example.org",
)
_OWNER = Principal(sub="owner-sub", roles=["member"], email="owner@example.org")


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


def _field(key: str, ftype: str = "text", **extra: Any) -> FormFieldDef:
    return FormFieldDef.model_validate(
        {"key": key, "type": ftype, "label": {"de": f"DE {key}", "en": f"EN {key}"}, **extra}
    )


async def _type(
    maker: async_sessionmaker[AsyncSession], seed: GuestSeed, fields: list[FormFieldDef]
) -> uuid.UUID:
    async with maker() as session:
        row = ApplicationType(
            gremium_id=seed.gremium_id,
            key=f"t-{uuid.uuid4().hex[:8]}",
            name_i18n={"de": f"Art {len(fields)}"},
            has_budget=False,
        )
        session.add(row)
        await session.commit()
        type_id = row.id
        await FormVersionWriter(session).create_form_version(
            type_id, FormVersionCreate(fields=fields, activate=True), "tester"
        )
    return type_id


async def _back_transition(maker: async_sessionmaker[AsyncSession], seed: GuestSeed) -> uuid.UUID:
    """Add the manual transition `gesperrt` -> `eingang` (editable) to the seed flow."""
    async with maker() as session:
        locked = await session.get(Transition, seed.transition_id)
        assert locked is not None
        back = Transition(
            flow_version_id=locked.flow_version_id,
            from_state_id=seed.locked_state_id,
            to_state_id=seed.open_state_id,
            label_i18n={"de": "Zur Überarbeitung"},
            guard=None,
            actions=[],
            order=1,
        )
        session.add(back)
        await session.commit()
        return back.id


async def _submitted(
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
    type_id: uuid.UUID,
    data: dict[str, Any],
) -> uuid.UUID:
    """Create an application and move it to the locked, non-initial state."""
    payload = ApplicationCreate.model_validate(
        {"typeId": str(type_id), "data": data, "applicantEmail": _OWNER.email, "lang": "de"}
    )
    async with maker() as session:
        app, _ = await ApplicationsService(session).create(
            payload, actor=_OWNER.sub, email_confirmed=True
        )
        await session.execute(
            update(Application)
            .where(Application.id == app.id)
            .values(current_state_id=seed.locked_state_id)
        )
        await session.commit()
        return app.id


async def _old_and_new(
    maker: async_sessionmaker[AsyncSession], seed: GuestSeed
) -> tuple[uuid.UUID, uuid.UUID]:
    old = await _type(
        maker,
        seed,
        [_field("zweck"), _field("anzahl", "number"), _field("nur_alt")],
    )
    new = await _type(
        maker,
        seed,
        [_field("zweck"), _field("anzahl", required=True), _field("neu", required=True)],
    )
    return old, new


async def test_change_with_missing_fields_sends_back(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 001660, 001661, 001662, 001663: carry, send back with a note, keep, record."""
    old_type, new_type = await _old_and_new(maker, seed)
    back = await _back_transition(maker, seed)
    app_id = await _submitted(
        maker,
        seed,
        old_type,
        {"title": "Sommerfest", "zweck": "Feier", "anzahl": 3, "nur_alt": "x"},
    )
    client = _client(migrated, settings, monkeypatch, _CHANGER)

    preview = client.get(
        f"/api/applications/{app_id}/type-change", params={"typeId": str(new_type)}
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert [f["key"] for f in body["carried"]] == ["title", "zweck"]
    assert sorted(f["key"] for f in body["missing"]) == ["anzahl", "neu"]
    assert sorted(f["key"] for f in body["dropped"]) == ["anzahl", "nur_alt"]
    assert [t["id"] for t in body["transitions"]] == [str(back)]
    assert body["possible"] is True

    res = client.post(f"/api/applications/{app_id}/type-change", json={"typeId": str(new_type)})
    assert res.status_code == 422
    assert res.json()["code"] == "type_change_transition_required"

    res = client.post(
        f"/api/applications/{app_id}/type-change",
        json={"typeId": str(new_type), "transitionId": str(back), "note": "Bitte ergänzen."},
    )
    assert res.status_code == 200, res.text

    async with maker() as session:
        app = await session.get(Application, app_id)
        assert app is not None
        assert app.type_id == new_type
        target = await session.get(ApplicationType, new_type)
        assert target is not None
        assert app.form_version_id == target.active_form_version_id
        assert app.current_state_id == seed.open_state_id
        assert app.data == {"title": "Sommerfest", "zweck": "Feier"}
        versions = (
            await session.scalars(
                select(SubmissionVersion)
                .where(SubmissionVersion.application_id == app_id)
                .order_by(SubmissionVersion.version)
            )
        ).all()
        assert [v.version for v in versions] == [1, 2]
        assert versions[0].data["nur_alt"] == "x"
        assert versions[0].data["anzahl"] == 3
        assert versions[1].from_type_id == old_type
        assert versions[1].to_type_id == new_type
        event = (
            await session.scalars(
                select(StatusEvent).where(
                    StatusEvent.application_id == app_id, StatusEvent.transition_id == back
                )
            )
        ).one()
        assert event.note is not None
        assert "DE anzahl" in event.note
        assert "DE neu" in event.note
        assert event.note.endswith("Bitte ergänzen.")
        audit = (
            await session.scalars(
                select(AuditEntry).where(
                    AuditEntry.action == "application_type_change",
                    AuditEntry.target_id == str(app_id),
                )
            )
        ).one()
        assert audit.data["fromTypeId"] == str(old_type)
        assert audit.data["toTypeId"] == str(new_type)
        assert audit.data["missingFields"] == ["anzahl", "neu"]

    history = client.get(f"/api/applications/{app_id}/versions").json()
    change = history[1]["typeChange"]
    assert change["fromTypeId"] == str(old_type)
    assert change["toTypeId"] == str(new_type)
    assert set(change["fieldLabels"]) == {"anzahl", "nur_alt"}
    assert history[0]["data"]["nur_alt"] == "x"


async def test_change_without_missing_fields_keeps_state(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 001660: nothing missing, no transition, the state stays."""
    old_type, _ = await _old_and_new(maker, seed)
    target = await _type(maker, seed, [_field("zweck", required=True)])
    app_id = await _submitted(maker, seed, old_type, {"title": "T", "zweck": "Z"})
    client = _client(migrated, settings, monkeypatch, _CHANGER)

    preview = client.get(f"/api/applications/{app_id}/type-change", params={"typeId": str(target)})
    assert preview.json()["missing"] == []
    assert preview.json()["transitions"] == []

    needless = client.post(
        f"/api/applications/{app_id}/type-change",
        json={"typeId": str(target), "transitionId": str(seed.transition_id)},
    )
    assert needless.status_code == 422
    assert needless.json()["code"] == "type_change_transition_not_needed"

    res = client.post(f"/api/applications/{app_id}/type-change", json={"typeId": str(target)})
    assert res.status_code == 200, res.text
    async with maker() as session:
        app = await session.get(Application, app_id)
        assert app is not None
        assert app.type_id == target
        assert app.current_state_id == seed.locked_state_id


async def test_change_refusals(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 001660 and § 001661: permission, same type, initial state, no editable transition."""
    old_type, new_type = await _old_and_new(maker, seed)
    app_id = await _submitted(maker, seed, old_type, {"title": "T"})
    url = f"/api/applications/{app_id}/type-change"

    reader = _client(migrated, settings, monkeypatch, _READER)
    assert reader.post(url, json={"typeId": str(new_type)}).status_code == 403

    client = _client(migrated, settings, monkeypatch, _CHANGER)
    same = client.post(url, json={"typeId": str(old_type)})
    assert same.status_code == 422
    assert same.json()["code"] == "type_change_same_type"

    preview = client.get(url, params={"typeId": str(new_type)})
    assert preview.json()["possible"] is False
    blocked = client.post(url, json={"typeId": str(new_type)})
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "type_change_no_edit_transition"

    async with maker() as session:
        await session.execute(
            update(Application)
            .where(Application.id == app_id)
            .values(current_state_id=seed.open_state_id)
        )
        await session.commit()
    initial = client.post(url, json={"typeId": str(new_type)})
    assert initial.status_code == 409
    assert initial.json()["code"] == "type_change_not_submitted"
