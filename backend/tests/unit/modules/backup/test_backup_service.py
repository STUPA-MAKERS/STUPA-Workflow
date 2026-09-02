"""Unit tests for `BackupService`: catalogue, retention, keys and the archive build.

The tests use a fake object storage and a fake session, so no MinIO and no database
are needed. `build_archive` runs for real against those fakes, with `pg_dump` stubbed
out, because the interesting part is the staging, the tar and the encryption, not the
subprocess.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from pyrage import x25519  # pyright: ignore[reportAttributeAccessIssue]

from app.modules.backup import archive as arch
from app.modules.backup.models import Backup
from app.modules.backup.service import (
    BackupError,
    BackupService,
    archive_key,
    download_name,
    libpq_dsn,
    stream_upload,
    temp_file,
)
from app.modules.files.storage import StorageError
from app.settings import Settings, load_settings

CREATED_AT = datetime(2026, 9, 1, 22, 5, 0, tzinfo=UTC)


class _FakeStorage:
    """In-memory object storage covering the parts the backup service uses."""

    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects: dict[str, bytes] = dict(objects or {})
        self.removed: list[str] = []
        self.presigned: list[tuple[str, int, str | None]] = []
        self.fail_on_get: set[str] = set()

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = data

    async def get(self, key: str) -> bytes:
        return self.objects[key]

    async def get_stream(self, key: str, *, chunk_size: int = 1024):  # noqa: ANN202
        payload = self.objects[key]

        async def _chunks():  # noqa: ANN202
            for i in range(0, len(payload), chunk_size):
                yield payload[i : i + chunk_size]

        return _chunks()

    async def remove(self, key: str) -> None:
        if key not in self.objects:
            raise StorageError("gone")
        self.removed.append(key)
        del self.objects[key]

    async def list_keys(self) -> list[str]:
        return sorted(self.objects)

    async def put_file(self, key: str, path: str, content_type: str) -> None:
        self.objects[key] = Path(path).read_bytes()

    async def get_file(self, key: str, path: str) -> None:
        if key in self.fail_on_get:
            raise StorageError("vanished")
        Path(path).write_bytes(self.objects[key])

    def presigned_get_url(
        self, key: str, *, expires_seconds: int, download_name: str | None = None
    ) -> str:
        self.presigned.append((key, expires_seconds, download_name))
        return f"https://minio.invalid/{key}?signed"


class _FakeSession:
    """Session double: records added rows and deletions, no database."""

    def __init__(self, rows: list[Backup] | None = None) -> None:
        self.rows = rows or []
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.flushed = 0
        self.scalar_value: object = "f3b3f1a022b5"

    def add(self, row: object) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        self.flushed += 1

    async def delete(self, row: object) -> None:
        self.deleted.append(row)

    async def get(self, _model: object, ident: UUID) -> Backup | None:
        return next((r for r in self.rows if r.id == ident), None)

    async def scalars(self, _stmt: object) -> Any:
        return _Scalars(self.rows)

    async def scalar(self, _stmt: object) -> object:
        if isinstance(self.scalar_value, Exception):
            raise self.scalar_value
        return self.scalar_value


class _Scalars:
    def __init__(self, rows: list[Backup]) -> None:
        self._rows = rows

    def all(self) -> list[Backup]:
        return self._rows


def _settings(**overrides: object) -> Settings:
    base = load_settings()
    return base.model_copy(update=overrides)


def _row(**kw: object) -> Backup:
    """Build a catalogue row as it looks AFTER the insert flush.

    `id` and `created_at` are server defaults, so a row the service ever sees already
    carries both. The helper fills them in, because the plain constructor does not.
    """
    row = Backup(**kw)  # type: ignore[arg-type]
    row.id = uuid4()
    if row.created_at is None:  # type: ignore[comparison-overlap]
        row.created_at = CREATED_AT
    return row


def _service(
    *,
    session: _FakeSession | None = None,
    attachments: _FakeStorage | None = None,
    archives: _FakeStorage | None = None,
    **settings_overrides: object,
) -> BackupService:
    return BackupService(
        session or _FakeSession(),  # type: ignore[arg-type]
        _settings(**settings_overrides),
        attachments=attachments,  # type: ignore[arg-type]
        archives=archives,  # type: ignore[arg-type]
    )


# ------------------------------------------------------------------------- helpers


def test_libpq_dsn_strips_the_asyncpg_driver_prefix() -> None:
    """`pg_dump` cannot read the SQLAlchemy driver prefix."""
    assert libpq_dsn("postgresql+asyncpg://u:p@host:5432/db") == "postgresql://u:p@host:5432/db"


def test_libpq_dsn_leaves_a_plain_url_alone() -> None:
    assert libpq_dsn("postgresql://u@h/db") == "postgresql://u@h/db"


def test_archive_key_is_time_sortable_and_unique() -> None:
    backup_id = uuid4()
    key = archive_key(backup_id, CREATED_AT)
    assert key == f"antrag-20260901T220500Z-{backup_id}.tar.age"


def test_download_name_carries_the_timestamp() -> None:
    assert download_name(CREATED_AT) == "antrag-20260901T220500Z.tar.age"


def test_temp_file_removes_the_file_on_the_way_out() -> None:
    with temp_file(".probe") as handle:
        path = Path(handle.name)
        handle.write(b"x")
        assert path.exists()
    assert not path.exists()


# ----------------------------------------------------------------------- catalogue


@pytest.mark.asyncio
async def test_create_row_starts_pending_and_stamps_the_app_version() -> None:
    session = _FakeSession()
    service = _service(session=session, app_version="9.9.9")
    row = await service.create_row(kind="manual", actor="sub-1", note="before the vote")
    assert (row.status, row.kind, row.created_by, row.note) == (
        "pending",
        "manual",
        "sub-1",
        "before the vote",
    )
    assert row.app_version == "9.9.9"
    assert session.added == [row]


@pytest.mark.asyncio
async def test_mark_done_records_the_archive_and_clears_a_previous_error() -> None:
    from app.modules.backup.service import ArchiveResult

    service = _service()
    row = _row(status="running", error="an earlier failure")
    await service.mark_done(
        row,
        ArchiveResult(
            storage_key="k",
            size_bytes=42,
            checksum="abc",
            object_count=3,
            schema_revision="rev",
        ),
    )
    assert (row.status, row.storage_key, row.size_bytes, row.error) == (
        "done",
        "k",
        42,
        None,
    )
    assert row.finished_at is not None


@pytest.mark.asyncio
async def test_mark_failed_truncates_the_code_and_never_carries_a_path() -> None:
    service = _service()
    row = _row(status="running")
    await service.mark_failed(row, "x" * 500)
    assert row.status == "failed"
    assert row.error is not None
    assert len(row.error) == 200


@pytest.mark.asyncio
async def test_export_streams_the_bytes_rather_than_presigning_a_url() -> None:
    """Regression: MinIO is internal, so a presigned URL is unreachable from a browser.

    The export therefore reads the object and streams it; nothing hands the client a
    URL that points at the object store.
    """
    archives = _FakeStorage({"key": b"cipher-bytes"})
    service = _service(archives=archives)
    chunks = [c async for c in await service.export_stream(_row(storage_key="key"))]
    assert b"".join(chunks) == b"cipher-bytes"
    assert archives.presigned == [], "the export must not presign anything"


@pytest.mark.asyncio
async def test_export_refuses_a_row_without_an_archive() -> None:
    service = _service(archives=_FakeStorage())
    with pytest.raises(BackupError, match="no stored archive"):
        await service.export_stream(_row(storage_key=None))


# ----------------------------------------------------------------------- retention


@pytest.mark.asyncio
async def test_prune_keeps_the_newest_and_deletes_the_rest() -> None:
    rows = [_row(status="done", kind="manual", storage_key=f"k{i}") for i in range(5)]
    archives = _FakeStorage({f"k{i}": b"x" for i in range(5)})
    session = _FakeSession(rows)
    service = _service(session=session, archives=archives, backup_retention_count=2)
    doomed = await service.prune()
    assert doomed == rows[2:]
    assert session.deleted == rows[2:]
    assert archives.removed == ["k2", "k3", "k4"]


@pytest.mark.asyncio
async def test_prune_is_off_when_the_retention_count_is_zero() -> None:
    session = _FakeSession([_row(status="done") for _ in range(3)])
    service = _service(session=session, backup_retention_count=0)
    assert await service.prune() == []
    assert session.deleted == []


@pytest.mark.asyncio
async def test_delete_removes_the_object_before_the_row() -> None:
    """A row without its object would show as restorable and lie."""
    archives = _FakeStorage({"k": b"x"})
    session = _FakeSession()
    service = _service(session=session, archives=archives)
    row = _row(storage_key="k")
    await service.delete(row)
    assert archives.removed == ["k"]
    assert session.deleted == [row]


@pytest.mark.asyncio
async def test_delete_survives_an_object_that_is_already_gone() -> None:
    session = _FakeSession()
    service = _service(session=session, archives=_FakeStorage())
    row = _row(storage_key="missing")
    await service.delete(row)
    assert session.deleted == [row]


# --------------------------------------------------------------------------- build


@pytest.mark.asyncio
async def test_build_archive_packs_the_dump_and_every_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = x25519.Identity.generate()
    attachments = _FakeStorage({"a.pdf": b"one", "deep/b.png": b"two"})
    archives = _FakeStorage()
    service = _service(
        attachments=attachments,
        archives=archives,
        backup_age_recipient=str(identity.to_public()),
        minio_endpoint="minio:9000",
    )

    async def _fake_dump(path: str) -> None:
        Path(path).write_bytes(b"PGDUMP")

    monkeypatch.setattr(service, "_pg_dump", _fake_dump)

    row = _row()
    result = await service.build_archive(row)

    assert result.object_count == 2
    assert result.schema_revision == "f3b3f1a022b5"
    assert result.storage_key == archive_key(row.id, CREATED_AT)
    stored = archives.objects[result.storage_key]
    assert result.size_bytes == len(stored)

    plain = io.BytesIO()
    arch.decrypt_stream(io.BytesIO(stored), plain, identity)
    with arch.open_tar(plain) as tar:
        assert dict(arch.iter_objects(tar)) == {"a.pdf": b"one", "deep/b.png": b"two"}
        dump = io.BytesIO()
        arch.extract_dump(tar, dump)
    assert dump.getvalue() == b"PGDUMP"


@pytest.mark.asyncio
async def test_build_archive_skips_an_attachment_that_vanishes_mid_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An upload deleted while the backup runs must not fail the whole backup."""
    identity = x25519.Identity.generate()
    attachments = _FakeStorage({"gone.pdf": b"x", "kept.pdf": b"y"})
    attachments.fail_on_get.add("gone.pdf")
    service = _service(
        attachments=attachments,
        archives=_FakeStorage(),
        backup_age_recipient=str(identity.to_public()),
        minio_endpoint="minio:9000",
    )

    async def _fake_dump(path: str) -> None:
        Path(path).write_bytes(b"D")

    monkeypatch.setattr(service, "_pg_dump", _fake_dump)
    result = await service.build_archive(_row())
    assert result.object_count == 1


