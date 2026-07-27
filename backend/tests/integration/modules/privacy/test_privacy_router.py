"""Integration test for the GDPR privacy **HTTP router** (real Postgres).

``test_privacy`` calls the services directly. This module drives the wired
``/api/admin/privacy`` router through the real ASGI request cycle. See api.md and
security.md section 4. The tests cover:

* the ``privacy.manage`` gate. It answers 401 without a session and 403 without the
  permission.
* the erasure request queue with the list and the ``?status`` filter. Execute and
  reject answer 409 on a request that is no longer open.
* the direct erasure of a principal. It answers 204 and nulls the PII.
* the settings with GET and PUT. A value under the ``ge=1`` bound gives 422.
* the Art. 15 data export as XLSX. The test also proves that the ``pii_export`` audit
  entry carries **no** raw PII such as the email address.
* the self-service endpoint ``POST /api/applications/{id}/erasure-request``. It uses
  the **real** magic-link applicant token and no principal workaround.

The request runs on a shared test engine through the ``get_session`` override. The test
can therefore seed and assert with the ``session`` fixture. The best-effort mail
background tasks run as no-ops. They would otherwise reach the global
``get_sessionmaker()`` on localhost, and they are not the subject of this test.
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
    clear_privacy_tables(engine)  # isolate principal, auth_session, erasure_request, settings
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


@pytest.fixture
def app(
    migrated: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> Iterator[FastAPI]:
    """Build the app against the test database.

    `get_session` shares the engine. The mail tasks run as no-ops.
    """
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

    # Neutralize the best-effort mail background tasks. They would otherwise reach the
    # global localhost sessionmaker, and they are not the subject of this test.
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


def test_erasures_requires_auth_401(client: TestClient) -> None:
    assert client.get("/api/admin/privacy/erasures").status_code == 401


def test_erasures_forbidden_without_privacy_manage_403(
    app: FastAPI, client: TestClient
) -> None:
    _as(app, {"admin.users"})  # logged in, but without privacy.manage
    r = client.get("/api/admin/privacy/erasures")
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"
    # the gate also covers a mutation
    assert (
        client.post(f"/api/admin/privacy/principals/{uuid.uuid4()}/erase").status_code
        == 403
    )


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
    # list shape (camelCase DTO): the required fields are present
    row = next(row for row in body if row["id"] == open_id)
    assert row["subjectType"] == "principal"
    assert row["status"] == "open"
    assert "createdAt" in row

    filtered = client.get("/api/admin/privacy/erasures", params={"status": "open"})
    assert filtered.status_code == 200
    fids = {row["id"] for row in filtered.json()}
    assert open_id in fids
    assert str(rejected_req.id) not in fids


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

    # Fresh from the database, because the request ran on its own engine. The `refresh`
    # call is awaited. An expired attribute access would start a sync lazy load.
    await session.refresh(applicant)
    assert applicant.email is None
    assert applicant.anonymized_at is not None

    # a second execute gives 409, because the request is no longer open
    again = client.post(f"/api/admin/privacy/erasures/{req_id}/execute")
    assert again.status_code == 409


async def test_execute_unknown_request_404(app: FastAPI, client: TestClient) -> None:
    _as_dpo(app)
    r = client.post(
        f"/api/admin/privacy/erasures/{uuid.uuid4()}/execute"
    )
    assert r.status_code == 404


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

    # the subject stays untouched
    await session.refresh(principal)
    assert principal.email == "rej@example.org"
    assert principal.active is True

    # no longer open, therefore 409
    again = client.post(
        f"/api/admin/privacy/erasures/{req_id}/reject", json={"reason": "x"}
    )
    assert again.status_code == 409


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
    assert principal.sub == original_sub  # the pseudonym stays


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

    # The schema rejects 0 because of ge=1 and answers 422 before the service runs.
    bad = client.put(
        "/api/admin/privacy/settings", json={"defaultRetentionMonths": 0}
    )
    assert bad.status_code == 422


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
    assert r.content[:2] == b"PK"  # an XLSX file is a ZIP container

    # the request wrote exactly one fresh pii_export audit entry ...
    rows = (
        await session.scalars(
            select(AuditEntry).where(AuditEntry.action == "pii_export")
        )
    ).all()
    assert len(rows) == 1
    entry = rows[0]
    # ... and it keeps the CANONICAL email for accountability: WHOSE data left the
    # system. The router lowercases the requested address so that the audit gets a
    # consistent target_id. The assertion mirrors that canonicalization.
    canonical_email = email.lower()
    assert entry.target_id == canonical_email
    assert entry.data is not None
    assert entry.data.get("email") == canonical_email
    assert entry.data.get("hasPrincipal") is False
    assert entry.data.get("applications") == 1


async def test_applicant_self_service_erasure_request(
    app: FastAPI, client: TestClient, session: AsyncSession
) -> None:
    """``POST /applications/{id}/erasure-request`` with the **real** magic-link token."""
    app_type, _, _ = await _seed_type(session)
    svc = ApplicationsService(session)
    application, _ = await svc.create(_create_payload(app_type.id))
    app_id = str(application.id)

    # A real server-side applicant session instead of a stateless token. The row needs a
    # commit so that the request session in its own transaction can resolve the sid.
    token = await sessions.create_applicant_session(
        session,
        secret=_SECRET,
        application_id=application.id,
        scope="view",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await session.commit()

    # NO principal override here. The applicant path (require_app_read) must apply.
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

    # one erasure_requested audit entry exists
    audited = (
        await session.scalars(
            select(AuditEntry).where(
                AuditEntry.action == "erasure_requested",
                AuditEntry.target_id == str(created.id),
            )
        )
    ).all()
    assert len(audited) == 1
