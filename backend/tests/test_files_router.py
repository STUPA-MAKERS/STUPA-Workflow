"""Router-Tests files (T-13): Endpunkt-Verdrahtung + RBAC, Service gefaked."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import Principal, get_current_principal, get_session
from app.main import create_app
from app.modules.files.models import Attachment
from app.modules.files.router import get_files_service
from app.modules.files.schemas import AttachmentOut, SignedUrlOut
from app.modules.files.service import FilesService
from app.settings import load_settings
from app.shared.errors import NotFoundError

APP_ID = uuid4()
ATT_ID = uuid4()


class _FakeService:
    max_bytes = 10 * 1024 * 1024

    def __init__(self) -> None:
        self.uploaded: list[tuple[UUID, str | None, int]] = []

    async def upload(
        self,
        application_id: UUID,
        *,
        filename: str | None,
        data: bytes,
        by: str,
        field_key: str | None = None,
        is_comparison_offer: bool = False,
    ) -> AttachmentOut:
        self.uploaded.append((application_id, filename, len(data)))
        return AttachmentOut(
            id=ATT_ID,
            filename=filename or "f",
            mime="application/pdf",
            size=len(data),
            scanned=False,
            is_comparison_offer=is_comparison_offer,
        )

    async def get_attachment(self, attachment_id: UUID) -> Attachment:
        if str(attachment_id).startswith("00000000"):
            raise NotFoundError("nope")
        att = Attachment(
            application_id=APP_ID,
            filename="doc.pdf",
            mime="application/pdf",
            size=3,
            storage_key="k",
        )
        att.id = attachment_id
        return att

    async def signed_url(self, attachment_id: UUID) -> SignedUrlOut:
        return SignedUrlOut(url="https://minio.local/k", expiresIn=300)

    async def delete(self, attachment_id: UUID, *, actor: str) -> None:
        self.deleted = attachment_id

    async def list_for_application(self, application_id: UUID) -> list[AttachmentOut]:
        self.listed = application_id
        return [
            AttachmentOut(
                id=ATT_ID, filename="doc.pdf", mime="application/pdf",
                size=3, scanned=True, is_comparison_offer=False,
            )
        ]


@pytest.fixture
def fake_service() -> _FakeService:
    return _FakeService()


class _NoCreatorDb:
    """Session-Stub: ``scalar`` → None (kein created_by) für den Ersteller-Check (#24)."""

    async def scalar(self, *_a: object, **_k: object) -> None:
        return None


async def _fake_session():  # noqa: ANN202
    yield _NoCreatorDb()


@pytest.fixture
def app(fake_service: _FakeService) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_files_service] = lambda: fake_service
    # require_app_edit/read fragen created_by ab — ohne echte DB ein No-Creator-Stub.
    application.dependency_overrides[get_session] = _fake_session
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _as(app: FastAPI, *perms: str) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="p", permissions=set(perms)
    )


# --------------------------------------------------------------------------- upload
def test_upload_requires_auth_401(client: TestClient) -> None:
    r = client.post(
        f"/api/applications/{APP_ID}/attachments",
        files={"file": ("doc.pdf", b"%PDF", "application/pdf")},
    )
    assert r.status_code == 401


def test_list_attachments_ok(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    _as(app, "application.read")
    r = client.get(f"/api/applications/{APP_ID}/attachments")
    assert r.status_code == 200
    assert r.json()[0]["filename"] == "doc.pdf"
    assert fake_service.listed == APP_ID


def test_upload_forbidden_without_manage(app: FastAPI, client: TestClient) -> None:
    _as(app, "application.read")
    r = client.post(
        f"/api/applications/{APP_ID}/attachments",
        files={"file": ("doc.pdf", b"%PDF", "application/pdf")},
    )
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"


def test_upload_ok(app: FastAPI, client: TestClient, fake_service: _FakeService) -> None:
    _as(app, "application.manage")
    r = client.post(
        f"/api/applications/{APP_ID}/attachments",
        files={"file": ("doc.pdf", b"%PDF-data", "application/pdf")},
        data={"is_comparison_offer": "true"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["filename"] == "doc.pdf"
    assert body["scanned"] is False
    assert body["is_comparison_offer"] is True
    assert fake_service.uploaded[0][0] == APP_ID


def test_upload_missing_file_422(app: FastAPI, client: TestClient) -> None:
    _as(app, "application.manage")
    r = client.post(f"/api/applications/{APP_ID}/attachments")
    assert r.status_code == 422


def test_upload_too_large_413(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    _as(app, "application.manage")
    fake_service.max_bytes = 8  # gekapptes Lesen im Router → 413 vor dem Service
    r = client.post(
        f"/api/applications/{APP_ID}/attachments",
        files={"file": ("doc.pdf", b"x" * 64, "application/pdf")},
    )
    assert r.status_code == 413


# --------------------------------------------------------------------------- download
def test_get_url_requires_auth_401(client: TestClient) -> None:
    assert client.get(f"/api/attachments/{ATT_ID}").status_code == 401


def test_get_url_not_found_404(app: FastAPI, client: TestClient) -> None:
    _as(app, "application.read")
    r = client.get("/api/attachments/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


def test_get_url_ok(app: FastAPI, client: TestClient) -> None:
    _as(app, "application.read")
    r = client.get(f"/api/attachments/{ATT_ID}")
    assert r.status_code == 200
    assert r.json()["url"] == "https://minio.local/k"
    assert r.json()["expiresIn"] == 300


def test_get_url_cross_tenant_is_404_not_403(app: FastAPI, client: TestClient) -> None:
    # Auth, aber kein Lesezugriff auf den Antrag → 404 (kein Existenz-Orakel), nicht 403.
    _as(app)  # keine Permissions
    r = client.get(f"/api/attachments/{ATT_ID}")
    assert r.status_code == 404


# --------------------------------------------------------------------------- wiring
def test_get_files_service_builds_from_app_state() -> None:
    """Factory verdrahtet Storage + Scan-Queue aus dem App-State (kein Pool → None)."""

    class _State:
        object_storage = None
        arq_pool = None

    class _App:
        state = _State()

    class _Req:
        app = _App()

    svc = get_files_service(object(), _Req(), load_settings())  # type: ignore[arg-type]
    assert isinstance(svc, FilesService)
    assert svc.storage is None
    assert svc.queue is None


# --------------------------------------------------------------------------- contract
def test_endpoints_declare_problem_responses(app: FastAPI) -> None:
    spec = app.openapi()
    upload = spec["paths"]["/api/applications/{application_id}/attachments"]["post"][
        "responses"
    ]
    for code in ("401", "403", "404", "413", "415", "503"):
        assert code in upload, f"upload missing {code}"
        assert list(upload[code]["content"]) == ["application/problem+json"]
    get = spec["paths"]["/api/attachments/{attachment_id}"]["get"]["responses"]
    for code in ("401", "404", "409", "410"):
        assert code in get, f"get missing {code}"


# --------------------------------------------------------------------------- delete
def test_delete_requires_auth_401(client: TestClient) -> None:
    r = client.delete(f"/api/attachments/{ATT_ID}")
    assert r.status_code == 401


def test_delete_forbidden_without_manage_404(app: FastAPI, client: TestClient) -> None:
    # Principal ohne application.manage und kein Ersteller (No-Creator-Stub) → 404.
    _as(app)
    r = client.delete(f"/api/attachments/{ATT_ID}")
    assert r.status_code == 404


def test_delete_ok_with_manage(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    _as(app, "application.manage")
    r = client.delete(f"/api/attachments/{ATT_ID}")
    assert r.status_code == 204
    assert fake_service.deleted == ATT_ID
