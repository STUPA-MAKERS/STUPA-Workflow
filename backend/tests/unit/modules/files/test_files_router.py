"""Router tests for files (T-13): endpoint wiring and RBAC with a faked service."""

from __future__ import annotations

from collections.abc import AsyncIterator
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

    async def signed_url(
        self, attachment_id: UUID, *, allow_unconfirmed: bool = True
    ) -> SignedUrlOut:
        return SignedUrlOut(url=f"/api/attachments/{attachment_id}/download", expiresIn=300)

    async def download_bytes(
        self, attachment_id: UUID, *, allow_unconfirmed: bool = True
    ) -> tuple[bytes, str, str]:
        return b"PDF-BYTES", "doc.pdf", "application/pdf"

    async def download_stream(
        self, attachment_id: UUID, *, allow_unconfirmed: bool = True
    ) -> tuple[AsyncIterator[bytes], str, str, int]:
        async def _iter() -> AsyncIterator[bytes]:
            yield b"PDF-"
            yield b"BYTES"

        return _iter(), "doc.pdf", "application/pdf", len(b"PDF-BYTES")

    async def delete(self, attachment_id: UUID, *, actor: str) -> None:
        self.deleted = attachment_id

    async def list_for_application(
        self, application_id: UUID, *, allow_unconfirmed: bool = True
    ) -> list[AttachmentOut]:
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


class _EmptyResult:
    """Stub a SQLAlchemy result: `all` returns an empty list, so no Gremium memberships."""

    def all(self) -> list[object]:  # noqa: A003
        return []


class _NoCreatorDb:
    """Stub a session for the creator check (#24).

    `scalar` returns None, so there is no created_by. `execute` returns an empty
    result, so the Gremium read path gives False.
    """

    async def scalar(self, *_a: object, **_k: object) -> None:
        return None

    async def execute(self, *_a: object, **_k: object) -> _EmptyResult:
        return _EmptyResult()


async def _fake_session():  # noqa: ANN202
    yield _NoCreatorDb()


@pytest.fixture
def app(fake_service: _FakeService) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_files_service] = lambda: fake_service
    # require_app_edit and require_app_read read created_by, so the stub has no creator.
    application.dependency_overrides[get_session] = _fake_session
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _as(app: FastAPI, *perms: str) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="p", permissions=set(perms)
    )


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
    fake_service.max_bytes = 8  # the router caps the read, so 413 comes before the service
    r = client.post(
        f"/api/applications/{APP_ID}/attachments",
        files={"file": ("doc.pdf", b"x" * 64, "application/pdf")},
    )
    assert r.status_code == 413


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
    # App-relative stream path instead of a presigned MinIO URL (#attachment-links).
    assert r.json()["url"] == f"/api/attachments/{ATT_ID}/download"
    assert r.json()["expiresIn"] == 300


def test_get_url_cross_tenant_is_404_not_403(app: FastAPI, client: TestClient) -> None:
    # Authenticated but without read access to the application: 404, not 403.
    # A 403 would work as an existence oracle.
    _as(app)  # no permissions
    r = client.get(f"/api/attachments/{ATT_ID}")
    assert r.status_code == 404


def test_download_requires_auth_401(client: TestClient) -> None:
    assert client.get(f"/api/attachments/{ATT_ID}/download").status_code == 401


def test_download_streams_bytes_with_disposition(app: FastAPI, client: TestClient) -> None:
    _as(app, "application.read")
    r = client.get(f"/api/attachments/{ATT_ID}/download")
    assert r.status_code == 200
    assert r.content == b"PDF-BYTES"
    assert r.headers["content-type"] == "application/pdf"
    assert 'attachment; filename="doc.pdf"' in r.headers["content-disposition"]


