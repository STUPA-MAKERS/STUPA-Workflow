"""Observers of an application on a real Postgres.

§ F/applications/applications/000751 the applicant adds and removes up to five observers;
an observer and a member without ``application.manage`` cannot. § 000752 an observer
reads the application through an account or an e-mail session and changes nothing; the
lists mark the observed application. § 000753 the observer view has no ``isPII`` answer
and no applicant block. § 000754 the end link removes the observer without a login.
§ 000755 a removed observer gets 403 at once, the audit has no address, and the
anonymization deletes the observers.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.deps import get_current_applicant, get_current_principal
from app.modules.admin.service.forms import FormVersionWriter
from app.modules.applications import email_login
from app.modules.applications.models import Applicant as ApplicantRow
from app.modules.applications.models import ApplicationObserver
from app.modules.applications.observers import end_token
from app.modules.applications.observers_router import get_observer_mail_sender
from app.modules.applications.router import get_comment_mail_sender, get_magic_link_sender
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.audit.models import AuditEntry
from app.modules.auth.principal import Applicant, Principal
from app.modules.forms.schemas import FormVersionCreate
from app.settings import Settings
from app.shared.config_schemas import FormFieldDef
from tests._support.guest_apps import GuestSeed, build_api, guest_settings, seed_guest_flow

pytestmark = pytest.mark.integration

_OWNER = Principal(sub="owner-sub", roles=["member"], email="luis@example.org", display_name="Luis")
_OBSERVER = Principal(sub="adrian-sub", roles=["member"], email="Adrian@Example.org")
_STRANGER = Principal(sub="other-sub", roles=["member"], email="other@example.org")
_READER = Principal(
    sub="reader-sub", roles=["member"], permissions={"application.read"}, email="r@example.org"
)
_MANAGER = Principal(
    sub="manager-sub",
    roles=["member"],
    permissions={"application.read", "application.manage"},
    email="m@example.org",
)
_ADRIAN = "adrian@example.org"


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
    seed = await seed_guest_flow(maker)
    async with maker() as session:
        await FormVersionWriter(session).create_form_version(
            seed.type_id,
            FormVersionCreate(
                fields=[
                    FormFieldDef(key="title", type="text", label={"de": "Titel"}, required=True),
                    FormFieldDef.model_validate(
                        {"key": "iban", "type": "text", "label": {"de": "IBAN"}, "isPII": True}
                    ),
                ],
                activate=True,
            ),
            "tester",
        )
    return seed


@pytest.fixture
def mails() -> list[tuple[uuid.UUID, uuid.UUID]]:
    return []


def _client(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    mails: list[tuple[uuid.UUID, uuid.UUID]],
    principal: Principal | None,
    applicant: Applicant | None = None,
) -> TestClient:
    async def _no_mail(*_args: object) -> None:
        return None

    async def _record(
        _settings: Settings, app_id: uuid.UUID, obs_id: uuid.UUID, _p: object
    ) -> None:
        mails.append((app_id, obs_id))

    api = build_api(migrated[1], settings, monkeypatch)
    api.dependency_overrides[get_current_principal] = lambda: principal
    api.dependency_overrides[get_current_applicant] = lambda: applicant
    api.dependency_overrides[get_magic_link_sender] = lambda: _no_mail
    api.dependency_overrides[get_comment_mail_sender] = lambda: _no_mail
    api.dependency_overrides[get_observer_mail_sender] = lambda: _record
    return TestClient(api)


async def _create(maker: async_sessionmaker[AsyncSession], seed: GuestSeed) -> uuid.UUID:
    payload = ApplicationCreate.model_validate(
        {
            "typeId": str(seed.type_id),
            "data": {"title": "Druckauftrag Plakate", "iban": "DE02120300000000202051"},
            "applicantEmail": _OWNER.email,
            "applicantName": "Luis Meyer",
        }
    )
    async with maker() as session:
        app, _ = await ApplicationsService(session).create(
            payload, actor=_OWNER.sub, email_confirmed=True
        )
        return app.id


async def _observer_rows(maker: async_sessionmaker[AsyncSession], app_id: uuid.UUID) -> int:
    async with maker() as session:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(ApplicationObserver)
                .where(ApplicationObserver.application_id == app_id)
            )
            or 0
        )


async def _audit(maker: async_sessionmaker[AsyncSession], action: str) -> list[AuditEntry]:
    async with maker() as session:
        return list(
            await session.scalars(
                select(AuditEntry).where(AuditEntry.action == action).order_by(AuditEntry.id)
            )
        )


async def test_the_applicant_manages_up_to_five_observers(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
    mails: list[tuple[uuid.UUID, uuid.UUID]],
) -> None:
    """§ 000751 + § 000755: add, list, limit, duplicate, own address, remove, audit."""
    app_id = await _create(maker, seed)
    owner = _client(migrated, settings, monkeypatch, mails, _OWNER)
    base = f"/api/applications/{app_id}/observers"

    first = owner.post(base, json={"email": _ADRIAN})
    assert first.status_code == 201, first.text
    assert first.json()["email"] == _ADRIAN
    assert mails == [(app_id, uuid.UUID(first.json()["id"]))]
    assert owner.post(base, json={"email": _ADRIAN.upper()}).json()["code"] == "observer_exists"
    own = owner.post(base, json={"email": "LUIS@example.org"})
    assert own.status_code == 422
    assert own.json()["code"] == "observer_is_applicant"
    for n in range(4):
        assert owner.post(base, json={"email": f"p{n}@example.org"}).status_code == 201
    sixth = owner.post(base, json={"email": "six@example.org"})
    assert sixth.status_code == 422
    assert sixth.json()["code"] == "observer_limit"
    assert owner.post(base, json={"email": "kein-mail"}).status_code == 422

    listed = owner.get(base).json()
    assert [o["email"] for o in listed][0] == _ADRIAN
    assert len(listed) == 5
    gone = owner.delete(f"{base}/{listed[1]['id']}")
    assert gone.status_code == 204
    assert owner.delete(f"{base}/{listed[1]['id']}").status_code == 404
    assert await _observer_rows(maker, app_id) == 4

    added = await _audit(maker, "application_observer_add")
    removed = await _audit(maker, "application_observer_remove")
    assert len(added) == 5
    assert removed[0].data == {"observerId": listed[1]["id"]}
    assert all("@" not in json.dumps(e.data) for e in [*added, *removed])


async def test_only_the_applicant_and_a_manager_manage_observers(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
    mails: list[tuple[uuid.UUID, uuid.UUID]],
) -> None:
    """§ 000751: an observer, a reader and a stranger get 403; a manager and a session pass."""
    app_id = await _create(maker, seed)
    base = f"/api/applications/{app_id}/observers"
    assert (
        _client(migrated, settings, monkeypatch, mails, _OWNER)
        .post(base, json={"email": _ADRIAN})
        .status_code
        == 201
    )
    for who in (_OBSERVER, _READER, _STRANGER):
        client = _client(migrated, settings, monkeypatch, mails, who)
        assert client.get(base).status_code == 403
        assert client.post(base, json={"email": "x@example.org"}).status_code == 403
    observer_session = Applicant(email=_ADRIAN)
    client = _client(migrated, settings, monkeypatch, mails, None, observer_session)
    assert client.get(base).status_code == 403
    manager = _client(migrated, settings, monkeypatch, mails, _MANAGER)
    assert manager.post(base, json={"email": "m2@example.org"}).status_code == 201
    session = Applicant(email=_OWNER.email, application_ids=frozenset({str(app_id)}))
    applicant = _client(migrated, settings, monkeypatch, mails, None, session)
    assert len(applicant.get(base).json()) == 2
    assert _client(migrated, settings, monkeypatch, mails, None).get(base).status_code == 401


async def test_an_observer_reads_without_pii_and_changes_nothing(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
    mails: list[tuple[uuid.UUID, uuid.UUID]],
) -> None:
    """§ 000752 + § 000753: account and e-mail session read; every write gets 403."""
    app_id = await _create(maker, seed)
    owner = _client(migrated, settings, monkeypatch, mails, _OWNER)
    assert owner.post(f"/api/applications/{app_id}/observers", json={"email": _ADRIAN}).is_success
    assert owner.post(
        f"/api/applications/{app_id}/comments", json={"body": "Hallo", "visibility": "public"}
    ).is_success

    stranger = _client(migrated, settings, monkeypatch, mails, _STRANGER)
    assert stranger.get(f"/api/applications/{app_id}").status_code == 403

    for client in (
        _client(migrated, settings, monkeypatch, mails, _OBSERVER),
        _client(migrated, settings, monkeypatch, mails, None, Applicant(email=_ADRIAN)),
    ):
        detail = client.get(f"/api/applications/{app_id}")
        assert detail.status_code == 200, detail.text
        body: dict[str, Any] = detail.json()
        assert body["observer"] is True
        assert body["submittedBy"] == "Luis Meyer"
        assert body["canEdit"] is False
        assert body["isOwner"] is False
        assert body.get("applicant") is None
        assert "iban" not in body["data"]
        assert "iban" in body["hiddenKeys"]
        assert client.get(f"/api/applications/{app_id}/form").status_code == 200
        assert client.get(f"/api/applications/{app_id}/timeline").status_code == 200
        assert client.get(f"/api/applications/{app_id}/links").status_code == 200
        assert client.get(f"/api/applications/{app_id}/attachments").json() == []
        versions = client.get(f"/api/applications/{app_id}/versions").json()
        assert versions[0]["data"] is None
        comments = client.get(f"/api/applications/{app_id}/comments").json()
        assert [c["body"] for c in comments] == ["Hallo"]
        assert comments[0]["isOwn"] is False
        assert client.get(f"/api/applications/{app_id}/mentionable").status_code == 403

        assert (
            client.patch(
                f"/api/applications/{app_id}", json={"data": {"title": "X"}, "version": 1}
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/api/applications/{app_id}/comments", json={"body": "Hi", "visibility": "public"}
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/api/applications/{app_id}/applicant-transition",
                json={"transitionId": str(seed.transition_id)},
            ).status_code
            == 403
        )
        assert client.post(f"/api/applications/{app_id}/erasure-request").status_code == 403
        upload = client.post(
            f"/api/applications/{app_id}/attachments",
            files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")},
        )
        assert upload.status_code == 403


async def test_the_lists_mark_an_observed_application(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
    mails: list[tuple[uuid.UUID, uuid.UUID]],
) -> None:
    """§ 000752: the Anträge page and Meine Anträge show the observed application."""
    app_id = await _create(maker, seed)
    owner = _client(migrated, settings, monkeypatch, mails, _OWNER)
    assert owner.post(f"/api/applications/{app_id}/observers", json={"email": _ADRIAN}).is_success

    own_rows = owner.get("/api/applications").json()["items"]
    assert [(r["id"], r["observed"]) for r in own_rows] == [(str(app_id), False)]
    observer = _client(migrated, settings, monkeypatch, mails, _OBSERVER)
    rows = observer.get("/api/applications").json()["items"]
    assert [(r["id"], r["observed"]) for r in rows] == [(str(app_id), True)]
    assert observer.get("/api/applications?mine=true").json()["items"] == []
    reader = _client(migrated, settings, monkeypatch, mails, _READER)
    assert [r["observed"] for r in reader.get("/api/applications").json()["items"]] == [False]
    assert (
        _client(migrated, settings, monkeypatch, mails, _STRANGER)
        .get("/api/applications")
        .json()["items"]
        == []
    )

    session = _client(migrated, settings, monkeypatch, mails, None, Applicant(email=_ADRIAN))
    items = session.get("/api/applicant/applications").json()["items"]
    assert [(i["id"], i["observed"]) for i in items] == [(str(app_id), True)]
    both = Applicant(email=_ADRIAN, application_ids=frozenset({str(app_id)}))
    own = _client(migrated, settings, monkeypatch, mails, None, both)
    assert [i["observed"] for i in own.get("/api/applicant/applications").json()["items"]] == [
        False
    ]
    nobody = _client(migrated, settings, monkeypatch, mails, None, Applicant(email="n@example.org"))
    assert nobody.get("/api/applicant/applications").json()["items"] == []


async def test_a_removed_observer_loses_the_access(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
    mails: list[tuple[uuid.UUID, uuid.UUID]],
) -> None:
    """§ 000755 + § 000754: removal and the end link end the access at once."""
    app_id = await _create(maker, seed)
    owner = _client(migrated, settings, monkeypatch, mails, _OWNER)
    added = owner.post(f"/api/applications/{app_id}/observers", json={"email": _ADRIAN}).json()
    observer = _client(migrated, settings, monkeypatch, mails, _OBSERVER)
    assert observer.get(f"/api/applications/{app_id}").status_code == 200
    owner.delete(f"/api/applications/{app_id}/observers/{added['id']}")
    assert observer.get(f"/api/applications/{app_id}").status_code == 403

    again = owner.post(f"/api/applications/{app_id}/observers", json={"email": _ADRIAN}).json()
    anonymous = _client(migrated, settings, monkeypatch, mails, None)
    token = end_token(settings.magic_link_secret, uuid.UUID(again["id"]))
    forged = end_token("another-secret-of-thirty-chars-x", uuid.UUID(again["id"]))
    for bad in (forged, "kein-token", f"{uuid.uuid4()}.abc"):
        assert anonymous.post("/api/observers/end", json={"token": bad}).status_code == 404
    assert anonymous.post("/api/observers/end", json={"token": token}).status_code == 204
    assert anonymous.post("/api/observers/end", json={"token": token}).status_code == 404
    assert observer.get(f"/api/applications/{app_id}").status_code == 403
    removed = await _audit(maker, "application_observer_remove")
    assert removed[-1].data == {"observerId": again["id"], "via": "endLink"}


async def test_the_anonymization_deletes_the_observers(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
    mails: list[tuple[uuid.UUID, uuid.UUID]],
) -> None:
    """§ 000755: no observer row survives the anonymization; no new one is possible."""
    app_id = await _create(maker, seed)
    owner = _client(migrated, settings, monkeypatch, mails, _OWNER)
    assert owner.post(f"/api/applications/{app_id}/observers", json={"email": _ADRIAN}).is_success
    async with maker() as session:
        await ApplicationsService(session).anonymize(app_id)
    assert await _observer_rows(maker, app_id) == 0
    manager = _client(migrated, settings, monkeypatch, mails, _MANAGER)
    late = manager.post(f"/api/applications/{app_id}/observers", json={"email": _ADRIAN})
    assert late.status_code == 403
    async with maker() as session:
        row = await session.scalar(
            select(ApplicantRow).where(ApplicantRow.application_id == app_id)
        )
        assert row is not None
        assert row.email is None


async def test_an_observer_address_gets_the_email_login(
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    seed: GuestSeed,
) -> None:
    """§ 000752: the e-mail login sends a link to an address that only observes."""
    app_id = await _create(maker, seed)
    sent: list[str] = []
    async with maker() as session:
        await email_login.request_email_login(
            session, settings, email=_ADRIAN, send_link=lambda _e, link: sent.append(link)
        )
        session.add(ApplicationObserver(application_id=app_id, email=_ADRIAN))
        await session.commit()
        await email_login.request_email_login(
            session, settings, email=_ADRIAN.upper(), send_link=lambda _e, link: sent.append(link)
        )
        await session.commit()
    assert len(sent) == 1
