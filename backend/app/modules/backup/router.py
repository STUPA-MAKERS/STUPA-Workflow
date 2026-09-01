"""Admin backup router (`/admin/backups`, gated by `backup.manage`).

The router lists the catalogue, creates a backup, exports one as a signed download,
imports an uploaded archive, restores one, and deletes one. Every long operation is
enqueued for the worker and the route answers 202 with the row to poll.

`backup.manage` is deliberately its own permission and sits in `FORBIDDEN_PERMISSIONS`,
so no OAuth agent token can reach any of this. Its holder can read the whole database
and replace it, which stays with a human at a browser.

Every route here writes an audit entry. `backup_create` and `backup_restore` are written
by the worker, once the work actually happened; the route only records the intent it
could not otherwise prove, so a failed job never leaves a log line claiming success.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Request, UploadFile, status

from app.deps import DbSession, Principal, SettingsDep, require_principal
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.backup.archive import ArchiveError, sha256_of
from app.modules.backup.models import Backup
from app.modules.backup.queue import backup_queue_from_pool
from app.modules.backup.schemas import (
    BackupCreate,
    BackupExportOut,
    BackupJobOut,
    BackupListOut,
    BackupOut,
    BackupRestoreBody,
    BackupUpdate,
)
from app.modules.backup.service import (
    ARCHIVE_CONTENT_TYPE,
    BackupError,
    BackupService,
    archive_key,
    stream_upload,
    temp_file,
)
from app.modules.files.storage import build_object_storage
from app.shared.errors import (
    ConflictError,
    NotFoundError,
    ProblemDetail,
    ServiceUnavailableError,
    ValidationProblem,
)

router = APIRouter(prefix="/admin/backups", tags=["backup"])

# The literal a client must send to restore. It is not translated: it is a machine
# confirmation token, and the UI types it for the operator after its own dialog.
RESTORE_CONFIRMATION = "RESTORE"

_UPLOAD_CHUNK = 1024 * 1024


def _errors(*codes: int) -> dict[int | str, dict[str, object]]:
    return {code: {"model": ProblemDetail} for code in codes}


def get_backup_service(session: DbSession, settings: SettingsDep) -> BackupService:
    """Build the service with both buckets: the attachments and the archives."""
    return BackupService(
        session,
        settings,
        attachments=build_object_storage(settings),
        archives=build_object_storage(settings, bucket=settings.backup_bucket),
    )


ServiceDep = Annotated[BackupService, Depends(get_backup_service)]
AdminDep = Annotated[Principal, Depends(require_principal("backup.manage"))]


def _require_enabled(service: BackupService) -> None:
    """Refuse with 503 when no age recipient is configured.

    Raises:
        ServiceUnavailableError: Backups are switched off for this deployment.
    """
    if not service.settings.backup_enabled:
        raise ServiceUnavailableError("Backups are not configured for this installation.")


def _require_restore_enabled(service: BackupService) -> None:
    """Refuse with 503 when no age identity is mounted.

    Raises:
        ServiceUnavailableError: The platform cannot decrypt its own archives.
    """
    _require_enabled(service)
    if not service.settings.backup_restore_enabled:
        raise ServiceUnavailableError(
            "No age identity is mounted, so this installation cannot read an archive."
        )


async def _load(service: BackupService, backup_id: UUID) -> Backup:
    """Load one row.

    Raises:
        NotFoundError: No such backup.
    """
    row = await service.get(backup_id)
    if row is None:
        raise NotFoundError("Backup not found.")
    return row


@router.get("", response_model=BackupListOut, responses=_errors(401, 403))
async def list_backups(
    service: ServiceDep,
    _admin: AdminDep,
    limit: int = 100,
    offset: int = 0,
) -> BackupListOut:
    """List the catalogue, newest first, plus what this installation can do."""
    rows = await service.list(limit=min(limit, 200), offset=max(offset, 0))
    return BackupListOut(
        items=[BackupOut.model_validate(row) for row in rows],
        enabled=service.settings.backup_enabled,
        restore_enabled=service.settings.backup_restore_enabled,
        retention_count=service.settings.backup_retention_count,
    )


@router.get("/{backup_id}", response_model=BackupOut, responses=_errors(401, 403, 404))
async def get_backup(backup_id: UUID, service: ServiceDep, _admin: AdminDep) -> BackupOut:
    """Return one row. The page polls this while a job runs."""
    return BackupOut.model_validate(await _load(service, backup_id))


@router.post(
    "",
    response_model=BackupJobOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_errors(401, 403, 503),
)
async def create_backup(
    body: BackupCreate,
    service: ServiceDep,
    session: DbSession,
    request: Request,
    admin: AdminDep,
) -> BackupJobOut:
    """Create a catalogue row and enqueue the archive build.

    Answers 202. The worker does the dump, so the row starts ``pending``.
    """
    _require_enabled(service)
    row = await service.create_row(kind="manual", actor=admin.sub, note=body.note)
    await session.commit()
    # Enqueue after the commit, so the worker always finds the row.
    queue = backup_queue_from_pool(getattr(request.app.state, "arq_pool", None))
    if queue is not None:
        await queue.enqueue_create(row.id)
    return BackupJobOut(id=row.id, status=row.status)


@router.patch("/{backup_id}", response_model=BackupOut, responses=_errors(401, 403, 404))
async def update_backup(
    backup_id: UUID,
    body: BackupUpdate,
    service: ServiceDep,
    session: DbSession,
    _admin: AdminDep,
) -> BackupOut:
    """Edit the note, or pin the archive so retention never prunes it."""
    row = await _load(service, backup_id)
    if body.note is not None:
        row.note = body.note
    if body.pinned is not None:
        row.pinned = body.pinned
    await session.commit()
    return BackupOut.model_validate(row)


@router.get(
    "/{backup_id}/export",
    response_model=BackupExportOut,
    responses=_errors(401, 403, 404, 409, 503),
)
async def export_backup(
    backup_id: UUID,
    service: ServiceDep,
    session: DbSession,
    admin: AdminDep,
) -> BackupExportOut:
    """Hand out a short-lived signed URL for the archive.

    The archive stays age-encrypted on the way out. The URL is what leaves the platform,
    never the plaintext, and the audit entry records that it was handed out at all.
    """
    _require_enabled(service)
    row = await _load(service, backup_id)
    if row.status != "done":
        raise ConflictError("This backup carries no archive yet.", code="backup_not_ready")
    try:
        url = service.export_url(row)
    except BackupError as exc:
        raise ServiceUnavailableError(str(exc)) from exc
    await audit_record(
        session,
        actor=admin.sub,
        action=AuditAction.BACKUP_EXPORT,
        target_type="backup",
        target_id=str(row.id),
        data={"checksum": row.checksum, "sizeBytes": row.size_bytes},
    )
    await session.commit()
    return BackupExportOut(url=url, expires_in=service.settings.backup_url_ttl_seconds)


@router.post(
    "/import",
    response_model=BackupOut,
    status_code=status.HTTP_201_CREATED,
    responses=_errors(401, 403, 413, 422, 503),
)
async def import_backup(
    service: ServiceDep,
    session: DbSession,
    admin: AdminDep,
    file: Annotated[UploadFile, File()],
) -> BackupOut:
    """Take an uploaded archive into the catalogue.

    The upload is decrypted far enough to read its manifest, which proves the archive
    is one of ours and that this installation can actually open it. Without that check
    a restore would be the first thing to discover the file is unusable, and by then it
    has already taken a safety backup and started replacing data.

    The import stores the archive as it arrived. It does NOT restore it: the operator
    picks the restore separately, from the list.
    """
    _require_restore_enabled(service)
    if service.archives is None:  # pragma: no cover — guarded by _require_enabled
        raise ServiceUnavailableError("Object storage is not configured.")

    cap = service.settings.backup_max_upload_bytes
    with temp_file(".age") as local:
        try:
            size = await stream_upload(_chunks(file), local, cap)
        except BackupError as exc:
            raise ValidationProblem(str(exc), code="backup_too_large") from exc
        checksum = sha256_of(local)
        try:
            manifest = service.verify_archive(local.name)
        except (ArchiveError, BackupError) as exc:
            raise ValidationProblem(str(exc), code="backup_unreadable") from exc

        row = await service.create_row(kind="imported", actor=admin.sub, note=None)
        key = archive_key(row.id, row.created_at)
        await service.archives.put_file(key, local.name, ARCHIVE_CONTENT_TYPE)

    row.status = "done"
    row.storage_key = key
    row.size_bytes = size
    row.checksum = checksum
    row.object_count = manifest.object_count
    row.app_version = manifest.app_version
    row.schema_revision = manifest.schema_revision
    row.touch_finished(row.created_at)
    await audit_record(
        session,
        actor=admin.sub,
        action=AuditAction.BACKUP_IMPORT,
        target_type="backup",
        target_id=str(row.id),
        data={
            "checksum": checksum,
            "sizeBytes": size,
            "objectCount": manifest.object_count,
            "archiveAppVersion": manifest.app_version,
            "archiveSchemaRevision": manifest.schema_revision,
        },
    )
    await session.commit()
    return BackupOut.model_validate(row)


async def _chunks(file: UploadFile) -> AsyncIterator[bytes]:
    """Yield the upload in chunks, so a large archive never lands in memory whole."""
    while chunk := await file.read(_UPLOAD_CHUNK):
        yield chunk


@router.post(
    "/{backup_id}/restore",
    response_model=BackupJobOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_errors(401, 403, 404, 409, 422, 503),
)
async def restore_backup(
    backup_id: UUID,
    body: BackupRestoreBody,
    service: ServiceDep,
    session: DbSession,
    request: Request,
    admin: AdminDep,
) -> BackupJobOut:
    """Enqueue a restore of this archive over the live platform.

    The worker takes a `pre_restore` safety archive before it replaces anything, so a
    restore of the wrong archive is itself undoable. Everybody is logged out, because
    the session table comes from the archive too.

    Answers 202. The audit entry lands in the RESTORED chain, written by the worker.
    """
    _require_restore_enabled(service)
    row = await _load(service, backup_id)
    if row.status != "done":
        raise ConflictError("This backup carries no archive to restore.", code="backup_not_ready")
    if body.confirm != RESTORE_CONFIRMATION:
        raise ValidationProblem(
            f"Send confirm='{RESTORE_CONFIRMATION}' to restore.",
            code="backup_confirm_required",
        )
    queue = backup_queue_from_pool(getattr(request.app.state, "arq_pool", None))
    if queue is None:
        raise ServiceUnavailableError("The job queue is unavailable, so no restore can start.")
    await queue.enqueue_restore(row.id, admin.sub)
    return BackupJobOut(id=row.id, status="running")


@router.delete(
    "/{backup_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_errors(401, 403, 404, 409),
)
async def delete_backup(
    backup_id: UUID,
    service: ServiceDep,
    session: DbSession,
    admin: AdminDep,
) -> None:
    """Delete the archive and its catalogue row.

    A pinned archive is refused. Unpin it first; that keeps a deliberate keep from
    being undone by one stray click.
    """
    row = await _load(service, backup_id)
    if row.pinned:
        raise ConflictError(
            "This backup is pinned. Unpin it before you delete it.",
            code="backup_pinned",
        )
    await audit_record(
        session,
        actor=admin.sub,
        action=AuditAction.BACKUP_DELETE,
        target_type="backup",
        target_id=str(row.id),
        data={"kind": row.kind, "checksum": row.checksum},
    )
    await service.delete(row)
    await session.commit()