def test_download_inline_renders_in_browser(app: FastAPI, client: TestClient) -> None:
    # ?inline=1 gives Content-Disposition inline for the preview dialog. It applies
    # only to the non-scriptable allowlist (PDF, PNG, JPEG = the upload allowlist).
    _as(app, "application.read")
    r = client.get(f"/api/attachments/{ATT_ID}/download?inline=1")
    assert r.status_code == 200
    assert 'inline; filename="doc.pdf"' in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_download_cross_tenant_is_404(app: FastAPI, client: TestClient) -> None:
    _as(app)  # no permissions, so no read access and 404 (no existence oracle)
    r = client.get(f"/api/attachments/{ATT_ID}/download")
    assert r.status_code == 404


def test_get_files_service_builds_from_app_state() -> None:
    """The factory wires storage and scan queue from the app state, None without a pool."""

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


def test_delete_requires_auth_401(client: TestClient) -> None:
    r = client.delete(f"/api/attachments/{ATT_ID}")
    assert r.status_code == 401


def test_delete_forbidden_without_manage_404(app: FastAPI, client: TestClient) -> None:
    # A principal without application.manage and without creator rights gets 404.
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


def test_delete_ok_with_edit_any(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    # application.edit_any is a global write permission. Like the upload path
    # (require_app_edit), it must also allow delete and must not give 404 (#AUD-040).
    # With the no-creator stub and no application.manage, only edit_any can pass.
    _as(app, "application.edit_any")
    r = client.delete(f"/api/attachments/{ATT_ID}")
    assert r.status_code == 204
    assert fake_service.deleted == ATT_ID


# Attachment read covers the same paths as require_app_read, not only the global
# application.read: read_all, the creator and Gremium read.
def test_get_url_read_all_ok(app: FastAPI, client: TestClient) -> None:
    # application.read_all grants access without application.read (read_all branch).
    _as(app, "application.read_all")
    r = client.get(f"/api/attachments/{ATT_ID}")
    assert r.status_code == 200
    assert r.json()["url"] == f"/api/attachments/{ATT_ID}/download"


def test_download_read_all_ok(app: FastAPI, client: TestClient) -> None:
    _as(app, "application.read_all")
    r = client.get(f"/api/attachments/{ATT_ID}/download")
    assert r.status_code == 200
    assert r.content == b"PDF-BYTES"


def _patch_creator(monkeypatch: pytest.MonkeyPatch, *, is_creator: bool) -> None:
    # _resolve_with_creator in the access module calls _is_creator. Patch it to
    # switch the creator branch without a real database.
    import app.modules.applications.access as access_mod

    async def _fake_is_creator(*_a: object, **_k: object) -> bool:
        return is_creator

    monkeypatch.setattr(access_mod, "_is_creator", _fake_is_creator)


def _patch_committee(monkeypatch: pytest.MonkeyPatch, *, can_read: bool) -> None:
    import app.modules.files.router as router_mod

    async def _fake_committee(*_a: object, **_k: object) -> bool:
        return can_read

    monkeypatch.setattr(router_mod, "_committee_can_read", _fake_committee)


def test_get_url_creator_fallback_ok(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No application.read, but the logged-in creator (#24) gets 200 by the creator branch.
    _as(app)
    _patch_creator(monkeypatch, is_creator=True)
    r = client.get(f"/api/attachments/{ATT_ID}")
    assert r.status_code == 200


def test_get_url_committee_read_fallback_ok(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No permission and no creator, but Gremium read (#committee-read) gives 200.
    _as(app)
    _patch_creator(monkeypatch, is_creator=False)
    _patch_committee(monkeypatch, can_read=True)
    r = client.get(f"/api/attachments/{ATT_ID}")
    assert r.status_code == 200


def test_download_committee_read_fallback_ok(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _as(app)
    _patch_creator(monkeypatch, is_creator=False)
    _patch_committee(monkeypatch, can_read=True)
    r = client.get(f"/api/attachments/{ATT_ID}/download")
    assert r.status_code == 200
    assert r.content == b"PDF-BYTES"


def test_get_url_no_access_paths_is_404(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No permission, no creator and no Gremium read, so 404 (no existence oracle).
    _as(app)
    _patch_creator(monkeypatch, is_creator=False)
    _patch_committee(monkeypatch, can_read=False)
    r = client.get(f"/api/attachments/{ATT_ID}")
    assert r.status_code == 404
