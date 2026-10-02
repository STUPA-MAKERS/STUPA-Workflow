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

from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import DbSession, SettingsDep, get_current_applicant, get_current_principal
from app.modules.applications.access import (
    EDIT_ANY_PERMISSION,
    MANAGE_PERMISSION,
    Access,
    _resolve_with_creator,
    hidden_pii_keys,
    require_app_edit,
    require_app_read,
    resolve_app_read,
)
from app.modules.applications.models import Application
from app.modules.auth.principal import Applicant, Principal
from app.modules.files.drafts import DraftAttachments, invalid_token
from app.modules.files.models import Attachment
from app.modules.files.queue import scan_queue_from_pool
from app.modules.files.schemas import AttachmentOut, DraftAttachmentOut, SignedUrlOut
from app.modules.files.service import FilesService, application_id_of
from app.modules.files.storage import _safe_disposition
from app.shared.altcha import AltchaError, AltchaVerifier, NullAltchaVerifier
from app.shared.antiabuse import (
    enforce_attachment_body_cap,
    get_altcha_verifier,
    rate_limit_attachments,
)
from app.shared.errors import (
    BadRequestError,
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


def get_draft_attachments(service: ServiceDep) -> DraftAttachments:
    """Wire the draft operations (Z4) on top of the files service."""
    return DraftAttachments(service)


DraftsDep = Annotated[DraftAttachments, Depends(get_draft_attachments)]


async def _resolve_attachment_read(
    db: DbSession,
    application_id: UUID,
    principal: Principal | None,
    applicant: Applicant | None,
) -> Access:
    """Resolve read access to the application of an attachment.

    The check is `resolve_app_read`, the same as ``require_app_read``, not only the
    global ``application.read`` permission through ``resolve_access``. The accepted
    paths are ``application.read_all``, an applicant with ``view`` scope, a member of
    the Gremium in read scope, and the logged-in creator.

    An application that a caller may read must also yield its attachments, so there is
    no availability gap. The router still maps a cross-object miss to 404, so the API
    is no existence oracle.
    """
    return await resolve_app_read(db, application_id, principal, applicant)


async def _pii_attachment_filter(
    db: AsyncSession, access: Access
) -> Callable[[Attachment], bool] | None:
    """Return a test for the attachments of the ``isPII`` fields (O21).

    The result is ``None`` when the caller reads the ``isPII`` fields (`can_read_pii`).
    Otherwise the test is true for an attachment that belongs to an ``isPII`` field. An
    attachment belongs to a field when its ``field_key`` names the field, or when the
    answer of the field refers to the attachment id. The detail view removes the same
    fields from ``data``, so the file is not available one call away.
    """
    keys = await hidden_pii_keys(db, access)
    if not keys:
        return None
    data = await db.scalar(select(Application.data).where(Application.id == access.application_id))
    refs: set[str] = set()
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, str):
                refs.add(value)
            elif isinstance(value, list):
                refs.update(v for v in value if isinstance(v, str))

    def hidden(attachment: Attachment) -> bool:
        return attachment.field_key in keys or str(attachment.id) in refs

    return hidden


async def _assert_not_pii_hidden(db: AsyncSession, access: Access, attachment: Attachment) -> None:
    """Answer 404 for an attachment of an ``isPII`` field that the caller may not read.

    A 404 and not a 403, so the route is no existence oracle (O21).

    Raises:
        NotFoundError: The attachment belongs to an ``isPII`` field and the caller
            does not read the ``isPII`` fields (HTTP 404).
    """
    hidden = await _pii_attachment_filter(db, access)
    if hidden is not None and hidden(attachment):
        raise NotFoundError(f"attachment {attachment.id} not found")


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
    dependencies=[Depends(enforce_attachment_body_cap), Depends(rate_limit_attachments)],
    # 401/403 auth, 404 application missing, 413 too large, 415 bad type or sniff,
    # 429 rate limit, 503 storage off.
    responses=_errors(401, 403, 404, 413, 415, 429, 503),
)
async def upload_attachment(
    application_id: UUID,
    service: ServiceDep,
    access: Annotated[Access, Depends(require_app_edit)],
    file: Annotated[UploadFile, File()],
    field_key: Annotated[str | None, Form(max_length=256)] = None,
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
    db: DbSession,
    access: Annotated[Access, Depends(require_app_read)],
) -> list[AttachmentOut]:
    """List the attachments of an application.

    The frontend uses this route to fill the panel again after a reload. Access is A/P.

    A caller without the PII right (`can_read_pii`) does not see the attachments of the
    ``isPII`` fields (O21).

    An unconfirmed guest submission stays invisible to a principal or a member of the
    Gremium and gives 404. Only the owning magic-link applicant reads it. This mirrors
    the list semantics.
    """
    return await service.list_for_application(
        access.application_id,
        allow_unconfirmed=access.is_owning_applicant,
        hidden=await _pii_attachment_filter(db, access),
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
            db, application_id_of(attachment), principal, applicant
        )
    except ForbiddenError as exc:
        raise NotFoundError(f"attachment {attachment_id} not found") from exc
    await _assert_not_pii_hidden(db, access, attachment)
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
            db, application_id_of(attachment), principal, applicant
        )
    except ForbiddenError as exc:
        raise NotFoundError(f"attachment {attachment_id} not found") from exc
    await _assert_not_pii_hidden(db, access, attachment)
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
    # 409: an applicant or a creator deletes in a locked state.
    responses=_errors(401, 403, 404, 409),
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

    A delete is a data change, not an upload. An applicant and a creator without
    ``application.manage`` can delete only while the current state has
    ``edit_allowed``. In a locked state they get 409, as for a PATCH. They can still
    upload in every state (Z1, O4). ``application.manage`` and
    ``application.edit_any`` keep the bypass.
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
            application_id_of(attachment),
            principal,
            applicant,
            perm=MANAGE_PERMISSION,
            scope="edit",
        )
    except ForbiddenError as exc:
        raise NotFoundError(f"attachment {attachment_id} not found") from exc
    if access.principal is None or not access.principal.has(MANAGE_PERMISSION):
        await service.assert_editable(application_id_of(attachment))
    await service.delete(attachment_id, actor=access.actor)


