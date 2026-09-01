"""Unit tests for the backup worker tasks and the enqueue abstraction.

The tasks are driven with a fake service and a fake session, so nothing here dumps a
database or talks to MinIO. What the tests pin down is the control flow: what happens
on failure, that a restore always takes its safety copy first, and that a restore
never runs when the platform cannot decrypt.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.backup.models import Backup
from app.modules.backup.queue import (
    CREATE_TASK_NAME,
    RESTORE_TASK_NAME,
    ArqBackupQueue,
    backup_queue_from_pool,
)
from app.modules.backup.service import ArchiveResult, BackupError
from app.settings import Settings, load_settings
from worker import backup as task

BACKUP_ID = uuid4()
CREATED_AT = datetime(2026, 9, 1, 22, 5, 0, tzinfo=UTC)


def _row(backup_id: UUID = BACKUP_ID, **kw: object) -> Backup:
    # The model defaults apply at flush, and a double never flushes for real.
    defaults: dict[str, object] = {"kind": "manual", "status": "pending", "pinned": False}
    row = Backup(**{**defaults, **kw})  # type: ignore[arg-type]
    row.id = backup_id
    row.created_at = CREATED_AT
    return row


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.audit: list[dict[str, Any]] = []

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None: ...
    def add(self, _row: object) -> None: ...

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> None: ...


class _Sessionmaker:
    """Callable that hands out one shared fake session."""

    def __init__(self) -> None:
        self.session = _FakeSession()

    def __call__(self) -> _FakeSession:
        return self.session


class _FakeService:
    def __init__(self, row: Backup | None) -> None:
        self.row = row
        self.built: list[UUID] = []
        self.applied: list[str] = []
        self.build_error: Exception | None = None
        self.apply_error: Exception | None = None
        self.failed_with: str | None = None
        self.pruned: list[Backup] = []
        self.created: list[str] = []

    async def get(self, _backup_id: UUID) -> Backup | None:
        return self.row

    async def mark_running(self, row: Backup) -> None:
        row.status = "running"

    async def build_archive(self, row: Backup) -> ArchiveResult:
        if self.build_error is not None:
            raise self.build_error
        self.built.append(row.id)
        return ArchiveResult(
            storage_key="k", size_bytes=1, checksum="c", object_count=0, schema_revision="r"
        )

    async def mark_done(self, row: Backup, _result: ArchiveResult) -> None:
        row.status = "done"

    async def mark_failed(self, row: Backup, code: str) -> None:
        row.status = "failed"
        self.failed_with = code

    async def create_row(self, *, kind: str, actor: str | None, note: str | None) -> Backup:
        self.created.append(kind)
        return _row(uuid4(), kind=kind, created_by=actor, note=note)

    async def prune(self) -> list[Backup]:
        return self.pruned

    async def apply_archive(self, path: str) -> Any:
        if self.apply_error is not None:
            raise self.apply_error
        self.applied.append(path)
        from app.modules.backup.archive import ArchiveManifest

        return ArchiveManifest(app_version="1.0", object_count=3)


class _FakeArchives:
    def __init__(self) -> None:
        self.fetched: list[str] = []

    async def get_file(self, key: str, path: str) -> None:
        self.fetched.append(key)
        with open(path, "wb") as handle:  # noqa: PTH123 — a plain temp path from the task
            handle.write(b"cipher")


def _settings(**overrides: object) -> Settings:
    return load_settings().model_copy(
        update={
            "minio_endpoint": "minio:9000",
            "backup_age_recipient": "age1recipient",
            "backup_age_identity_file": "/secrets/age.key",
            **overrides,
        }
    )


def _ctx(
    service: _FakeService,
    *,
    settings: Settings | None = None,
    archives: object | None = None,
) -> dict[str, Any]:
    maker = _Sessionmaker()
    ctx: dict[str, Any] = {
        "backup_sessionmaker": maker,
        "backup_settings": settings or _settings(),
        "backup_archives": archives,
        "backup_attachments": object(),
    }
    ctx["_service"] = service
    return ctx


@pytest.fixture(autouse=True)
def _patch_service(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give every task the fake service that the ctx carries."""
    monkeypatch.setattr(task, "_service", lambda ctx, _session: ctx["_service"])


