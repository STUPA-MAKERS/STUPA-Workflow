"""Router-Tests pdf (T-20): Endpunkt-Verdrahtung + A/P-Zugriff, Service gefaked."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_session
from app.deps import (
    Applicant,
    Principal,
    get_current_applicant,
    get_current_principal,
)
from app.main import create_app
from app.modules.pdf.models import RenderJob
from app.modules.pdf.router import get_pdf_service
from app.modules.pdf.schemas import JobOut
from app.shared.errors import NotFoundError

APP_ID = uuid4()
JOB_ID = uuid4()


class _FakeSession:
    async def commit(self) -> None: ...

    async def scalar(self, *_a: object, **_k: object) -> None:
        return None  # kein created_by → kein Ersteller-Zugriff

    async def execute(self, *_a: object, **_k: object) -> _EmptyResult:
        return _EmptyResult()  # keine Gremium-Mitgliedschaften (#vote-read)


class _EmptyResult:
    def scalars(self) -> _EmptyResult:
        return self

    def all(self) -> list[object]:
        return []

    def scalar_one_or_none(self) -> None:
        return None


class _FakeService:
    def __init__(self) -> None:
        self.created: list[UUID] = []

    async def create_application_job(
        self, application_id: UUID, *, idempotency_key: str | None = None
    ) -> RenderJob:
        self.created.append(application_id)
        job = RenderJob(application_id=application_id, status="pending")
        job.id = JOB_ID
        return job

    async def get_job(self, job_id: UUID) -> RenderJob:
        if str(job_id).startswith("00000000"):
            raise NotFoundError("nope")
        job = RenderJob(application_id=APP_ID, status="done", storage_key="k")
        job.id = job_id
        return job

    def to_out(self, job: RenderJob, *, storage: object = None, settings: object = None) -> JobOut:
        return JobOut(
            id=job.id,
            kind=job.kind or "application_pdf",
            status=job.status,
            applicationId=job.application_id,
            resultUrl="https://minio.local/k" if job.status == "done" else None,
        )


@pytest.fixture
def fake_service() -> _FakeService:
    return _FakeService()


@pytest.fixture
def app(fake_service: _FakeService) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_pdf_service] = lambda: fake_service

    def _session() -> Iterator[_FakeSession]:
        yield _FakeSession()

    application.dependency_overrides[get_session] = _session
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _principal(app: FastAPI, *perms: str) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="p", permissions=set(perms)
    )


def _applicant(app: FastAPI, application_id: UUID, scope: str = "view") -> None:
    app.dependency_overrides[get_current_applicant] = lambda: Applicant(
        application_id=str(application_id), scope=scope  # type: ignore[arg-type]
    )


# ------------------------------------------------------------------- POST /pdf
def test_create_pdf_requires_auth_401(client: TestClient) -> None:
    assert client.post(f"/api/applications/{APP_ID}/pdf").status_code == 401


def test_create_pdf_forbidden_without_read(app: FastAPI, client: TestClient) -> None:
    _principal(app, "other.perm")
    assert client.post(f"/api/applications/{APP_ID}/pdf").status_code == 403


def test_create_pdf_accepted_principal(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    _principal(app, "application.read")
    r = client.post(f"/api/applications/{APP_ID}/pdf")
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "pending"
    assert body["applicationId"] == str(APP_ID)
    assert fake_service.created == [APP_ID]


def test_create_pdf_accepted_applicant(app: FastAPI, client: TestClient) -> None:
    _applicant(app, APP_ID, "view")
    assert client.post(f"/api/applications/{APP_ID}/pdf").status_code == 202


# ------------------------------------------------------------------- GET /jobs
def test_get_job_requires_auth_401(client: TestClient) -> None:
    assert client.get(f"/api/jobs/{JOB_ID}").status_code == 401


def test_get_job_ok_principal(app: FastAPI, client: TestClient) -> None:
    _principal(app, "application.read")
    r = client.get(f"/api/jobs/{JOB_ID}")
    assert r.status_code == 200
    assert r.json()["resultUrl"] == "https://minio.local/k"


def test_get_job_not_found_404(app: FastAPI, client: TestClient) -> None:
    _principal(app, "application.read")
    r = client.get("/api/jobs/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


def test_get_job_cross_tenant_applicant_404(app: FastAPI, client: TestClient) -> None:
    # Antragsteller eines *fremden* Antrags → 404 (kein Existenz-Orakel).
    _applicant(app, uuid4(), "view")
    r = client.get(f"/api/jobs/{JOB_ID}")
    assert r.status_code == 404


def test_get_job_applicant_of_owning_application_ok(
    app: FastAPI, client: TestClient
) -> None:
    _applicant(app, APP_ID, "view")
    assert client.get(f"/api/jobs/{JOB_ID}").status_code == 200