# Header of the draft token on ``POST`` and ``DELETE /apply/attachments`` (Z4). A header
# keeps the token out of the URL and out of the access log.
DRAFT_TOKEN_HEADER = "X-Draft-Token"


@router.post(
    "/apply/attachments",
    response_model=DraftAttachmentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_attachment_body_cap), Depends(rate_limit_attachments)],
    # 400 ALTCHA, 413 file or draft too large, 415 bad type or sniff, 422 unknown or
    # expired token, 429 rate limit, 503 storage off.
    responses=_errors(400, 413, 415, 422, 429, 503),
)
async def upload_draft_attachment(
    drafts: DraftsDep,
    verifier: Annotated[
        AltchaVerifier | NullAltchaVerifier, Depends(get_altcha_verifier)
    ],
    principal: Annotated[Principal | None, Depends(get_current_principal)],
    file: Annotated[UploadFile, File()],
    field_key: Annotated[str | None, Form(max_length=256)] = None,
    is_comparison_offer: Annotated[bool, Form()] = False,
    altcha: Annotated[str | None, Form(max_length=4096)] = None,
    draft_token: Annotated[
        str | None, Header(alias=DRAFT_TOKEN_HEADER, max_length=128)
    ] = None,
) -> DraftAttachmentOut:
    """Upload a file of the wizard before the application exists (Z4).

    The route is public. The first upload of a draft has no ``X-Draft-Token``
    header. An anonymous caller then sends an ALTCHA solution in the multipart field
    ``altcha``; a logged-in principal needs none. The response carries the new
    ``draftToken``. Each later upload of the same draft sends the token in the
    header and needs no ALTCHA. The route checks such a token before it reads the
    file, so an unknown or expired token costs no read and no sniff and gives 422 at
    once. The token and its drafts live ``attachment_draft_ttl_days`` after the last
    upload. The token stays valid when the owner deletes all its drafts. One token
    holds at most ``attachment_draft_max_files`` files and
    ``attachment_draft_max_bytes`` bytes.

    Size cap, rate limit and MIME sniff work as on the application upload. The file
    stays quarantined until the scan is clean. ``POST /applications`` binds the
    drafts with ``attachmentIds`` and ``draftToken``.
    """
    if draft_token is not None:
        if not await drafts.token_is_valid(draft_token):
            raise invalid_token()
    elif principal is None:
        try:
            await verifier.verify(altcha)
        except AltchaError as exc:
            raise BadRequestError(
                "Altcha verification failed.", code="altcha_failed"
            ) from exc
    data = await _read_capped(file, drafts.files.max_bytes)
    return await drafts.upload(
        token=draft_token,
        filename=file.filename,
        data=data,
        by=principal.sub if principal is not None else "applicant",
        field_key=field_key,
        is_comparison_offer=is_comparison_offer,
    )


@router.delete(
    "/apply/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    # 404: the token owns no draft with this id. 422: the header is missing.
    responses=_errors(404, 422),
)
async def delete_draft_attachment(
    attachment_id: UUID,
    drafts: DraftsDep,
    principal: Annotated[Principal | None, Depends(get_current_principal)],
    draft_token: Annotated[str, Header(alias=DRAFT_TOKEN_HEADER, max_length=128)],
) -> None:
    """Remove a draft file of the wizard (Z4).

    The ``X-Draft-Token`` header must name the token that owns the draft. Any other
    case gives 404, so the route is no existence oracle. A bound attachment is out of
    reach here; ``DELETE /attachments/{id}`` handles it.
    """
    await drafts.delete(
        attachment_id,
        token=draft_token,
        actor=principal.sub if principal is not None else "applicant",
    )