@pytest.mark.asyncio
async def test_build_archive_refuses_without_storage() -> None:
    service = _service(backup_age_recipient="age1whatever")
    with pytest.raises(BackupError, match="object storage is not configured"):
        await service.build_archive(_row())


@pytest.mark.asyncio
async def test_build_archive_refuses_without_a_recipient() -> None:
    service = _service(
        attachments=_FakeStorage(), archives=_FakeStorage(), backup_age_recipient=None
    )
    with pytest.raises(BackupError, match="no age recipient"):
        await service.build_archive(_row())


@pytest.mark.asyncio
async def test_schema_revision_is_none_when_alembic_version_is_unreadable() -> None:
    session = _FakeSession()
    session.scalar_value = RuntimeError("no such table")
    service = _service(session=session)
    assert await service._schema_revision() is None  # noqa: SLF001


# ------------------------------------------------------------------------- restore


@pytest.mark.asyncio
async def test_verify_archive_reads_the_manifest_of_a_real_archive(
    tmp_path: Path,
) -> None:
    identity = x25519.Identity.generate()
    key_file = tmp_path / "age.key"
    key_file.write_text(str(identity))
    service = _service(
        backup_age_identity_file=str(key_file),
        backup_age_recipient=str(identity.to_public()),
    )

    tar_bytes = io.BytesIO()
    arch.write_tar(
        tar_bytes,
        io.BytesIO(b"D"),
        [],
        arch.ArchiveManifest(app_version="7.7.7", object_count=0),
    )
    encrypted = io.BytesIO()
    arch.encrypt_stream(tar_bytes, encrypted, identity.to_public())
    archive_path = tmp_path / "a.tar.age"
    archive_path.write_bytes(encrypted.getvalue())

    manifest = service.verify_archive(str(archive_path))
    assert manifest.app_version == "7.7.7"


