"""Tests for the paths a restore takes: the bucket mirror, the subprocess wrapper, and
the import route.

These are the parts that only ran live before. The mirror decides what survives a
restore, the subprocess wrapper decides how a missing `pg_dump` is reported, and the
import route is the one place a file from outside enters the platform.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pyrage import x25519  # pyright: ignore[reportAttributeAccessIssue]

from app.db import get_session
from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.backup import archive as arch
from app.modules.backup.models import Backup
from app.modules.backup.router import get_backup_service
from app.modules.backup.service import BackupError, BackupService
from app.modules.files.storage import StorageError
from app.settings import Settings, load_settings

CREATED_AT = datetime(2026, 9, 1, 22, 5, 0, tzinfo=UTC)


class _FakeStorage:
    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects: dict[str, bytes] = dict(objects or {})
        self.removed: list[str] = []
        self.undeletable: set[str] = set()

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = data

    async def get(self, key: str) -> bytes:
        return self.objects[key]

    async def remove(self, key: str) -> None:
        if key in self.undeletable:
            raise StorageError("locked")
        self.removed.append(key)
        self.objects.pop(key, None)

    async def list_keys(self) -> list[str]:
        return sorted(self.objects)

    async def put_file(self, key: str, path: str, content_type: str) -> None:
        self.objects[key] = Path(path).read_bytes()

    async def get_file(self, key: str, path: str) -> None:
        Path(path).write_bytes(self.objects[key])

    def presigned_get_url(self, key: str, **_kw: object) -> str:
        return f"https://minio.invalid/{key}"


def _settings(**overrides: object) -> Settings:
    return load_settings().model_copy(
        update={
            "minio_endpoint": "minio:9000",
            "backup_age_recipient": "age1recipient",
            "backup_age_identity_file": "/secrets/age.key",
            **overrides,
        }
    )


def _sessionless(**settings_overrides: object) -> BackupService:
    """Build a service for the paths that never touch the session.

    The mirror and the subprocess wrapper take no session at all, so a placeholder is
    honest here: passing a real one would suggest they use it.
    """
    return BackupService(
        object(),  # type: ignore[arg-type]  # these paths never touch the session
        _settings(**settings_overrides),
    )


def _tar_bytes(objects: dict[str, bytes]) -> io.BytesIO:
    target = io.BytesIO()
    readers = [(k, io.BytesIO(v)) for k, v in objects.items()]
    arch.write_tar(target, io.BytesIO(b"DUMP"), readers, arch.ArchiveManifest())
    return target


# -------------------------------------------------------------------- bucket mirror


@pytest.mark.asyncio
async def test_mirror_writes_the_archive_objects_and_removes_the_rest() -> None:
    """A restore must leave the bucket matching the archive exactly.

    Without the removal the platform keeps attachments that the restored database has
    no row for.
    """
    attachments = _FakeStorage({"stale.pdf": b"old", "kept.pdf": b"old"})
    service = _sessionless()
    service.attachments = attachments  # type: ignore[assignment]
    with arch.open_tar(_tar_bytes({"kept.pdf": b"new", "fresh.pdf": b"new"})) as tar:
        await service._mirror_objects(tar)  # noqa: SLF001
    assert attachments.objects == {"kept.pdf": b"new", "fresh.pdf": b"new"}
    assert attachments.removed == ["stale.pdf"]


@pytest.mark.asyncio
async def test_mirror_survives_an_object_it_cannot_remove() -> None:
    """One locked object must not abort a restore that already replaced the database."""
    attachments = _FakeStorage({"stuck.pdf": b"old"})
    attachments.undeletable.add("stuck.pdf")
    service = _sessionless()
    service.attachments = attachments  # type: ignore[assignment]
    with arch.open_tar(_tar_bytes({"fresh.pdf": b"new"})) as tar:
        await service._mirror_objects(tar)  # noqa: SLF001
    assert attachments.objects["fresh.pdf"] == b"new"


@pytest.mark.asyncio
async def test_apply_archive_refuses_without_storage() -> None:
    service = _sessionless()
    with pytest.raises(BackupError, match="object storage is not configured"):
        await service.apply_archive("/nowhere.age")


# ---------------------------------------------------------------------- subprocess


@pytest.mark.asyncio
async def test_a_missing_binary_is_reported_as_a_missing_binary() -> None:
    """The image must not be able to fail silently on a missing pg_dump."""
    service = _sessionless()
    with pytest.raises(BackupError, match="is not installed in this image"):
        await service._run(  # noqa: SLF001
            ["definitely-not-a-real-binary-9f3a"], what="pg_dump"
        )


@pytest.mark.asyncio
async def test_a_non_zero_exit_fails_the_run() -> None:
    service = _sessionless()
    with pytest.raises(BackupError, match="pg_dump failed"):
        await service._run(["false"], what="pg_dump")  # noqa: SLF001


@pytest.mark.asyncio
async def test_pg_restore_tolerates_a_non_zero_exit() -> None:
    """`--clean` warns for every object the target lacks, which sets a non-zero code."""
    service = _sessionless()
    await service._run(["false"], what="pg_restore", tolerate_nonzero=True)  # noqa: SLF001


@pytest.mark.asyncio
async def test_a_run_that_overruns_its_timeout_is_killed() -> None:
    service = _sessionless(backup_subprocess_timeout_seconds=1)
    with pytest.raises(BackupError, match="timed out"):
        await service._run(["sleep", "30"], what="pg_dump")  # noqa: SLF001


# -------------------------------------------------------------------- import route


class _ImportSession:
    """Session double that stamps the server defaults, as a real flush does.

    `id` and `created_at` come from the database, and the model defaults for `pinned`
    apply at flush. `import_backup` reads all of them straight afterwards, so a double
    that leaves them None would test something the real database never does.
    """

    def __init__(self) -> None:
        self.pending: list[Backup] = []

    async def commit(self) -> None:
        await self.flush()

    async def flush(self) -> None:
        for row in self.pending:
            if row.id is None:  # type: ignore[comparison-overlap]
                row.id = uuid4()
            if row.created_at is None:  # type: ignore[comparison-overlap]
                row.created_at = CREATED_AT
            if row.pinned is None:  # type: ignore[comparison-overlap]
                row.pinned = False
        self.pending.clear()

    def add(self, row: object) -> None:
        if isinstance(row, Backup):
            self.pending.append(row)

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


def _upload_bytes(identity: x25519.Identity, app_version: str = "1.0") -> bytes:
    manifest = arch.ArchiveManifest(app_version=app_version, object_count=1)
    tar = io.BytesIO()
    arch.write_tar(tar, io.BytesIO(b"DUMP"), [("a.pdf", io.BytesIO(b"x"))], manifest)
    encrypted = io.BytesIO()
    arch.encrypt_stream(tar, encrypted, identity.to_public())
    return encrypted.getvalue()


@pytest.fixture
def identity() -> x25519.Identity:
    return x25519.Identity.generate()


@pytest.fixture
def key_file(tmp_path: Path, identity: x25519.Identity) -> Path:
    path = tmp_path / "age.key"
    path.write_text(str(identity))
    return path


@pytest.fixture
def import_service(key_file: Path, identity: x25519.Identity) -> BackupService:
    settings = _settings(
        backup_age_identity_file=str(key_file),
        backup_age_recipient=str(identity.to_public()),
        backup_max_upload_bytes=1024 * 1024,
    )
    service = BackupService(
        _ImportSession(),  # type: ignore[arg-type]
        settings,
        attachments=_FakeStorage(),  # type: ignore[arg-type]
        archives=_FakeStorage(),  # type: ignore[arg-type]
    )
    return service


@pytest.fixture
def client(import_service: BackupService) -> Iterator[TestClient]:
    app: FastAPI = create_app()
    app.dependency_overrides[get_backup_service] = lambda: import_service
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="admin-sub", permissions={"backup.manage"}
    )

    def _session() -> Iterator[_ImportSession]:
        yield _ImportSession()

    app.dependency_overrides[get_session] = _session
    yield TestClient(app)


def test_import_stores_the_upload_and_reads_its_manifest(
    client: TestClient, identity: x25519.Identity, import_service: BackupService
) -> None:
    payload = _upload_bytes(identity, app_version="4.2.0")
    response = client.post(
        "/api/admin/backups/import",
        files={"file": ("archive.tar.age", payload, "application/octet-stream")},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "done"
    assert body["kind"] == "imported"
    assert body["sizeBytes"] == len(payload)
    assert body["appVersion"] == "4.2.0"
    assert body["objectCount"] == 1
    # The archive itself reached the bucket, byte for byte.
    archives: Any = import_service.archives
    assert list(archives.objects.values()) == [payload]


def test_import_rejects_a_file_that_does_not_decrypt(client: TestClient) -> None:
    """A restore must never be the first thing to discover the file is unusable."""
    response = client.post(
        "/api/admin/backups/import",
        files={"file": ("junk.tar.age", b"not an age archive", "application/octet-stream")},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "backup_unreadable"


def test_import_rejects_an_upload_over_the_cap(
    client: TestClient, identity: x25519.Identity, import_service: BackupService
) -> None:
    import_service.settings = import_service.settings.model_copy(
        update={"backup_max_upload_bytes": 8}
    )
    response = client.post(
        "/api/admin/backups/import",
        files={"file": ("big.tar.age", _upload_bytes(identity), "application/octet-stream")},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "backup_too_large"


def test_import_refuses_without_an_age_identity(
    client: TestClient, identity: x25519.Identity, import_service: BackupService
) -> None:
    import_service.settings = import_service.settings.model_copy(
        update={"backup_age_identity_file": None}
    )
    response = client.post(
        "/api/admin/backups/import",
        files={"file": ("a.tar.age", _upload_bytes(identity), "application/octet-stream")},
    )
    assert response.status_code == 503


def test_import_requires_the_backup_permission(
    import_service: BackupService, identity: x25519.Identity
) -> None:
    app: FastAPI = create_app()
    app.dependency_overrides[get_backup_service] = lambda: import_service
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="s", permissions={"admin.site"}
    )
    response = TestClient(app).post(
        "/api/admin/backups/import",
        files={"file": ("a.tar.age", _upload_bytes(identity), "application/octet-stream")},
    )
    assert response.status_code == 403


# --------------------------------------------------------------------------- patch


def test_patch_sets_the_note_and_the_pin(client: TestClient, import_service: BackupService) -> None:
    row = Backup(kind="manual", status="done", pinned=False)
    row.id = uuid4()
    row.created_at = CREATED_AT

    async def _get(_backup_id: object) -> Backup:
        return row

    import_service.get = _get  # type: ignore[assignment]
    response = client.patch(
        f"/api/admin/backups/{row.id}", json={"note": "keep this one", "pinned": True}
    )
    assert response.status_code == 200
    assert response.json()["pinned"] is True
    assert response.json()["note"] == "keep this one"
