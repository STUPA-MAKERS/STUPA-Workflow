"""New versions of an Antrag on a real Postgres (specs 001720-001722).

§ 001720 a denied or returned Antrag offers "Neue Fassung" to its applicant and to
``application.manage``; the new draft gets the answers. § 001721 both Anträge show the
link. § 001722 the submit of the new version moves the old Antrag into the target for
replaced Anträge, with the note "Ersetzt durch <number>".
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.deps import get_current_principal
from app.modules.applications.models import Application, StatusEvent
from app.modules.applications.router import get_magic_link_sender
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.audit.models import AuditEntry
from app.modules.auth.principal import Principal
from app.modules.flow.models import State
from app.modules.flow.service import FlowService
from app.settings import Settings
from tests._support.guest_apps import GuestSeed, build_api, guest_settings, seed_guest_flow

pytestmark = pytest.mark.integration

_OWNER = Principal(sub="owner-sub", roles=["member"], email="owner@example.org")
_OTHER = Principal(sub="other-sub", roles=["member"], email="other@example.org")
_MANAGER = Principal(
    sub="manager-sub",
    roles=["member"],
    permissions={"application.read", "application.manage"},
    email="manager@example.org",
)


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


async def _state(
    maker: async_sessionmaker[AsyncSession], seed: GuestSeed, key: str, **flags: bool
) -> uuid.UUID:
    """Add a state to the flow of the seed."""
    async with maker() as session:
        initial = await session.get(State, seed.open_state_id)
        assert initial is not None
        row = State(
            flow_version_id=initial.flow_version_id,
            key=key,
            label_i18n={"de": key},
            **flags,
        )
        session.add(row)
        await session.commit()
        return row.id


async def _replaced_target(maker: async_sessionmaker[AsyncSession], seed: GuestSeed) -> uuid.UUID:
    return await _state(
        maker,
        seed,
        "ersetzt",
        edit_allowed=False,
        is_terminal=True,
        is_denied=True,
        is_replaced_target=True,
    )


async def _create(maker: async_sessionmaker[AsyncSession], seed: GuestSeed) -> uuid.UUID:
    payload = ApplicationCreate.model_validate(
        {
            "typeId": str(seed.type_id),
            "data": {"title": "Sommerfest"},
            "applicantEmail": _OWNER.email,
        }
    )
    async with maker() as session:
        app, _ = await ApplicationsService(session).create(
            payload, actor=_OWNER.sub, email_confirmed=True
        )
        return app.id


async def _move(
    maker: async_sessionmaker[AsyncSession], app_id: uuid.UUID, state_id: uuid.UUID
) -> None:
    async with maker() as session:
        await session.execute(
            update(Application).where(Application.id == app_id).values(current_state_id=state_id)
        )
        await session.commit()


async def _app(maker: async_sessionmaker[AsyncSession], app_id: uuid.UUID) -> Application:
    async with maker() as session:
        app = await session.get(Application, app_id)
        assert app is not None
        return app


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


async def test_a_returned_antrag_gets_a_new_version_with_its_answers(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 001720, § 001721: the owner creates the draft, both Anträge show the link."""
    returned = await _state(maker, seed, "rueckfrage", edit_allowed=True)
    old = await _create(maker, seed)
    await _move(maker, old, returned)
    client = _client(migrated, settings, monkeypatch, _OWNER)

    res = client.post(f"/api/applications/{old}/new-version")
    assert res.status_code == 201, res.text
    assert res.json()["linkSent"] is False
    new = uuid.UUID(res.json()["applicationId"])
    draft = await _app(maker, new)
    assert draft.replaces_id == old
    assert draft.current_state_id == seed.open_state_id
    assert draft.created_by == _OWNER.sub
    assert draft.data["title"] == "Sommerfest"

    assert client.get(f"/api/applications/{new}/links").json()["replaces"]["id"] == str(old)
    back = client.get(f"/api/applications/{old}/links").json()
    assert [r["id"] for r in back["replacedBy"]] == [str(new)]
    async with maker() as session:
        audit = await session.scalar(
            select(AuditEntry).where(
                AuditEntry.action == "application_create", AuditEntry.target_id == str(new)
            )
        )
        assert audit is not None
        assert audit.data["replacesId"] == str(old)


