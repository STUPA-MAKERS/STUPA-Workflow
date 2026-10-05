"""#11: capture an application on behalf of an applicant (real Postgres).

A person with `application.create_on_behalf` enters an application for an account or
for a guest. The application belongs to the applicant. The capturing person shows only
in the history (version 1, the first status event, the capture block) and in the audit
log. The route validates against the effective form like a normal submission, and the
applicant gets the mail `application_captured`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.deps import get_current_principal
from app.modules.applications.models import (
    Applicant,
    Application,
    MagicLink,
    StatusEvent,
    SubmissionVersion,
)
from app.modules.applications.router import get_capture_mail_sender
from app.modules.audit.models import AuditEntry
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.notifications import captured as captured_mod
from app.modules.notifications.mail import MailMessage
from app.settings import Settings
from tests._support.guest_apps import GuestSeed, build_api, guest_settings, seed_guest_flow

pytestmark = pytest.mark.integration

_CLERK = Principal(
    sub="clerk-sub",
    roles=["member"],
    permissions={"application.create_on_behalf"},
    email="clerk@example.org",
    display_name="Clara Clerk",
)
_ADMIN = Principal(sub="admin-sub", roles=["admin"], email="admin@example.org")
_PLAIN = Principal(sub="plain-sub", roles=["member"], email="plain@example.org")

Sent = list[tuple[str, uuid.UUID, bool]]


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


async def _add_principal(
    maker: async_sessionmaker[AsyncSession],
    sub: str,
    email: str | None,
    name: str | None,
    *,
    active: bool = True,
) -> uuid.UUID:
    """Insert or reset an account. The `principal` table outlives one test."""
    async with maker() as session:
        row = await session.scalar(select(PrincipalRow).where(PrincipalRow.sub == sub))
        if row is None:
            row = PrincipalRow(sub=sub)
            session.add(row)
        row.email, row.display_name, row.active = email, name, active
        await session.commit()
        return row.id


def _client(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    principal: Principal | None,
    sent: Sent,
) -> TestClient:
    async def _sender(
        _settings: Settings, to: str, app_id: uuid.UUID, guest: bool, _pool: Any
    ) -> None:
        sent.append((to, app_id, guest))

    api = build_api(migrated[1], settings, monkeypatch)
    api.dependency_overrides[get_current_principal] = lambda: principal
    api.dependency_overrides[get_capture_mail_sender] = lambda: _sender
    return TestClient(api)


def _guest_body(seed: GuestSeed, **extra: Any) -> dict[str, Any]:
    return {
        "typeId": str(seed.type_id),
        "data": {"title": "Papierantrag"},
        "applicantName": "Gisela Gast",
        "applicantEmail": "gisela@example.org",
        **extra,
    }


async def _get(maker: async_sessionmaker[AsyncSession], app_id: uuid.UUID) -> Application:
    async with maker() as session:
        app = await session.get(Application, app_id)
        assert app is not None
        return app


async def _audit(
    maker: async_sessionmaker[AsyncSession], app_id: uuid.UUID, action: str
) -> AuditEntry:
    async with maker() as session:
        return (
            await session.scalars(
                select(AuditEntry).where(
                    AuditEntry.action == action, AuditEntry.target_id == str(app_id)
                )
            )
        ).one()


async def test_without_permission_answers_403_and_401(
    migrated: tuple[str, str],
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = await seed_guest_flow(maker)
    sent: Sent = []
    with _client(migrated, settings, monkeypatch, _PLAIN, sent) as client:
        resp = client.post("/api/applications/on-behalf", json=_guest_body(seed))
        assert resp.status_code == 403
        assert resp.headers["content-type"].startswith("application/problem+json")
        assert client.get("/api/applications/on-behalf/applicants?q=gi").status_code == 403
    with _client(migrated, settings, monkeypatch, None, sent) as client:
        assert (
            client.post("/api/applications/on-behalf", json=_guest_body(seed)).status_code
            == 401
        )
    assert sent == []
    async with maker() as session:
        assert (await session.scalars(select(Application))).all() == []


async def test_guest_capture_belongs_to_the_guest(
    migrated: tuple[str, str],
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = await seed_guest_flow(maker)
    await _add_principal(maker, "clerk-sub", "clerk@example.org", "Clara Clerk")
    sent: Sent = []
    body = _guest_body(seed, receivedOn="2026-01-15", intake="  per PDF  ")
    with _client(migrated, settings, monkeypatch, _CLERK, sent) as client:
        resp = client.post("/api/applications/on-behalf", json=body)
    assert resp.status_code == 201, resp.text
    app_id = uuid.UUID(resp.json()["applicationId"])

    app = await _get(maker, app_id)
    # The guest owns it through the magic link: no account owner.
    assert app.created_by is None
    assert app.captured_by == "clerk-sub"
    assert app.capture_intake == "per PDF"
    assert app.received_on == date(2026, 1, 15)
    # Submitted directly into the flow: no confirmation by the guest.
    assert app.email_confirmed_at is not None
    assert app.current_state_id == seed.open_state_id
    assert sent == [("gisela@example.org", app_id, True)]

    async with maker() as session:
        applicant = (
            await session.scalars(select(Applicant).where(Applicant.application_id == app_id))
        ).one()
        assert (applicant.email, applicant.name) == ("gisela@example.org", "Gisela Gast")
        version = (
            await session.scalars(
                select(SubmissionVersion).where(SubmissionVersion.application_id == app_id)
            )
        ).one()
        assert version.changed_by == "clerk-sub"
        event = (
            await session.scalars(select(StatusEvent).where(StatusEvent.application_id == app_id))
        ).one()
        assert event.actor == "clerk-sub"

    create = await _audit(maker, app_id, "application_create")
    assert create.actor == "clerk-sub"
    assert create.data["emailConfirmed"] is True
    behalf = await _audit(maker, app_id, "application_create_on_behalf")
    assert behalf.actor == "clerk-sub"
    assert behalf.data == {
        "applicantKind": "guest",
        "applicantPrincipalId": None,
        "receivedOn": "2026-01-15",
        "intake": True,
    }


async def test_account_capture_belongs_to_the_account(
    migrated: tuple[str, str],
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = await seed_guest_flow(maker)
    await _add_principal(maker, "clerk-sub", "clerk@example.org", "Clara Clerk")
    owner_id = await _add_principal(maker, "anna-sub", "anna@example.org", "Anna Antrag")
    sent: Sent = []
    body = {
        "typeId": str(seed.type_id),
        "data": {"title": "Per Mail"},
        "applicantPrincipalId": str(owner_id),
    }
    with _client(migrated, settings, monkeypatch, _CLERK, sent) as client:
        resp = client.post("/api/applications/on-behalf", json=body)
    assert resp.status_code == 201, resp.text
    app_id = uuid.UUID(resp.json()["applicationId"])

    app = await _get(maker, app_id)
    assert app.created_by == "anna-sub"
    assert app.captured_by == "clerk-sub"
    assert app.capture_intake is None
    # The default received date is today.
    assert app.received_on is not None
    assert abs((app.received_on - date.today()).days) <= 1
    assert sent == [("anna@example.org", app_id, False)]
    behalf = await _audit(maker, app_id, "application_create_on_behalf")
    assert behalf.data["applicantKind"] == "principal"
    assert behalf.data["applicantPrincipalId"] == str(owner_id)
    assert behalf.data["intake"] is False

    # The applicant reads it as the owner and sees the Gremium as the capturer.
    owner = Principal(sub="anna-sub", roles=["member"], email="anna@example.org")
    with _client(migrated, settings, monkeypatch, owner, sent) as client:
        detail = client.get(f"/api/applications/{app_id}")
        assert detail.status_code == 200, detail.text
        out = detail.json()
        assert out["isOwner"] is True
        assert out["applicant"]["email"] == "anna@example.org"
        assert out["capture"]["capturedBy"] == {
            "kind": "gremium",
            "key": None,
            "displayName": "G",
            "principalId": None,
        }
        assert out["capture"]["intake"] is None
        timeline = client.get(f"/api/applications/{app_id}/timeline").json()
        assert timeline[0]["actorInfo"]["kind"] == "gremium"
        mine = client.get("/api/applications?mine=true").json()
        assert [item["id"] for item in mine["items"]] == [str(app_id)]

    # A reader with the right sees the name of the capturing person.
    with _client(migrated, settings, monkeypatch, _ADMIN, sent) as client:
        out = client.get(f"/api/applications/{app_id}").json()
        captured_by = out["capture"]["capturedBy"]
        assert captured_by["kind"] == "principal"
        assert captured_by["displayName"] == "Clara Clerk"
        assert out["capture"]["receivedOn"] == app.received_on.isoformat()
        assert out["isOwner"] is False
        # A normal application carries no capture block.
        timeline = client.get(f"/api/applications/{app_id}/timeline").json()
        assert timeline[0]["actorInfo"]["displayName"] == "Clara Clerk"


@pytest.mark.parametrize(
    ("patch", "field"),
    [
        ({"data": {}}, "title"),
        ({"receivedOn": "2999-01-01"}, "receivedOn"),
    ],
)
async def test_invalid_capture_answers_422_and_writes_nothing(
    migrated: tuple[str, str],
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    patch: dict[str, Any],
    field: str,
) -> None:
    seed = await seed_guest_flow(maker)
    sent: Sent = []
    with _client(migrated, settings, monkeypatch, _CLERK, sent) as client:
        resp = client.post("/api/applications/on-behalf", json={**_guest_body(seed), **patch})
    assert resp.status_code == 422, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert field in {e["field"] for e in resp.json()["errors"]}
    assert sent == []
    async with maker() as session:
        assert (await session.scalars(select(Application))).all() == []


async def test_bad_applicant_answers_422(
    migrated: tuple[str, str],
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = await seed_guest_flow(maker)
    inactive = await _add_principal(maker, "gone-sub", "gone@example.org", "Gone", active=False)
    no_mail = await _add_principal(maker, "nomail-sub", None, "No Mail")
    sent: Sent = []
    base = {"typeId": str(seed.type_id), "data": {"title": "X"}}
    with _client(migrated, settings, monkeypatch, _CLERK, sent) as client:
        for principal_id in (inactive, no_mail, uuid.uuid4()):
            resp = client.post(
                "/api/applications/on-behalf",
                json={**base, "applicantPrincipalId": str(principal_id)},
            )
            assert resp.status_code == 422, resp.text
            assert resp.json()["code"] == "applicant_unavailable"
        # Both an account and a guest, or a guest without a name: schema errors.
        both = {**_guest_body(seed), "applicantPrincipalId": str(inactive)}
        assert client.post("/api/applications/on-behalf", json=both).status_code == 422
        nameless = {**_guest_body(seed), "applicantName": "  "}
        assert client.post("/api/applications/on-behalf", json=nameless).status_code == 422
    assert sent == []


async def test_body_cap_answers_413(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = await seed_guest_flow(maker)
    small = guest_settings(migrated[1]).model_copy(update={"max_application_payload_bytes": 64})
    sent: Sent = []
    body = _guest_body(seed, data={"title": "x" * 200})
    with _client(migrated, small, monkeypatch, _CLERK, sent) as client:
        assert client.post("/api/applications/on-behalf", json=body).status_code == 413


async def test_applicant_search(
    migrated: tuple[str, str],
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _add_principal(maker, "s-a", "quirin@example.org", "Quirin Quast")
    await _add_principal(maker, "s-b", "bert@example.org", "Bert")
    await _add_principal(maker, "s-c", "quilla@example.org", "Quilla", active=False)
    await _add_principal(maker, "s-d", None, "Quintus ohne Mail")
    sent: Sent = []
    with _client(migrated, settings, monkeypatch, _CLERK, sent) as client:
        hits = client.get("/api/applications/on-behalf/applicants?q=QU").json()
        assert [h["email"] for h in hits] == ["quirin@example.org"]
        assert hits[0]["displayName"] == "Quirin Quast"
        assert client.get("/api/applications/on-behalf/applicants?q=q").json() == []
        assert client.get("/api/applications/on-behalf/applicants").json() == []
        # A LIKE wildcard is a literal character.
        assert client.get("/api/applications/on-behalf/applicants?q=%25%25").json() == []


class _Queue:
    def __init__(self) -> None:
        self.messages: list[MailMessage] = []

    async def enqueue(self, msg: MailMessage) -> None:
        self.messages.append(msg)


async def _seed_captured(
    maker: async_sessionmaker[AsyncSession], seed: GuestSeed, *, owner: str | None
) -> uuid.UUID:
    async with maker() as session:
        from app.modules.flow.models import FlowVersion

        flow_id = (
            await session.scalars(select(FlowVersion.id).where(FlowVersion.active.is_(True)))
        ).one()
        from app.modules.forms.models import FormVersion

        form_id = (
            await session.scalars(
                select(FormVersion.id).where(FormVersion.application_type_id == seed.type_id)
            )
        ).first()
        app = Application(
            type_id=seed.type_id,
            form_version_id=form_id,
            flow_version_id=flow_id,
            current_state_id=seed.open_state_id,
            gremium_id=seed.gremium_id,
            data={"title": "Papier"},
            lang="de",
            created_by=owner,
            captured_by="clerk-sub",
            capture_intake="per Mail",
            received_on=date(2026, 10, 1),
        )
        session.add(app)
        await session.flush()
        session.add(
            Applicant(application_id=app.id, email="gisela@example.org", name="Gisela")
        )
        await session.commit()
        return app.id


@pytest.mark.parametrize("guest", [True, False])
async def test_capture_mail_links(
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    guest: bool,
) -> None:
    seed = await seed_guest_flow(maker)
    app_id = await _seed_captured(maker, seed, owner=None if guest else "anna-sub")
    monkeypatch.setattr(captured_mod, "get_sessionmaker", lambda: maker)
    queue = _Queue()
    await captured_mod.notify_application_captured(
        queue=queue,
        settings=settings,
        application_id=app_id,
        email="gisela@example.org",
        guest=guest,
    )
    (msg,) = queue.messages
    assert msg.to == ("gisela@example.org",)
    assert msg.subject == "Für dich wurde ein Antrag erfasst: „Papier“"
    assert "Eingegangen am 01.10.2026." in msg.text
    assert "Eingang: per Mail." in msg.text
    async with maker() as session:
        links = (
            await session.scalars(select(MagicLink).where(MagicLink.application_id == app_id))
        ).all()
    if guest:
        assert f"/antrag/{app_id}#t=" in msg.text
        assert len(links) == 1
    else:
        assert f"/applications/{app_id}\n" in msg.text
        assert "#t=" not in msg.text
        assert links == []
    # The same application coalesces into one mail.
    again = _Queue()
    await captured_mod.notify_application_captured(
        queue=again,
        settings=settings,
        application_id=app_id,
        email="gisela@example.org",
        guest=guest,
    )
    assert again.messages[0].idempotency_key == msg.idempotency_key


async def test_capture_mail_is_best_effort(
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(captured_mod, "get_sessionmaker", lambda: maker)
    queue = _Queue()
    # An unknown application sends nothing.
    await captured_mod.notify_application_captured(
        queue=queue,
        settings=settings,
        application_id=uuid.uuid4(),
        email="x@example.org",
        guest=False,
    )
    assert queue.messages == []

    def _boom() -> Any:
        raise RuntimeError("db down")

    monkeypatch.setattr(captured_mod, "get_sessionmaker", _boom)
    await captured_mod.notify_application_captured(
        queue=queue,
        settings=settings,
        application_id=uuid.uuid4(),
        email="x@example.org",
        guest=False,
    )
    assert queue.messages == []

