"""Files API router.

``POST /api/applications/{id}/attachments`` takes a multipart upload of at most 10 MB.
Access is A(edit)/P. The route sniffs the MIME type and enqueues the ClamAV scan.
``scanned`` stays false until the scan reports clean.

``GET /api/attachments/{id}`` returns the app-relative ``/download`` route that the
authorization layer gates. Access is A/P. There is no direct bucket access and no signed
MinIO URL. The route answers 409 while the file is quarantined and 410 after a finding
removed it.

The routes declare their errors as ``ProblemDetail`` (problem+json). Storage and scan are
optional infrastructure. Without MinIO an upload gives 503. Without Redis the file stays
quarantined.
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

# Types the browser may render inline in the attachment preview. This is the upload
# allowlist without anything scriptable. HTML and SVG never appear here, so there is no
# stored-XSS vector.
_INLINE_MIMES = frozenset({"application/pdf", "image/png", "image/jpeg"})


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def get_files_service(
    session: DbSession, request: Request, settings: SettingsDep
) -> FilesService:
    """Wire the service with the optional storage and scan queue from the app state."""
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
    """Resolve read access to the application of an attachment.

    The check covers the same paths as ``require_app_read``, not only the global
    ``application.read`` permission through ``resolve_access``. The accepted paths are
    ``application.read_all``, an applicant with ``view`` scope, the logged-in creator,
    and a member of the Gremium in read scope.

    This mirrors the application read logic on purpose. An application that a caller may
    read must also yield its attachments, so there is no availability gap. The router
    still maps a cross-object miss to 404, so the API is no existence oracle.
    """
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
    """Read the upload in chunks with a size cap.

    The function stops as soon as the body passes the cap. It never buffers a body that
    is larger than ``max_bytes``.

    Raises:
        PayloadTooLargeError: The body is larger than ``max_bytes`` (HTTP 413).
    """
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
    # 401/403 auth, 404 application missing, 413 too large, 415 bad type or sniff,
    # 429 rate limit, 503 storage off.
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
    """Upload an attachment.

    The attachment stays at ``scanned=false`` until the worker finishes the ClamAV scan.
    """
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
    """List the attachments of an application.

    The frontend uses this route to fill the panel again after a reload. Access is A/P.

    An unconfirmed guest submission stays invisible to a principal or a member of the
    Gremium and gives 404. Only the owning magic-link applicant reads it. This mirrors
    the list semantics.
    """
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
    """Return the download URL of an attachment.

    A principal or the applicant of the application may call this route.
    """
    # Fail closed before the database access. Without an identity the route answers 401.
    # A difference between 404 and 401 would reveal that the attachment exists.
    if principal is None and applicant is None:
        raise UnauthorizedError("Authentication required.")
    attachment = await service.get_attachment(attachment_id)
    # Check read access against the application of the attachment. This uses the same
    # paths as in require_app_read, that is read_all, creator and Gremium read, not only
    # the global application.read permission. A cross-tenant caller is authenticated but
    # has no read access. It gets 404 instead of 403, so an outsider cannot learn that
    # the attachment exists.
    try:
        access = await _resolve_attachment_read(
            db, attachment.application_id, principal, applicant
        )
    except ForbiddenError as exc:
        raise NotFoundError(f"attachment {attachment_id} not found") from exc
    # An unconfirmed guest submission stays invisible to a principal or a member of the
    # Gremium and gives 404. Only the owning magic-link applicant reads it. This mirrors
    # the list and detail gates.
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
    inline: bool = False,
) -> StreamingResponse:
    """Stream the bytes of an attachment from the server.

    MinIO runs on the internal Docker network. A presigned S3 URL binds the internal host
    into the signature, so the browser cannot reach it. The browser reaches this endpoint
    through nginx under ``/api/``. The protocol PDF uses the same pattern.

    The route reads the object from storage chunk by chunk. The API process never buffers
    the whole file in RAM. ``Content-Length`` comes from the stored size.

    Access works like in ``get_attachment_url``: A/P, and a cross-tenant caller gets 404,
    so the API is no existence oracle. ``Content-Disposition: attachment`` forces a
    download instead of an inline render.
    """
    if principal is None and applicant is None:
        raise UnauthorizedError("Authentication required.")
    attachment = await service.get_attachment(attachment_id)
    try:
        access = await _resolve_attachment_read(
            db, attachment.application_id, principal, applicant
        )
    except ForbiddenError as exc:
        raise NotFoundError(f"attachment {attachment_id} not found") from exc
    # An unconfirmed guest submission stays invisible to a principal or a member of the
    # Gremium and gives 404. Only the owning magic-link applicant downloads it. This
    # mirrors the list and detail gates. The quarantine gates (409/410/503) run in the
    # service BEFORE the stream starts. The StreamingResponse begins after those gates.
    stream, filename, mime, size = await service.download_stream(
        attachment_id, allow_unconfirmed=access.is_owning_applicant
    )
    # ``?inline=1`` renders the file in the browser preview dialog. This works only for
    # the non-scriptable allowlist. Anything else stays a forced download.
    kind = "inline" if inline and mime in _INLINE_MIMES else "attachment"
    disposition = f'{kind}; filename="{_safe_disposition(filename)}"'
    return StreamingResponse(
        stream,
        media_type=mime,
        headers={
            "Content-Disposition": disposition,
            "Content-Length": str(size),
            "X-Content-Type-Options": "nosniff",
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
    """Delete an attachment.

    A principal with ``application.manage`` or ``application.edit_any`` may delete it. An
    applicant with edit scope and the logged-in creator may delete it too. A cross-tenant
    caller gets 404, so the API is no existence oracle.

    This mirrors ``require_app_edit`` on the upload route on purpose.
    ``application.edit_any`` is a global write permission. It must also delete the same
    attachment. Otherwise RBAC would be inconsistent: upload allowed, delete 404.
    """
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
