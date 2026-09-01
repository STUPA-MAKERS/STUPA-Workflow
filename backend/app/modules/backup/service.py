"""Backup service: the catalogue, the archive build, and the restore.

The service owns three things:

* the `backup` catalogue rows that the admin page lists,
* `build_archive`, which turns the live database and the attachment bucket into one
  encrypted archive,
* `apply_archive`, which puts an archive back.

The heavy work runs in the arq worker (`tasks.py`), never in a request. A dump of the
whole platform takes as long as it takes, and an API worker that blocks on it stops
serving everyone else.

Everything streams through temporary files. `tempfile` honours `TMPDIR`, so a deployment
that puts the container's temporary directory on a small tmpfs will fail here first; the
deploy README calls that out.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tarfile
import tempfile
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.backup import archive as arch
from app.modules.backup.models import Backup
from app.modules.files.storage import BulkObjectStorage, StorageError
from app.settings import Settings

logger = logging.getLogger(__name__)

# Content type of an archive object. The bytes are age ciphertext, so nothing more
# specific applies and nothing must ever render it inline.
ARCHIVE_CONTENT_TYPE = "application/octet-stream"


class BackupError(RuntimeError):
    """A backup or a restore failed. The message is short and carries no path."""


@dataclass(slots=True)
class ArchiveResult:
    """What `build_archive` produced."""

    storage_key: str
    size_bytes: int
    checksum: str
    object_count: int
    schema_revision: str | None


def archive_key(backup_id: UUID, created_at: datetime) -> str:
    """Object key of an archive: sortable by time, unique by id."""
    stamp = created_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"antrag-{stamp}-{backup_id}.tar.age"


def download_name(created_at: datetime) -> str:
    """File name the browser saves an exported archive under."""
    return f"antrag-{created_at.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}.tar.age"


def libpq_dsn(database_url: str) -> str:
    """Turn the SQLAlchemy URL into one the libpq tools accept.

    `pg_dump` and `pg_restore` cannot read the `postgresql+asyncpg://` driver prefix
    that SQLAlchemy needs, so the scheme is rewritten to plain `postgresql`.
    """
    parts = urlsplit(database_url)
    scheme = parts.scheme.split("+", 1)[0] or "postgresql"
    return urlunsplit((scheme, parts.netloc, parts.path, parts.query, parts.fragment))


@contextmanager
def temp_file(suffix: str) -> Iterator[IO[bytes]]:
    """Open a named temporary file that is removed on the way out."""
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)  # noqa: SIM115
    try:
        yield handle
    finally:
        handle.close()
        with suppress(OSError):  # the file may already be gone
            os.unlink(handle.name)


@contextmanager
def _open_staged(staged: list[tuple[str, Path]]) -> Iterator[list[tuple[str, IO[bytes]]]]:
    """Open every staged object for reading and close them all on the way out."""
    handles: list[tuple[str, IO[bytes]]] = []
    try:
        for key, path in staged:
            handles.append((key, path.open("rb")))
        yield handles
    finally:
        for _, handle in handles:
            handle.close()


class BackupService:
    """Catalogue reads and writes plus the archive build and restore."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        attachments: BulkObjectStorage | None = None,
        archives: BulkObjectStorage | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.attachments = attachments
        self.archives = archives

    # ---------------------------------------------------------------- catalogue

    async def list(self, *, limit: int = 100, offset: int = 0) -> list[Backup]:
        """Return the catalogue, newest first."""
        stmt = select(Backup).order_by(Backup.created_at.desc()).limit(limit).offset(offset)
        return list((await self.session.scalars(stmt)).all())

    async def get(self, backup_id: UUID) -> Backup | None:
        """Return one catalogue row, or ``None``."""
        return await self.session.get(Backup, backup_id)

    async def create_row(
        self, *, kind: str, actor: str | None, note: str | None = None
    ) -> Backup:
        """Insert a pending catalogue row. The worker fills in the rest."""
        row = Backup(
            kind=kind,
            status="pending",
            created_by=actor,
            note=note,
            app_version=self.settings.app_version,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def mark_running(self, row: Backup) -> None:
        """Move a row to ``running`` before the long work starts."""
        row.status = "running"
        await self.session.flush()

    async def mark_done(self, row: Backup, result: ArchiveResult) -> None:
        """Record a finished archive on the catalogue row."""
        row.status = "done"
        row.storage_key = result.storage_key
        row.size_bytes = result.size_bytes
        row.checksum = result.checksum
        row.object_count = result.object_count
        row.schema_revision = result.schema_revision
        row.error = None
        row.touch_finished(datetime.now(UTC))
        await self.session.flush()

    async def mark_failed(self, row: Backup, code: str) -> None:
        """Record a short failure code. The code never carries a path."""
        row.status = "failed"
        row.error = code[:200]
        row.touch_finished(datetime.now(UTC))
        await self.session.flush()

    async def prune(self) -> list[Backup]:
        """Delete archives beyond the retention count, oldest first.

        A pinned row and a ``pre_restore`` row never count towards the limit and never
        get pruned. A safety copy is the one archive somebody needs after a bad
        restore, so retention must not be what removes it.

        Returns:
            The rows that were deleted.
        """
        keep = self.settings.backup_retention_count
        if keep <= 0:
            return []
        stmt = (
            select(Backup)
            .where(
                Backup.status == "done",
                Backup.pinned.is_(False),
                Backup.kind.notin_(("pre_restore",)),
            )
            .order_by(Backup.created_at.desc())
        )
        rows = list((await self.session.scalars(stmt)).all())
        doomed = rows[keep:]
        for row in doomed:
            await self.delete(row)
        return doomed

    async def delete(self, row: Backup) -> None:
        """Remove the archive object and then the catalogue row.

        The object goes first. A row without its object is a lie the admin page would
        show as restorable, while an orphaned object only wastes space.
        """
        if row.storage_key and self.archives is not None:
            try:
                await self.archives.remove(row.storage_key)
            except StorageError:
                logger.warning("backup object already gone (backup=%s)", row.id)
        await self.session.delete(row)
        await self.session.flush()

    def export_url(self, row: Backup) -> str:
        """Return a short-lived signed URL for the archive.

        Raises:
            BackupError: Storage is off, or the row carries no archive.
        """
        if self.archives is None or not row.storage_key:
            raise BackupError("this backup has no stored archive")
        return self.archives.presigned_get_url(
            row.storage_key,
            expires_seconds=self.settings.backup_url_ttl_seconds,
            download_name=download_name(row.created_at),
        )

    # ------------------------------------------------------------------ archive

    async def build_archive(self, row: Backup) -> ArchiveResult:
        """Dump the database and the bucket into one encrypted archive.

        Raises:
            BackupError: Storage is off, the age recipient is unusable, or `pg_dump`
                failed.
        """
        if self.attachments is None or self.archives is None:
            raise BackupError("object storage is not configured")
        if not self.settings.backup_age_recipient:
            raise BackupError("no age recipient is configured")
        recipient = arch.recipient_from_str(self.settings.backup_age_recipient)
        revision = await self._schema_revision()

        key = archive_key(row.id, row.created_at)
        with (
            temp_file(".dump") as dump,
            temp_file(".tar") as tar_file,
            tempfile.TemporaryDirectory(prefix="antrag-objects-") as staging,
        ):
            await self._pg_dump(dump.name)
            dump.seek(0)
            manifest = arch.ArchiveManifest(
                app_version=self.settings.app_version,
                schema_revision=revision,
                created_at=datetime.now(UTC).isoformat(),
                bucket=self.settings.minio_bucket,
            )
            staged = await self._stage_objects(Path(staging))
            with _open_staged(staged) as readers:
                count = await asyncio.to_thread(arch.write_tar, tar_file, dump, readers, manifest)
            with temp_file(".age") as encrypted:
                checksum, size = await asyncio.to_thread(
                    arch.encrypt_stream, tar_file, encrypted, recipient
                )
                await self.archives.put_file(key, encrypted.name, ARCHIVE_CONTENT_TYPE)

        return ArchiveResult(
            storage_key=key,
            size_bytes=size,
            checksum=checksum,
            object_count=count,
            schema_revision=revision,
        )

    async def _stage_objects(self, staging: Path) -> list[tuple[str, Path]]:
        """Download the attachment bucket into `staging`, one file per object.

        The tar is written in a worker thread, so it cannot await a download mid-stream.
        Staging first keeps that boundary clean and keeps peak memory at one object
        rather than the whole bucket. The file names are counters, never the object
        keys, so a key with a slash or a traversal segment cannot steer the write.

        Returns:
            `(object key, staged path)` pairs, in bucket order.
        """
        assert self.attachments is not None
        staged: list[tuple[str, Path]] = []
        for index, key in enumerate(await self.attachments.list_keys()):
            path = staging / f"{index:08d}.bin"
            try:
                await self.attachments.get_file(key, str(path))
            except StorageError:
                logger.warning("attachment vanished during backup, skipped")
                continue
            staged.append((key, path))
        return staged

    async def _schema_revision(self) -> str | None:
        """Read the alembic head the live database sits at."""
        try:
            value = await self.session.scalar(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            )
        except Exception:  # noqa: BLE001 — a fresh database may not have the table
            return None
        return str(value) if value is not None else None

    async def _pg_dump(self, target_path: str) -> None:
        """Run `pg_dump --format=custom` into `target_path`.

        Raises:
            BackupError: `pg_dump` is missing, timed out, or exited non-zero.
        """
        await self._run(
            [
                "pg_dump",
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                f"--file={target_path}",
                "--dbname",
                libpq_dsn(self.settings.database_url),
            ],
            what="pg_dump",
        )

    # ------------------------------------------------------------------ restore

    async def apply_archive(self, path: str) -> arch.ArchiveManifest:
        """Decrypt `path`, restore the database, and mirror the bucket back.

        The database goes first. If the object mirror then fails, the platform is at
        least internally consistent and the operator can retry the mirror; the other
        order would leave rows pointing at attachments that no longer exist.

        Raises:
            BackupError: The identity is missing, the archive is unreadable, or
                `pg_restore` failed.
        """
        if self.attachments is None:
            raise BackupError("object storage is not configured")
        identity = self._identity()

        with temp_file(".tar") as plain, open(path, "rb") as ciphertext:
            await asyncio.to_thread(arch.decrypt_stream, ciphertext, plain, identity)
            with arch.open_tar(plain) as tar:
                manifest = arch.read_manifest(tar)
                with temp_file(".dump") as dump:
                    await asyncio.to_thread(arch.extract_dump, tar, dump)
                    await self._pg_restore(dump.name)
                await self._mirror_objects(tar)
        return manifest

    def verify_archive(self, path: str) -> arch.ArchiveManifest:
        """Decrypt an archive far enough to read and validate its manifest.

        The import path calls this before it stores anything. Without the check a
        restore would be the first thing to find out that a file is unusable, and by
        then it has already taken a safety backup and started replacing data.

        Raises:
            BackupError: No identity is configured.
            ArchiveError: The file does not decrypt, or carries no usable manifest.
        """
        identity = self._identity()
        with temp_file(".tar") as plain, open(path, "rb") as ciphertext:
            arch.decrypt_stream(ciphertext, plain, identity)
            with arch.open_tar(plain) as tar:
                return arch.read_manifest(tar)

    def _identity(self) -> arch.x25519.Identity:
        """Read and parse the mounted age private key.

        Raises:
            BackupError: No identity file is configured, or it is unreadable.
        """
        path = self.settings.backup_age_identity_file
        if not path:
            raise BackupError("no age identity is configured, so no restore is possible")
        try:
            raw = open(path, encoding="utf-8").read()  # noqa: SIM115
        except OSError as exc:
            raise BackupError("the age identity file is not readable") from exc
        return arch.identity_from_str(raw)

    async def _pg_restore(self, dump_path: str) -> None:
        """Replace the database contents from `dump_path`.

        `--clean --if-exists` drops what is there first, so the result matches the
        archive exactly rather than merging into it. The audit trigger blocks UPDATE
        and DELETE on `audit_entry` but not the DROP that `--clean` issues, so the
        chain comes back as the archive holds it.

        Raises:
            BackupError: `pg_restore` is missing, timed out, or failed hard.
        """
        await self._run(
            [
                "pg_restore",
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-privileges",
                "--dbname",
                libpq_dsn(self.settings.database_url),
                dump_path,
            ],
            what="pg_restore",
            # `--clean` warns for every object the target does not have yet, and those
            # warnings set a non-zero exit even on a good restore. The caller verifies
            # the outcome instead of trusting the code.
            tolerate_nonzero=True,
        )

    async def _mirror_objects(self, tar: tarfile.TarFile) -> None:
        """Make the attachment bucket match the archive exactly.

        Objects the archive holds are written, and objects it does not hold are
        removed. Without the removal a restore would leave attachments behind that the
        restored database has no row for.
        """
        assert self.attachments is not None
        before = set(await self.attachments.list_keys())
        seen: set[str] = set()
        for key, payload in arch.iter_objects(tar):
            await self.attachments.put(key, payload, ARCHIVE_CONTENT_TYPE)
            seen.add(key)
        for stale in before - seen:
            try:
                await self.attachments.remove(stale)
            except StorageError:
                logger.warning("could not remove a stale object during restore")

    # ------------------------------------------------------------- subprocesses

    async def _run(self, argv: list[str], *, what: str, tolerate_nonzero: bool = False) -> None:
        """Run one libpq tool with a timeout.

        The child inherits no shell. The connection string carries the password, so it
        goes in `argv` rather than the environment and never reaches a log line.

        Raises:
            BackupError: The binary is missing, the run timed out, or it failed.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise BackupError(f"{what} is not installed in this image") from exc
        try:
            _, err = await asyncio.wait_for(
                proc.communicate(), timeout=self.settings.backup_subprocess_timeout_seconds
            )
        except TimeoutError as exc:
            proc.kill()
            raise BackupError(f"{what} timed out") from exc
        if proc.returncode != 0 and not tolerate_nonzero:
            logger.error("%s failed: %s", what, err.decode(errors="replace")[:2000])
            raise BackupError(f"{what} failed")
        if proc.returncode != 0:
            logger.warning("%s warnings: %s", what, err.decode(errors="replace")[:2000])


async def stream_upload(
    source: AsyncIterator[bytes], target: IO[bytes], cap: int
) -> int:
    """Copy an upload into `target`, stopping at `cap` bytes.

    Returns:
        The number of bytes written.

    Raises:
        BackupError: The upload is larger than the cap.
    """
    total = 0
    async for chunk in source:
        total += len(chunk)
        if total > cap:
            raise BackupError("the uploaded archive is larger than the configured cap")
        target.write(chunk)
    target.flush()
    return total