@pytest.fixture(autouse=True)
def _silence_audit(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record audit writes instead of touching the hash chain."""
    written: list[dict[str, Any]] = []

    async def _record(_session: object, **kwargs: Any) -> None:
        written.append(kwargs)

    monkeypatch.setattr(task, "audit_record", _record)
    return written


# -------------------------------------------------------------------- create_backup


@pytest.mark.asyncio
async def test_create_backup_builds_the_archive_and_audits_it(
    _silence_audit: list[dict[str, Any]],
) -> None:
    row = _row()
    service = _FakeService(row)
    assert await task.create_backup(_ctx(service), str(BACKUP_ID)) == "done"
    assert service.built == [BACKUP_ID]
    assert row.status == "done"
    actions = [str(entry["action"]) for entry in _silence_audit]
    assert "backup_create" in actions


@pytest.mark.asyncio
async def test_create_backup_skips_a_row_that_is_gone() -> None:
    assert await task.create_backup(_ctx(_FakeService(None)), str(BACKUP_ID)) == "gone"


@pytest.mark.asyncio
async def test_create_backup_is_idempotent_for_a_finished_row() -> None:
    """A requeue must not build a second archive for the same row."""
    service = _FakeService(_row(status="done"))
    assert await task.create_backup(_ctx(service), str(BACKUP_ID)) == "done"
    assert service.built == []


@pytest.mark.asyncio
async def test_create_backup_marks_the_row_failed_and_does_not_retry() -> None:
    row = _row()
    service = _FakeService(row)
    service.build_error = BackupError("pg_dump failed")
    assert await task.create_backup(_ctx(service), str(BACKUP_ID)) == "failed"
    assert row.status == "failed"
    assert service.failed_with == "pg_dump failed"


# ------------------------------------------------------------------------ retention


@pytest.mark.asyncio
async def test_retention_audits_what_it_removed(
    _silence_audit: list[dict[str, Any]],
) -> None:
    service = _FakeService(_row())
    service.pruned = [_row(uuid4()), _row(uuid4())]
    assert await task.run_retention(_ctx(service)) == 2
    assert [str(e["action"]) for e in _silence_audit] == ["backup_delete"]


@pytest.mark.asyncio
async def test_retention_writes_nothing_when_it_removed_nothing(
    _silence_audit: list[dict[str, Any]],
) -> None:
    assert await task.run_retention(_ctx(_FakeService(_row()))) == 0
    assert _silence_audit == []


@pytest.mark.asyncio
async def test_retention_failure_never_fails_the_backup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeService(_row())

    async def _boom() -> list[Backup]:
        raise RuntimeError("database gone")

    monkeypatch.setattr(service, "prune", _boom)
    assert await task.run_retention(_ctx(service)) == 0


# ----------------------------------------------------------------- scheduled_backup


@pytest.mark.asyncio
async def test_scheduled_backup_does_nothing_when_backups_are_off() -> None:
    """A stack without an age recipient must not log a failure every night."""
    ctx = _ctx(_FakeService(_row()), settings=_settings(backup_age_recipient=None))
    assert await task.scheduled_backup(ctx) == "disabled"


@pytest.mark.asyncio
async def test_scheduled_backup_creates_a_scheduled_row() -> None:
    service = _FakeService(_row())
    assert await task.scheduled_backup(_ctx(service)) == "done"
    assert service.created == ["scheduled"]


# ------------------------------------------------------------------- restore_backup


@pytest.mark.asyncio
async def test_restore_takes_a_safety_backup_before_it_replaces_anything(
    _silence_audit: list[dict[str, Any]],
) -> None:
    service = _FakeService(_row(status="done", storage_key="k"))
    archives = _FakeArchives()
    assert await task.restore_backup(_ctx(service, archives=archives), str(BACKUP_ID), "sub")
    assert service.created == ["pre_restore"]
    assert archives.fetched == ["k"]
    assert service.applied  # the archive was actually applied
    actions = [str(e["action"]) for e in _silence_audit]
    assert actions[-1] == "backup_restore"


@pytest.mark.asyncio
async def test_restore_records_the_safety_backup_id_in_the_audit_entry(
    _silence_audit: list[dict[str, Any]],
) -> None:
    """The safety copy is the only record of the state before the restore."""
    service = _FakeService(_row(status="done", storage_key="k"))
    await task.restore_backup(_ctx(service, archives=_FakeArchives()), str(BACKUP_ID), "s")
    entry = next(e for e in _silence_audit if str(e["action"]) == "backup_restore")
    assert entry["data"]["safetyBackupId"]
    assert entry["data"]["objectCount"] == 3


@pytest.mark.asyncio
async def test_restore_refuses_without_an_age_identity() -> None:
    """Without the private key the platform cannot read the archive at all."""
    ctx = _ctx(
        _FakeService(_row(status="done", storage_key="k")),
        settings=_settings(backup_age_identity_file=None),
    )
    assert await task.restore_backup(ctx, str(BACKUP_ID), "sub") == "failed"


@pytest.mark.asyncio
async def test_restore_aborts_when_the_safety_backup_fails() -> None:
    """No undo means no restore. The platform stays as it is."""
    service = _FakeService(_row(status="done", storage_key="k"))
    service.build_error = BackupError("no disk space")
    assert await task.restore_backup(_ctx(service), str(BACKUP_ID), "sub") == "failed"
    assert service.applied == []


@pytest.mark.asyncio
async def test_restore_reports_failed_when_the_archive_does_not_apply() -> None:
    service = _FakeService(_row(status="done", storage_key="k"))
    service.apply_error = BackupError("pg_restore failed")
    ctx = _ctx(service, archives=_FakeArchives())
    assert await task.restore_backup(ctx, str(BACKUP_ID), "sub") == "failed"


# ---------------------------------------------------------------------------- queue


class _FakePool:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
        self.result: object = object()

    async def enqueue_job(self, name: str, *args: object, **kw: object) -> object:
        self.jobs.append((name, args, kw))
        return self.result


@pytest.mark.asyncio
async def test_create_enqueue_uses_an_idempotent_job_id() -> None:
    """A double click must coalesce into one archive."""
    pool = _FakePool()
    await ArqBackupQueue(pool).enqueue_create(BACKUP_ID)
    name, args, kw = pool.jobs[0]
    assert name == CREATE_TASK_NAME
    assert args == (str(BACKUP_ID),)
    assert kw["_job_id"] == f"backup:{BACKUP_ID}"


@pytest.mark.asyncio
async def test_create_enqueue_tolerates_a_deduped_job() -> None:
    pool = _FakePool()
    pool.result = None
    await ArqBackupQueue(pool).enqueue_create(BACKUP_ID)  # must not raise


@pytest.mark.asyncio
async def test_restore_enqueue_carries_the_actor_and_no_job_id() -> None:
    pool = _FakePool()
    await ArqBackupQueue(pool).enqueue_restore(BACKUP_ID, "sub-1")
    name, args, kw = pool.jobs[0]
    assert name == RESTORE_TASK_NAME
    assert args == (str(BACKUP_ID), "sub-1")
    assert "_job_id" not in kw


def test_queue_is_none_without_a_pool() -> None:
    """Without Redis the API leaves the row pending instead of blocking."""
    assert backup_queue_from_pool(None) is None
    assert backup_queue_from_pool(_FakePool()) is not None  # type: ignore[arg-type]
