"""arq worker tasks: build a backup archive, and restore one.

Both tasks are long. A dump of the whole platform plus a mirror of the attachment
bucket takes minutes on a real dataset, which is exactly why neither runs in a request.

Neither task retries. A half-finished restore is not something to re-attempt blindly,
and a failed backup is cheap to start again from the page. Both mark the catalogue row
`failed` with a short code instead, and the row is what the admin page shows.

`create_backup` also serves the nightly cron. `run_retention` prunes archives past the
retention count; it never touches a pinned archive or a `pre_restore` safety copy.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.backup.archive import ArchiveError
from app.modules.backup.service import BackupError, BackupService, temp_file
from app.modules.files.storage import build_object_storage
from app.settings import Settings, load_settings

logger = logging.getLogger("app.backup")


async def on_startup(ctx: dict[str, Any]) -> None:
    """Build the two storages the backup tasks need."""
    settings = load_settings()
    ctx["backup_settings"] = settings
    ctx["backup_attachments"] = build_object_storage(settings)
    ctx["backup_archives"] = build_object_storage(settings, bucket=settings.backup_bucket)


def _sessionmaker(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    """Return the DB sessionmaker (tests inject one via `ctx['backup_sessionmaker']`)."""
    maker = ctx.get("backup_sessionmaker")
    return maker if maker is not None else get_sessionmaker()


def _settings(ctx: dict[str, Any]) -> Settings:
    settings = ctx.get("backup_settings")
    return settings if isinstance(settings, Settings) else load_settings()


def _service(ctx: dict[str, Any], session: AsyncSession) -> BackupService:
    return BackupService(
        session,
        _settings(ctx),
        attachments=ctx.get("backup_attachments"),
        archives=ctx.get("backup_archives"),
    )


async def create_backup(ctx: dict[str, Any], backup_id: str) -> str:
    """Build the archive for one pending catalogue row.

    Returns:
        One of ``done``, ``failed`` or ``gone``.
    """
    async with _sessionmaker(ctx)() as session:
        service = _service(ctx, session)
        row = await service.get(UUID(backup_id))
        if row is None:
            logger.info("backup row %s gone — skipped", backup_id)
            return "gone"
        if row.status == "done":
            return "done"  # idempotent: the archive already exists
        await service.mark_running(row)
        await session.commit()

        try:
            result = await service.build_archive(row)
        except (BackupError, ArchiveError) as exc:
            logger.error("backup %s failed: %s", backup_id, exc)
            await service.mark_failed(row, str(exc))
            await session.commit()
            return "failed"

        await service.mark_done(row, result)
        await audit_record(
            session,
            actor=row.created_by,
            action=AuditAction.BACKUP_CREATE,
            target_type="backup",
            target_id=str(row.id),
            data={
                "kind": row.kind,
                "sizeBytes": result.size_bytes,
                "objectCount": result.object_count,
                "checksum": result.checksum,
                "schemaRevision": result.schema_revision,
            },
        )
        await session.commit()

    await run_retention(ctx)
    return "done"


async def run_retention(ctx: dict[str, Any]) -> int:
    """Prune archives past the retention count.

    Returns:
        The number of archives removed.
    """
    async with _sessionmaker(ctx)() as session:
        service = _service(ctx, session)
        try:
            doomed = await service.prune()
        except Exception:  # noqa: BLE001 — retention must never fail a backup
            logger.exception("backup retention failed")
            return 0
        if doomed:
            await audit_record(
                session,
                actor=None,
                action=AuditAction.BACKUP_DELETE,
                target_type="backup",
                target_id=None,
                data={"retention": True, "ids": [str(row.id) for row in doomed]},
            )
        await session.commit()
        return len(doomed)


async def scheduled_backup(ctx: dict[str, Any]) -> str:
    """Nightly cron: create a catalogue row and build its archive.

    The job does nothing when backups are not configured, so a stack without an age
    recipient does not fill the log with failures every night.
    """
    settings = _settings(ctx)
    if not settings.backup_enabled:
        return "disabled"
    async with _sessionmaker(ctx)() as session:
        service = _service(ctx, session)
        row = await service.create_row(kind="scheduled", actor=None, note=None)
        await session.commit()
        backup_id = str(row.id)
    return await create_backup(ctx, backup_id)


async def restore_backup(ctx: dict[str, Any], backup_id: str, actor: str | None) -> str:
    """Restore one archive over the live platform.

    The task takes a `pre_restore` safety archive FIRST and only replaces anything once
    that archive is stored. A restore is the one operation here that destroys data, so
    the undo has to exist before the damage does.

    The audit entry for the restore lands in the chain of the RESTORED state, because
    the restore replaces `audit_entry` along with everything else. The safety archive is
    what proves what the platform looked like beforehand.

    Returns:
        One of ``done``, ``failed`` or ``gone``.
    """
    settings = _settings(ctx)
    if not settings.backup_restore_enabled:
        logger.error("restore requested but no age identity is configured")
        return "failed"

    safety_id = await _safety_backup(ctx, actor)
    if safety_id is None:
        logger.error("restore aborted: the safety backup failed")
        return "failed"

    async with _sessionmaker(ctx)() as session:
        service = _service(ctx, session)
        row = await service.get(UUID(backup_id))
        if row is None or not row.storage_key:
            logger.info("restore target %s gone — skipped", backup_id)
            return "gone"
        archives = ctx.get("backup_archives")
        if archives is None:
            return "failed"

        try:
            with temp_file(".age") as local:
                await archives.get_file(row.storage_key, local.name)
                manifest = await service.apply_archive(local.name)
        except (BackupError, ArchiveError) as exc:
            logger.error("restore %s failed: %s", backup_id, exc)
            return "failed"

    # A new session: the one above talks to a database that no longer exists in the
    # form it was opened against.
    async with _sessionmaker(ctx)() as session:
        await audit_record(
            session,
            actor=actor,
            action=AuditAction.BACKUP_RESTORE,
            target_type="backup",
            target_id=backup_id,
            data={
                "safetyBackupId": safety_id,
                "restoredAt": datetime.now(UTC).isoformat(),
                "archiveCreatedAt": manifest.created_at,
                "archiveAppVersion": manifest.app_version,
                "archiveSchemaRevision": manifest.schema_revision,
                "objectCount": manifest.object_count,
            },
        )
        await session.commit()
    return "done"


async def _safety_backup(ctx: dict[str, Any], actor: str | None) -> str | None:
    """Take the `pre_restore` archive and return its id, or ``None`` when it failed."""
    async with _sessionmaker(ctx)() as session:
        service = _service(ctx, session)
        row = await service.create_row(
            kind="pre_restore",
            actor=actor,
            note="Automatic safety copy taken before a restore.",
        )
        await session.commit()
        safety_id = str(row.id)
    outcome = await create_backup(ctx, safety_id)
    return safety_id if outcome == "done" else None