@pytest.mark.asyncio
async def test_verify_archive_rejects_a_file_that_is_not_an_archive(
    tmp_path: Path,
) -> None:
    identity = x25519.Identity.generate()
    key_file = tmp_path / "age.key"
    key_file.write_text(str(identity))
    junk = tmp_path / "junk"
    junk.write_bytes(b"not an age file")
    service = _service(backup_age_identity_file=str(key_file))
    with pytest.raises(arch.ArchiveError, match="does not decrypt"):
        service.verify_archive(str(junk))


def test_identity_refuses_when_none_is_configured() -> None:
    service = _service(backup_age_identity_file=None)
    with pytest.raises(BackupError, match="no restore is possible"):
        service._identity()  # noqa: SLF001


def test_identity_refuses_an_unreadable_key_file() -> None:
    service = _service(backup_age_identity_file="/nonexistent/age.key")
    with pytest.raises(BackupError, match="not readable"):
        service._identity()  # noqa: SLF001


# -------------------------------------------------------------------------- upload


@pytest.mark.asyncio
async def test_stream_upload_writes_the_whole_body_and_returns_its_size() -> None:
    async def _chunks():  # noqa: ANN202
        yield b"abc"
        yield b"de"

    target = io.BytesIO()
    assert await stream_upload(_chunks(), target, cap=100) == 5
    assert target.getvalue() == b"abcde"


@pytest.mark.asyncio
async def test_stream_upload_stops_at_the_cap() -> None:
    async def _chunks():  # noqa: ANN202
        yield b"x" * 10
        yield b"x" * 10

    with pytest.raises(BackupError, match="larger than the configured cap"):
        await stream_upload(_chunks(), io.BytesIO(), cap=15)