async def test_a_manager_may_and_another_member_may_not(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 001720: the applicant and ``application.manage`` only; the owner stays the owner."""
    denied = await _state(maker, seed, "abgelehnt", is_terminal=True, is_denied=True)
    old = await _create(maker, seed)
    await _move(maker, old, denied)

    other = _client(migrated, settings, monkeypatch, _OTHER)
    assert other.post(f"/api/applications/{old}/new-version").status_code == 403

    manager = _client(migrated, settings, monkeypatch, _MANAGER)
    res = manager.post(f"/api/applications/{old}/new-version")
    assert res.status_code == 201, res.text
    draft = await _app(maker, uuid.UUID(res.json()["applicationId"]))
    assert draft.created_by == _OWNER.sub


async def test_a_draft_or_locked_antrag_offers_no_new_version(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 001720: the initial state and a locked state that is not denied refuse it."""
    old = await _create(maker, seed)
    client = _client(migrated, settings, monkeypatch, _OWNER)
    res = client.post(f"/api/applications/{old}/new-version")
    assert res.status_code == 409
    assert res.json()["code"] == "new_version_not_allowed"
    await _move(maker, old, seed.locked_state_id)
    assert client.post(f"/api/applications/{old}/new-version").status_code == 409


async def test_the_submit_closes_the_old_antrag(
    maker: async_sessionmaker[AsyncSession], seed: GuestSeed
) -> None:
    """§ 001722: the old Antrag moves into the target, with the note and an audit entry."""
    returned = await _state(maker, seed, "rueckfrage", edit_allowed=True)
    target = await _replaced_target(maker, seed)
    old = await _create(maker, seed)
    await _move(maker, old, returned)
    async with maker() as session:
        draft, _ = await ApplicationsService(session).new_version(
            old, actor=_OWNER.sub, hidden=set()
        )
        new = draft.id
    async with maker() as session:
        await FlowService(session).fire(new, seed.transition_id, _MANAGER)

    assert (await _app(maker, old)).current_state_id == target
    async with maker() as session:
        event = await session.scalar(
            select(StatusEvent)
            .where(StatusEvent.application_id == old)
            .order_by(StatusEvent.at.desc())
            .limit(1)
        )
        assert event is not None
        assert event.to_state_id == target
        assert event.note == f"Ersetzt durch {str(new)[:8].upper()}"
        audit = await session.scalar(
            select(AuditEntry).where(
                AuditEntry.action == "status_change",
                AuditEntry.target_id == str(old),
            )
        )
        assert audit is not None
        assert audit.data["replacedBy"] == str(new)


async def test_the_old_antrag_stays_without_target_or_when_terminal(
    maker: async_sessionmaker[AsyncSession], seed: GuestSeed
) -> None:
    """§ 001722: no target, or an old Antrag in a terminal state, changes nothing."""
    denied = await _state(maker, seed, "abgelehnt", is_terminal=True, is_denied=True)
    returned = await _state(maker, seed, "rueckfrage", edit_allowed=True)
    first = await _create(maker, seed)
    await _move(maker, first, returned)
    async with maker() as session:
        draft, _ = await ApplicationsService(session).new_version(
            first, actor=_OWNER.sub, hidden=set()
        )
    async with maker() as session:
        await FlowService(session).fire(draft.id, seed.transition_id, _MANAGER)
    assert (await _app(maker, first)).current_state_id == returned

    await _replaced_target(maker, seed)
    second = await _create(maker, seed)
    await _move(maker, second, denied)
    async with maker() as session:
        draft, _ = await ApplicationsService(session).new_version(
            second, actor=_OWNER.sub, hidden=set()
        )
    async with maker() as session:
        await FlowService(session).fire(draft.id, seed.transition_id, _MANAGER)
    assert (await _app(maker, second)).current_state_id == denied
