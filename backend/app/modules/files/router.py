"""Files API router.

* ``POST /api/applications/{id}/attachments`` — A(edit)/P; multipart upload ≤ 10 MB →
  MIME sniff + ClamAV scan (async), ``scanned=false`` until clean.
* ``GET  /api/attachments/{id}``             — A/P; returns the app-relative, authz-gated
  ``/download`` route (no direct bucket access, NO signed MinIO URL). 409 while
  quarantined, 410 when removed (finding).

Errors are declared as ``ProblemDetail`` (problem+json). Storage/scan are optional infra:
without MinIO → 503 (upload), without Redis → file stays quarantined.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from fastapi.responses import StreamingResponse

from app.deps import DbSession, SettingsDep, get_current_applicant, get_current_principal
from app.modules.applications.access import (
    EDIT_ANY_PERMISSION,
    MANAGE_PERMISSION,
    READ_ALL_PERMISSION,
    READ_PERMISSION,
    Access,
    _committee_can_read,
    _resolve_with_creator,
    require_app_edit,
    require_app_read,
)
from app.modules.auth.principal import Applicant, Principal
from app.modules.files.queue import scan_queue_from_pool
from app.modules.files.schemas import AttachmentOut, SignedUrlOut
from app.modules.files.service import FilesService
from app.modules.files.storage import _safe_disposition
from app.shared.antiabuse import rate_limit_attachments
from app.shared.errors import (
    ForbiddenError,
    NotFoundError,
    PayloadTooLargeError,
    ProblemDetail,
    UnauthorizedError,
)

router = APIRouter(tags=["files"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}
_CHUNK = 64 * 1024


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def get_files_service(
    session: DbSession, request: Request, settings: SettingsDep
) -> FilesService:
    """Wire the service with the (optional) storage + scan queue from app state."""
    storage = getattr(request.app.state, "object_storage", None)
    pool = getattr(request.app.state, "arq_pool", None)
    return FilesService(
        session,
        storage=storage,
        queue=scan_queue_from_pool(pool),
        settings=settings,
    )


ServiceDep = Annotated[FilesService, Depends(get_files_service)]


async def _resolve_attachment_read(
    db: DbSession,
    application_id: UUID,
    principal: Principal | None,
    applicant: Applicant | None,
) -> Access:
    """Read access to an attachment's application — covers the same paths as
    :func:`require_app_read` (not just global ``application.read`` via
    ``resolve_access``): ``application.read_all``, ``view`` applicant, logged-in creator,
    or gremium member in read scope.

    Deliberately mirrors the application read logic so an app someone may read also
    yields its attachments (no availability gap). The cross-object 404 stays the
    router's job (no existence oracle)."""
    if principal is not None and principal.has(READ_ALL_PERMISSION):
        return Access(application_id, principal, None)
    try:
        return await _resolve_with_creator(
            db, application_id, principal, applicant, perm=READ_PERMISSION, scope="view"
        )
    except ForbiddenError:
        if principal is not None and await _committee_can_read(
            db, application_id, principal
        ):
            return Access(application_id, principal, None)
        raise


async def _read_capped(file: UploadFile, max_bytes: int) -> bytes:
    """Stream the upload capped: > ``max_bytes`` → 413 (don't buffer the whole body)."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise PayloadTooLargeError(f"Attachment exceeds {max_bytes} bytes.")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post(
    "/applications/{application_id}/attachments",
    response_model=AttachmentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_attachments)],
    # 401/403 auth, 404 app missing, 413 too large, 415 type/sniff, 429 rate limit,
    # 503 storage off.
    responses=_errors(401, 403, 404, 413, 415, 429, 503),
)
async def upload_attachment(
    application_id: UUID,
    service: ServiceDep,
    access: Annotated[Access, Depends(require_app_edit)],
    file: Annotated[UploadFile, File()],
    field_key: Annotated[str | None, Form()] = None,
    is_comparison_offer: Annotated[bool, Form()] = False,
) -> AttachmentOut:
    """Upload an attachment. Stays ``scanned=false`` until the worker finishes ClamAV."""
    data = await _read_capped(file, service.max_bytes)
    return await service.upload(
        application_id,
        filename=file.filename,
        data=data,
        by=access.actor,
        field_key=field_key,
        is_comparison_offer=is_comparison_offer,
    )


@router.get(
    "/applications/{application_id}/attachments",
    response_model=list[AttachmentOut],
    responses=_errors(401, 403, 404),
)
async def list_attachments(
    application_id: UUID,
    service: ServiceDep,
    access: Annotated[Access, Depends(require_app_read)],
) -> list[AttachmentOut]:
    """List an application's attachments (panel hydration after reload). A/P access.

    An unconfirmed guest submission stays invisible to principals/gremium (404); only
    the owning magic-link applicant reads it — mirroring the list semantics."""
    return await service.list_for_application(
        access.application_id, allow_unconfirmed=access.is_owning_applicant
    )


@router.get(
    "/attachments/{attachment_id}",
    response_model=SignedUrlOut,
    responses=_errors(401, 404, 409, 410, 503),
)
async def get_attachment_url(
    attachment_id: UUID,
    service: ServiceDep,
    db: DbSession,
    principal: Annotated[Principal | None, Depends(get_current_principal)],
    applicant: Annotated[Applicant | None, Depends(get_current_applicant)],
) -> SignedUrlOut:
    """Signed download URL. Access via principal or the application's applicant."""
    # Fail-closed before the DB access: without identity 401 (no 404-vs-401 oracle that
    # would reveal an attachment's existence).
    if principal is None and applicant is None:
        raise UnauthorizedError("Authentication required.")
    attachment = await service.get_attachment(attachment_id)
    # Check read access against the attachment's application — same paths as
    # require_app_read (read_all/creator/gremium-read), not just global
    # application.read. Cross-tenant (authed but no read access) → 404 not 403 so an
    # authenticated outsider cannot tell an attachment exists (no existence oracle).
    try:
        access = await _resolve_attachment_read(
            db, attachment.application_id, principal, applicant
        )
    except ForbiddenError as exc:
        raise NotFoundError(f"attachment {attachment_id} not found") from exc
    # Unconfirmed guest submission stays invisible to principals/gremium (404); only the
    # owning magic-link applicant reads it — mirroring the list and detail gates.
    return await service.signed_url(
        attachment_id, allow_unconfirmed=access.is_owning_applicant
    )


