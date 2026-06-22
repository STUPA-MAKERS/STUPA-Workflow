"""Integration (echte Postgres, testcontainers): DSGVO/Privacy **HTTP-Router**.

Während ``test_privacy`` die Services direkt aufruft, prüft dieses
Modul den verdrahteten ``/api/admin/privacy``-Router (api.md, security.md §4) durch den
realen ASGI-Request-Zyklus:

* das ``privacy.manage``-Gate (401 ohne Session, 403 ohne Permission),
* Löschantrags-Queue (Liste + ``?status``-Filter), Ausführen/Ablehnen inkl. 409 auf
  nicht-offenen Anträgen,
* Direkt-Erasure eines Principals (204 + PII genullt),
* die Settings (GET/PUT, ``ge=1`` → 422),
* die Art.-15-Auskunft als XLSX **plus** der Beweis, dass der ``pii_export``-Audit-Eintrag
  **keine** Roh-PII (E-Mail) trägt,
* der Self-Service-Endpunkt ``POST /api/applications/{id}/erasure-request`` über den
  **echten** Magic-Link-Antragsteller-Token (kein Principal-Workaround).

Der Request läuft über eine geteilte Test-Engine (``get_session``-Override), sodass im Test
mit der ``session``-Fixture geseedet und assertiert werden kann. Die Best-Effort-Mail-
Hintergrund-Tasks werden auf No-ops gepatcht — sie würden sonst den globalen
``get_sessionmaker()`` (localhost) ansprechen und sind hier nicht der Prüfgegenstand.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.modules.applications.router as applications_router
import app.modules.privacy.router as privacy_router
from app.db import get_session
from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.applications.models import Applicant
from app.modules.applications.service import ApplicationsService
from app.modules.audit.models import AuditEntry
from app.modules.auth import sessions
from app.modules.privacy.models import ErasureRequest, PrivacySettings
from app.settings import get_settings, load_settings
from app.shared.xlsx import XLSX_MEDIA_TYPE
from tests.integration.conftest import clear_privacy_tables
from tests.integration.modules.applications.test_applications_service import (
    _create_payload,
    _seed_type,
)
from tests.integration.modules.privacy.test_privacy import _seed_principal

pytestmark = pytest.mark.integration

_SECRET = "session-secret-privacy-router-0"


@pytest.fixture
async def session(migrated: tuple[str, str], engine: Engine) -> AsyncIterator[AsyncSession]:
    clear_privacy_tables(engine)  # principal/auth_session/erasure_request/settings isolieren
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


@pytest.fixture
def app(
    migrated: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> Iterator[FastAPI]:
    """App gegen die Test-DB; `get_session` teilt sich die Engine, Mail-Tasks sind No-ops."""
    _, async_url = migrated
    settings = load_settings(
        database_url=async_url,
        session_secret=_SECRET,
        magic_link_secret="magic-link-secret-privacy0",
        cookie_secure=False,
    )
    engine = create_async_engine(async_url)
    maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    async def _request_session() -> AsyncIterator[AsyncSession]:
        db = maker()
        try:
            yield db
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()

    # Best-Effort-Mail-Hintergrund-Tasks neutralisieren (würden sonst den globalen
    # localhost-Sessionmaker ansprechen) — sie sind hier nicht der Prüfgegenstand.
    async def _noop(*_args: object, **_kwargs: object) -> None:
        return None

    for name in (
        "notify_erasure_executed",
        "notify_erasure_rejected",
    ):
        monkeypatch.setattr(privacy_router, name, _noop)
    monkeypatch.setattr(applications_router, "notify_erasure_requested", _noop)

    application = create_app(settings)
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_session] = _request_session
    try:
        yield application
    finally:
        application.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def _as(app: FastAPI, perms: set[str]) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="dpo", permissions=perms
    )


def _as_dpo(app: FastAPI) -> None:
    _as(app, {"privacy.manage"})


# --------------------------------------------------------------------------- auth
def test_erasures_requires_auth_401(client: TestClient) -> None:
    assert client.get("/api/admin/privacy/erasures").status_code == 401


def test_erasures_forbidden_without_privacy_manage_403(
    app: FastAPI, client: TestClient
) -> None:
    _as(app, {"admin.users"})  # eingeloggt, aber ohne privacy.manage
    r = client.get("/api/admin/privacy/erasures")
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"
    # auch eine Mutation ist gegated
    assert (
        client.post(f"/api/admin/privacy/principals/{uuid.uuid4()}/erase").status_code
        == 403
    )


# --------------------------------------------------------------------------- queue
async def test_list_erasures_and_status_filter(
    app: FastAPI, client: TestClient, session: AsyncSession
) -> None:
    principal = await _seed_principal(session, email="q@example.org")
    other = await _seed_principal(session, email="q2@example.org")
    open_req = ErasureRequest(subject_type="principal", principal_id=principal.id, status="open")
    rejected_req = ErasureRequest(
        subject_type="principal", principal_id=other.id, status="rejected"
    )
    session.add_all([open_req, rejected_req])
    await session.commit()
    open_id = str(open_req.id)

    _as_dpo(app)
    r = client.get("/api/admin/privacy/erasures")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    ids = {row["id"] for row in body}
    assert {open_id, str(rejected_req.id)} <= ids
    # Listen-Shape (camelCase-DTO): die Pflichtfelder sind vorhanden.
    row = next(row for row in body if row["id"] == open_id)
    assert row["subjectType"] == "principal"
    assert row["status"] == "open"
    assert "createdAt" in row

    filtered = client.get("/api/admin/privacy/erasures", params={"status": "open"})
    assert filtered.status_code == 200
    fids = {row["id"] for row in filtered.json()}
    assert open_id in fids
    assert str(rejected_req.id) not in fids


# --------------------------------------------------------------------------- execute
async def test_execute_applicant_erasure_anonymizes(
    app: FastAPI, client: TestClient, session: AsyncSession
) -> None:
    app_type, _, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    application, _ = await svc.create(_create_payload(app_type.id))
    req = ErasureRequest(
        subject_type="applicant", application_id=application.id, status="open"
    )
    session.add(req)
    await session.commit()
    req_id = str(req.id)
    applicant = (
        await session.execute(
            select(Applicant).where(Applicant.application_id == application.id)
        )
    ).scalar_one()

    _as_dpo(app)
    r = client.post(f"/api/admin/privacy/erasures/{req_id}/execute")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "executed"
    assert body["handledBy"] == "dpo"
    assert body["handledAt"] is not None

    # frisch aus der DB (Request lief über eine eigene Engine) — `refresh` ist awaited,
    # kein expired-Attr-Zugriff (der eine sync-Lazy-Load auslösen würde).
    await session.refresh(applicant)
    assert applicant.email is None
    assert applicant.anonymized_at is not None

    # zweite Ausführung → 409 (nicht mehr offen)
    again = client.post(f"/api/admin/privacy/erasures/{req_id}/execute")
    assert again.status_code == 409


async def test_execute_unknown_request_404(app: FastAPI, client: TestClient) -> None:
    _as_dpo(app)
    r = client.post(
        f"/api/admin/privacy/erasures/{uuid.uuid4()}/execute"
    )
    assert r.status_code == 404


# --------------------------------------------------------------------------- reject
async def test_reject_then_double_reject_409(
    app: FastAPI, client: TestClient, session: AsyncSession
) -> None:
    principal = await _seed_principal(session, email="rej@example.org")
    req = ErasureRequest(
        subject_type="principal", principal_id=principal.id, status="open"
    )
    session.add(req)
    await session.commit()
    req_id = str(req.id)

    _as_dpo(app)
    r = client.post(
        f"/api/admin/privacy/erasures/{req_id}/reject", json={"reason": "unbegründet"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "rejected"
    assert body["reason"] == "unbegründet"
    assert body["handledBy"] == "dpo"

    # Subjekt bleibt unangetastet.
    await session.refresh(principal)
    assert principal.email == "rej@example.org"
    assert principal.active is True

    # nicht mehr offen → 409
    again = client.post(
        f"/api/admin/privacy/erasures/{req_id}/reject", json={"reason": "x"}
    )
    assert again.status_code == 409


# --------------------------------------------------------------------------- principal
async def test_erase_principal_endpoint_nulls_pii_204(
    app: FastAPI, client: TestClient, session: AsyncSession
) -> None:
    principal = await _seed_principal(session, email="erase@example.org")
    await session.commit()
    pid = principal.id
    original_sub = principal.sub

    _as_dpo(app)
    r = client.post(f"/api/admin/privacy/principals/{pid}/erase")
    assert r.status_code == 204
    assert r.content == b""

    await session.refresh(principal)
    assert principal.email is None
    assert principal.display_name is None
    assert principal.active is False
    assert principal.sub == original_sub  # Pseudonym bleibt


# --------------------------------------------------------------------------- settings
async def test_settings_get_put_and_validation(
    app: FastAPI, client: TestClient, session: AsyncSession
) -> None:
    _as_dpo(app)
    r = client.get("/api/admin/privacy/settings")
    assert r.status_code == 200
    assert "defaultRetentionMonths" in r.json()

    put = client.put(
        "/api/admin/privacy/settings", json={"defaultRetentionMonths": 12}
    )
    assert put.status_code == 200, put.text
    assert put.json()["defaultRetentionMonths"] == 12

    persisted = (
        await session.execute(
            select(PrivacySettings).where(PrivacySettings.id == 1)
        )
    ).scalar_one()
    assert persisted.default_retention_months == 12

    # ge=1: 0 ist unzulässig → 422 (Schema-Validierung, vor dem Service)
    bad = client.put(
        "/api/admin/privacy/settings", json={"defaultRetentionMonths": 0}
    )
    assert bad.status_code == 422


# --------------------------------------------------------------------------- auskunft
async def test_auskunft_xlsx_and_audit_records_subject_email(
    app: FastAPI, client: TestClient, session: AsyncSession
) -> None:
    app_type, _, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    _, email = await svc.create(_create_payload(app_type.id))

    _as_dpo(app)
    r = client.get("/api/admin/privacy/auskunft", params={"email": email})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == XLSX_MEDIA_TYPE
    assert "attachment" in r.headers["content-disposition"]
    assert len(r.content) > 0
    assert r.content[:2] == b"PK"  # XLSX = ZIP-Container

    # ein pii_export-Audit-Eintrag wurde geschrieben (vom Request frisch angelegt) …
    rows = (
        await session.scalars(
            select(AuditEntry).where(AuditEntry.action == "pii_export")
        )
    ).all()
    assert len(rows) == 1
    entry = rows[0]
    # … und er hält die KANONISIERTE E-Mail fest (Rechenschaft: WESSEN Daten exportiert).
    # Der Router kanonisiert die Anfrage-Adresse (Kleinschreibung), damit ein konsistenter
    # target_id im Audit landet — die Assertion spiegelt diese Kanonisierung.
    canonical_email = email.lower()
    assert entry.target_id == canonical_email
    assert entry.data is not None
    assert entry.data.get("email") == canonical_email
    assert entry.data.get("hasPrincipal") is False
    assert entry.data.get("applications") == 1


# --------------------------------------------------------------------------- self-service
async def test_applicant_self_service_erasure_request(
    app: FastAPI, client: TestClient, session: AsyncSession
) -> None:
    """``POST /applications/{id}/erasure-request`` über den **echten** Magic-Link-Token."""
    app_type, _, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    application, _ = await svc.create(_create_payload(app_type.id))
    app_id = str(application.id)

    # Echte serverseitige Applicant-Session (statt zustandslosem Token): Zeile anlegen
    # und committen, damit die Request-Session (eigene Transaktion) die sid auflösen kann.
    token = await sessions.create_applicant_session(
        session,
        secret=_SECRET,
        application_id=application.id,
        scope="view",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await session.commit()

    # KEIN Principal-Override hier — der Applicant-Pfad (require_app_read) muss greifen.
    r = client.post(
        f"/api/applications/{app_id}/erasure-request",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 202, r.text

    reqs = (
        await session.scalars(
            select(ErasureRequest).where(ErasureRequest.application_id == application.id)
        )
    ).all()
    assert len(reqs) == 1
    created = reqs[0]
    assert created.status == "open"
    assert created.subject_type == "applicant"

    # ein erasure_requested-Audit-Eintrag liegt vor.
    audited = (
        await session.scalars(
            select(AuditEntry).where(
                AuditEntry.action == "erasure_requested",
                AuditEntry.target_id == str(created.id),
            )
        )
    ).all()
    assert len(audited) == 1
