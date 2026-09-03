"""Router tests for /admin/backups: RBAC, the 503 gates, and the restore confirmation.

The tests replace the service with a fake, so no MinIO, no database and no age key are
involved. What matters here is the wiring: who may call what, which routes refuse when
the feature is not configured, and that a restore cannot fire without the confirmation.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_session
from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.backup.models import Backup
from app.modules.backup.router import get_backup_service
from app.modules.backup.service import BackupError
from app.settings import Settings, load_settings

BACKUP_ID = uuid4()
MISSING_ID = UUID("00000000-0000-0000-0000-000000000000")
CREATED_AT = datetime(2026, 9, 1, 22, 5, 0, tzinfo=UTC)


class _FakeSession:
    async def commit(self) -> None: ...
    async def flush(self) -> None: ...
    def add(self, _row: object) -> None: ...

    async def scalar(self, *_a: object, **_k: object) -> None:
        return None

    async def execute(self, *_a: object, **_k: object) -> object:
        return _Empty()


class _Empty:
    def scalars(self) -> _Empty:
        return self

    def all(self) -> list[object]:
        return []

    def scalar_one_or_none(self) -> None:
        return None

    def first(self) -> None:
        return None


def _row(**kw: object) -> Backup:
    """Build a catalogue row as it looks after the insert.

    The model defaults for `kind`, `status` and `pinned` apply at FLUSH, not at
    construction, and `id`/`created_at` come from the database. A double never flushes
    for real, so the helper fills all of them in.
    """
    defaults: dict[str, object] = {"kind": "manual", "status": "pending", "pinned": False}
    row = Backup(**{**defaults, **kw})  # type: ignore[arg-type]
    row.id = BACKUP_ID
    if row.created_at is None:  # type: ignore[comparison-overlap]
        row.created_at = CREATED_AT
    return row


class _FakeService:
    """Stands in for BackupService. Records what the routes asked it to do."""

    def __init__(self, settings: Settings, row: Backup | None = None) -> None:
        self.settings = settings
        self.row = row if row is not None else _row(status="done", storage_key="k")
        self.archives = object()
        self.created: list[tuple[str, str | None, str | None]] = []
        self.deleted: list[UUID] = []
        self.export_calls = 0

    async def list(self, *, limit: int = 100, offset: int = 0) -> list[Backup]:
        return [self.row]

    async def get(self, backup_id: UUID) -> Backup | None:
        return None if backup_id == MISSING_ID else self.row

    async def create_row(self, *, kind: str, actor: str | None, note: str | None = None) -> Backup:
        self.created.append((kind, actor, note))
        return _row(status="pending", kind=kind, created_by=actor, note=note)

    async def export_stream(self, row: Backup):  # noqa: ANN202 — AsyncIterator[bytes]
        self.export_calls += 1
        if not row.storage_key:
            raise BackupError("this backup has no stored archive")

        async def _chunks():  # noqa: ANN202
            yield b"cipher"

        return _chunks()

    async def delete(self, row: Backup) -> None:
        self.deleted.append(row.id)


def _settings(**overrides: object) -> Settings:
    base = load_settings()
    return base.model_copy(
        update={
            "minio_endpoint": "minio:9000",
            "backup_age_recipient": "age1recipient",
            "backup_age_identity_file": "/secrets/age.key",
            **overrides,
        }
    )


@pytest.fixture
def service() -> _FakeService:
    return _FakeService(_settings())


@pytest.fixture
def app(service: _FakeService) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_backup_service] = lambda: service

    def _session() -> Iterator[_FakeSession]:
        yield _FakeSession()

    application.dependency_overrides[get_session] = _session
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _principal(app: FastAPI, *perms: str) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="admin-sub", permissions=set(perms)
    )


# ---------------------------------------------------------------------------- RBAC


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/admin/backups"),
        ("get", f"/api/admin/backups/{BACKUP_ID}"),
        ("post", "/api/admin/backups"),
        ("get", f"/api/admin/backups/{BACKUP_ID}/export"),
        ("post", f"/api/admin/backups/{BACKUP_ID}/restore"),
        ("delete", f"/api/admin/backups/{BACKUP_ID}"),
    ],
)
def test_every_route_requires_authentication(client: TestClient, method: str, path: str) -> None:
    # `request` rather than `client.get`/`client.delete`, because only it carries a
    # body on every verb, and the POST routes need one to get past validation.
    assert client.request(method.upper(), path, json={}).status_code == 401


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/admin/backups"),
        ("post", "/api/admin/backups"),
        ("get", f"/api/admin/backups/{BACKUP_ID}/export"),
        ("delete", f"/api/admin/backups/{BACKUP_ID}"),
    ],
)
def test_another_admin_permission_is_not_enough(
    app: FastAPI, client: TestClient, method: str, path: str
) -> None:
    """`backup.manage` is deliberately separate from every admin.* page permission."""
    _principal(app, "admin.site", "privacy.manage")
    assert client.request(method.upper(), path, json={}).status_code == 403


# ---------------------------------------------------------------------------- list


def test_list_returns_the_catalogue_and_the_capability_flags(
    app: FastAPI, client: TestClient
) -> None:
    _principal(app, "backup.manage")
    body = client.get("/api/admin/backups").json()
    assert body["enabled"] is True
    assert body["restoreEnabled"] is True
    assert body["items"][0]["id"] == str(BACKUP_ID)
    assert body["items"][0]["status"] == "done"


def test_list_reports_the_feature_as_off_without_a_recipient(
    app: FastAPI, client: TestClient, service: _FakeService
) -> None:
    service.settings = _settings(backup_age_recipient=None)
    _principal(app, "backup.manage")
    body = client.get("/api/admin/backups").json()
    assert body["enabled"] is False
    assert body["restoreEnabled"] is False


def test_list_reports_restore_off_without_an_identity(
    app: FastAPI, client: TestClient, service: _FakeService
) -> None:
    """Without the private key the platform cannot read its own archives."""
    service.settings = _settings(backup_age_identity_file=None)
    _principal(app, "backup.manage")
    body = client.get("/api/admin/backups").json()
    assert body["enabled"] is True
    assert body["restoreEnabled"] is False


def test_get_returns_404_for_an_unknown_backup(app: FastAPI, client: TestClient) -> None:
    _principal(app, "backup.manage")
    assert client.get(f"/api/admin/backups/{MISSING_ID}").status_code == 404


# -------------------------------------------------------------------------- create


def test_create_answers_202_with_a_pending_row(
    app: FastAPI, client: TestClient, service: _FakeService
) -> None:
    _principal(app, "backup.manage")
    response = client.post("/api/admin/backups", json={"note": "before the vote"})
    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    assert service.created == [("manual", "admin-sub", "before the vote")]


def test_create_refuses_with_503_when_the_feature_is_off(
    app: FastAPI, client: TestClient, service: _FakeService
) -> None:
    service.settings = _settings(backup_age_recipient=None)
    _principal(app, "backup.manage")
    assert client.post("/api/admin/backups", json={}).status_code == 503


def test_create_rejects_an_over_long_note(app: FastAPI, client: TestClient) -> None:
    _principal(app, "backup.manage")
    response = client.post("/api/admin/backups", json={"note": "x" * 501})
    assert response.status_code == 422


# -------------------------------------------------------------------------- export


def test_export_streams_the_archive_through_the_api(
    app: FastAPI, client: TestClient
) -> None:
    """Regression: the download must NOT be a presigned MinIO URL.

    MinIO sits on the internal Docker network, so a presigned S3 URL binds a host the
    browser cannot resolve. The bytes therefore come through this route.
    """
    _principal(app, "backup.manage")
    response = client.get(f"/api/admin/backups/{BACKUP_ID}/export")
    assert response.status_code == 200
    assert response.content == b"cipher"
    assert "attachment; filename=" in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"
    # Nothing in the response may point a client at the object store.
    assert "minio" not in response.text.lower()


def test_export_refuses_a_backup_that_is_not_finished(
    app: FastAPI, client: TestClient, service: _FakeService
) -> None:
    service.row = _row(status="running")
    _principal(app, "backup.manage")
    response = client.get(f"/api/admin/backups/{BACKUP_ID}/export")
    assert response.status_code == 409
    assert response.json()["code"] == "backup_not_ready"


# ------------------------------------------------------------------------- restore


def test_restore_needs_the_literal_confirmation(app: FastAPI, client: TestClient) -> None:
    """A stray call from a REST client must not replace the whole database."""
    _principal(app, "backup.manage")
    response = client.post(
        f"/api/admin/backups/{BACKUP_ID}/restore", json={"confirm": "yes please"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "backup_confirm_required"


def test_restore_refuses_with_503_without_an_identity(
    app: FastAPI, client: TestClient, service: _FakeService
) -> None:
    service.settings = _settings(backup_age_identity_file=None)
    _principal(app, "backup.manage")
    response = client.post(f"/api/admin/backups/{BACKUP_ID}/restore", json={"confirm": "RESTORE"})
    assert response.status_code == 503


def test_restore_refuses_a_backup_that_is_not_finished(
    app: FastAPI, client: TestClient, service: _FakeService
) -> None:
    service.row = _row(status="failed")
    _principal(app, "backup.manage")
    response = client.post(f"/api/admin/backups/{BACKUP_ID}/restore", json={"confirm": "RESTORE"})
    assert response.status_code == 409
    assert response.json()["code"] == "backup_not_ready"


def test_restore_refuses_without_a_job_queue(app: FastAPI, client: TestClient) -> None:
    """Without Redis nothing would ever run the restore, so say so instead of lying."""
    _principal(app, "backup.manage")
    response = client.post(f"/api/admin/backups/{BACKUP_ID}/restore", json={"confirm": "RESTORE"})
    assert response.status_code == 503


# -------------------------------------------------------------------------- delete


def test_delete_removes_the_backup(app: FastAPI, client: TestClient, service: _FakeService) -> None:
    _principal(app, "backup.manage")
    assert client.delete(f"/api/admin/backups/{BACKUP_ID}").status_code == 204
    assert service.deleted == [BACKUP_ID]


def test_delete_refuses_a_pinned_backup(
    app: FastAPI, client: TestClient, service: _FakeService
) -> None:
    """A deliberate keep must not be undone by one stray click."""
    service.row = _row(status="done", storage_key="k", pinned=True)
    _principal(app, "backup.manage")
    response = client.delete(f"/api/admin/backups/{BACKUP_ID}")
    assert response.status_code == 409
    assert response.json()["code"] == "backup_pinned"
    assert service.deleted == []


def test_delete_returns_404_for_an_unknown_backup(app: FastAPI, client: TestClient) -> None:
    _principal(app, "backup.manage")
    assert client.delete(f"/api/admin/backups/{MISSING_ID}").status_code == 404
