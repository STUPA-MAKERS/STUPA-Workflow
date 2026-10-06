"""Unit tests for the backup paths that the other files do not reach.

be-backup is a critical module (D11): every branch must run in the pure unit suite. The
tests here drive the catalogue reads, the restore chain (`apply_archive` → `pg_restore`
→ disconnect) and the rare archive faults with fakes and stubbed subprocesses. Nothing
here dumps or restores a real database.
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pyrage import x25519  # pyright: ignore[reportAttributeAccessIssue]

from app.modules.backup import archive as arch
from app.modules.backup.models import ARCHIVE_DUMP_NAME, ARCHIVE_OBJECT_PREFIX
from app.modules.backup.service import BackupError, BackupService
from tests.unit.modules.backup.test_backup_service import (
    _FakeSession,
    _FakeStorage,
    _row,
    _settings,
)

# ------------------------------------------------------------------------ catalogue


async def test_list_and_get_read_the_catalogue() -> None:
    row = _row(kind="manual", status="done")
    service = BackupService(_FakeSession([row]), _settings())  # type: ignore[arg-type]
    assert await service.list() == [row]
    assert await service.get(row.id) is row
    assert await service.get(uuid4()) is None


async def test_mark_running_moves_the_row_and_flushes() -> None:
    session = _FakeSession()
    row = _row(kind="manual", status="pending")
    await BackupService(session, _settings()).mark_running(row)  # type: ignore[arg-type]
    assert row.status == "running"
    assert session.flushed == 1


async def test_delete_without_an_archive_removes_only_the_row() -> None:
    session = _FakeSession()
    storage = _FakeStorage({"other": b"x"})
    row = _row(kind="manual", status="failed", storage_key=None)
    service = BackupService(session, _settings(), archives=storage)  # type: ignore[arg-type]
    await service.delete(row)
    assert session.deleted == [row]
    assert storage.removed == []


async def test_snapshot_catalogue_copies_every_column() -> None:
    row = _row(kind="manual", status="done", note="n")
    service = BackupService(_FakeSession([row]), _settings())  # type: ignore[arg-type]
    [snapshot] = await service.snapshot_catalogue()
    assert snapshot["id"] == row.id
    assert snapshot["note"] == "n"


class _ExecSession(_FakeSession):
    """Session double whose `execute` answers like a cursor result."""

    def __init__(self, rowcount: int | None) -> None:
        super().__init__()
        self.rowcount = rowcount
        self.executed: list[object] = []

    async def execute(self, stmt: object) -> Any:
        self.executed.append(stmt)

        class _Result:
            rowcount = self.rowcount

        return _Result()


async def test_reseed_writes_nothing_for_an_empty_catalogue() -> None:
    session = _ExecSession(rowcount=0)
    service = BackupService(session, _settings())  # type: ignore[arg-type]
    assert await service.reseed_catalogue([]) == 0
    assert session.executed == []


@pytest.mark.parametrize(("rowcount", "expected"), [(2, 2), (None, 0)])
async def test_reseed_returns_the_rows_the_insert_wrote(
    rowcount: int | None, expected: int
) -> None:
    session = _ExecSession(rowcount=rowcount)
    service = BackupService(session, _settings())  # type: ignore[arg-type]
    rows = [{"id": uuid4(), "kind": "manual", "status": "done"}]
    assert await service.reseed_catalogue(rows) == expected
    assert len(session.executed) == 1


# ------------------------------------------------------------------- subprocesses


class _Recorder:
    """Stands in for `BackupService._run` and records each command."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[list[str], str, bool]] = []
        self.error = error

    async def __call__(
        self, argv: list[str], *, what: str, tolerate_nonzero: bool = False
    ) -> None:
        self.calls.append((argv, what, tolerate_nonzero))
        if self.error is not None:
            raise self.error


def _service_with_run(
    monkeypatch: pytest.MonkeyPatch, run: _Recorder, **kw: Any
) -> BackupService:
    service = BackupService(
        object(),  # type: ignore[arg-type]  # these paths never touch the session
        _settings(database_url="postgresql+asyncpg://u:p@db/antrag"),
        **kw,
    )
    monkeypatch.setattr(service, "_run", run)
    return service