@router.get(
    "/attachments/{attachment_id}/download",
    response_class=StreamingResponse,
    responses=_errors(401, 404, 409, 410, 503),
)
async def download_attachment(
    attachment_id: UUID,
    service: ServiceDep,
    db: DbSession,
    principal: Annotated[Principal | None, Depends(get_current_principal)],
    applicant: Annotated[Applicant | None, Depends(get_current_applicant)],
) -> StreamingResponse:
    """Stream attachment bytes server-side — MinIO is on the internal Docker network, so a
    presigned S3 URL binds the internal host and is unreachable from the browser. This
    endpoint is reachable via nginx ``/api/`` (same pattern as the protocol PDF).

    The object is streamed chunk-wise from storage — the API process never buffers the
    whole file in RAM. ``Content-Length`` comes from the stored size.

    Access like :func:`get_attachment_url` (A/P; cross-tenant → 404, no existence oracle).
    ``Content-Disposition: attachment`` forces download instead of inline render."""
    if principal is None and applicant is None:
        raise UnauthorizedError("Authentication required.")
    attachment = await service.get_attachment(attachment_id)
    try:
        access = await _resolve_attachment_read(
            db, attachment.application_id, principal, applicant
        )
    except ForbiddenError as exc:
        raise NotFoundError(f"attachment {attachment_id} not found") from exc
    # Unconfirmed guest submission stays invisible to principals/gremium (404); only the
    # owning magic-link applicant downloads it — mirroring the list and detail gates. The
    # quarantine gates (409/410/503) run in the service BEFORE the stream starts — the
    # StreamingResponse begins only after the gates.
    stream, filename, mime, size = await service.download_stream(
        attachment_id, allow_unconfirmed=access.is_owning_applicant
    )
    disposition = f'attachment; filename="{_safe_disposition(filename)}"'
    return StreamingResponse(
        stream,
        media_type=mime,
        headers={
            "Content-Disposition": disposition,
            "Content-Length": str(size),
        },
    )


@router.delete(
    "/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_errors(401, 403, 404),
)
async def delete_attachment(
    attachment_id: UUID,
    service: ServiceDep,
    db: DbSession,
    principal: Annotated[Principal | None, Depends(get_current_principal)],
    applicant: Annotated[Applicant | None, Depends(get_current_applicant)],
) -> None:
    """Delete an attachment — principal (``application.manage`` or
    ``application.edit_any``)/applicant (edit scope)/logged-in creator. Cross-tenant →
    404 (no existence oracle).

    Deliberately mirrors :func:`require_app_edit` (upload): ``application.edit_any`` is a
    global write right and must be able to delete the same attachment, else RBAC would be
    inconsistent (upload yes, delete 404)."""
    if principal is None and applicant is None:
        raise UnauthorizedError("Authentication required.")
    attachment = await service.get_attachment(attachment_id)
    if principal is not None and principal.has(EDIT_ANY_PERMISSION):
        await service.delete(attachment_id, actor=principal.sub)
        return
    try:
        access = await _resolve_with_creator(
            db,
            attachment.application_id,
            principal,
            applicant,
            perm=MANAGE_PERMISSION,
            scope="edit",
        )
    except ForbiddenError as exc:
        raise NotFoundError(f"attachment {attachment_id} not found") from exc
    await service.delete(attachment_id, actor=access.actor)