async def test_pg_dump_writes_the_custom_format_to_the_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _Recorder()
    await _service_with_run(monkeypatch, run)._pg_dump("/tmp/x.dump")  # noqa: SLF001, S108
    [(argv, what, tolerate)] = run.calls
    assert argv[0] == "pg_dump"
    assert "--format=custom" in argv
    assert "--file=/tmp/x.dump" in argv
    assert "postgresql://u:p@db/antrag" in argv
    assert (what, tolerate) == ("pg_dump", False)


async def test_pg_restore_disconnects_the_others_first_and_tolerates_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _Recorder()
    await _service_with_run(monkeypatch, run)._pg_restore("/tmp/x.dump")  # noqa: SLF001, S108
    assert [what for _, what, _ in run.calls] == ["psql (disconnect)", "pg_restore"]
    assert all(tolerate for _, _, tolerate in run.calls)
    assert run.calls[1][0][-1] == "/tmp/x.dump"  # noqa: S108


async def test_a_failed_disconnect_does_not_stop_the_restore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _Recorder(error=BackupError("psql is not installed in this image"))
    service = _service_with_run(monkeypatch, run)
    await service._disconnect_everyone_else()  # noqa: SLF001  # must not raise
    assert len(run.calls) == 1


async def test_a_clean_exit_passes_without_a_warning() -> None:
    service = BackupService(object(), _settings())  # type: ignore[arg-type]
    await service._run(["true"], what="pg_dump")  # noqa: SLF001


# ------------------------------------------------------------------------- restore


async def test_apply_archive_restores_the_dump_and_mirrors_the_objects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The whole restore chain with a real age archive and a stubbed `pg_restore`."""
    identity = x25519.Identity.generate()
    key_file = tmp_path / "age.key"
    key_file.write_text(str(identity))
    manifest = arch.ArchiveManifest(app_version="2.0", object_count=1)
    plain = io.BytesIO()
    arch.write_tar(plain, io.BytesIO(b"PGDUMP"), [("a.pdf", io.BytesIO(b"pdf"))], manifest)
    plain.seek(0)
    archive_path = tmp_path / "backup.age"
    with archive_path.open("w+b") as target:  # the checksum reads the target back
        arch.encrypt_stream(plain, target, identity.to_public())

    attachments = _FakeStorage({"stale.png": b"old"})
    service = BackupService(
        object(),  # type: ignore[arg-type]  # the restore path needs no session
        _settings(backup_age_identity_file=str(key_file)),
        attachments=attachments,  # type: ignore[arg-type]
    )
    restored: list[bytes] = []

    async def _pg_restore(dump_path: str) -> None:
        restored.append(Path(dump_path).read_bytes())

    monkeypatch.setattr(service, "_pg_restore", _pg_restore)
    result = await service.apply_archive(str(archive_path))

    assert result.app_version == "2.0"
    assert restored == [b"PGDUMP"]
    assert attachments.objects == {"a.pdf": b"pdf"}
    assert attachments.removed == ["stale.png"]


# ------------------------------------------------------------------- archive faults


def test_identity_skips_a_line_that_is_not_a_key() -> None:
    """A stray text line in the key file is skipped, the key after it still counts."""
    identity = x25519.Identity.generate()
    assert str(arch.identity_from_str(f"not a key\n{identity}\n")) == str(identity)


def test_iter_objects_skips_a_member_without_a_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    target = io.BytesIO()
    with tarfile.open(fileobj=target, mode="w") as tar:
        info = tarfile.TarInfo(name=f"{ARCHIVE_OBJECT_PREFIX}a.pdf")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    target.seek(0)
    with arch.open_tar(target) as tar:
        monkeypatch.setattr(tar, "extractfile", lambda _member: None)
        assert list(arch.iter_objects(tar)) == []


def test_a_member_that_is_not_a_regular_file_fails_clearly() -> None:
    """A crafted archive with a directory where the dump belongs is not readable."""
    target = io.BytesIO()
    with tarfile.open(fileobj=target, mode="w") as tar:
        info = tarfile.TarInfo(name=ARCHIVE_DUMP_NAME)
        info.type = tarfile.DIRTYPE
        tar.addfile(info)
    target.seek(0)
    with arch.open_tar(target) as tar, pytest.raises(arch.ArchiveError, match=ARCHIVE_DUMP_NAME):
        arch.extract_dump(tar, io.BytesIO())
