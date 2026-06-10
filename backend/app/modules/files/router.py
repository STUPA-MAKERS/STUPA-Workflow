"""files-API-Router (T-13, api.md »files«, security.md §6).

* ``POST /api/applications/{id}/attachments`` — A(edit)/P; Multipart-Upload ≤ 10 MB →
  MIME-Sniff + ClamAV-Scan (async), ``scanned=false`` bis sauber.
* ``GET  /api/attachments/{id}``             — A/P; kurzlebige signierte MinIO-URL
  (kein direkter Bucket-Zugriff). 409 solange in Quarantäne, 410 wenn entfernt (Befund).

Fehler werden als ``ProblemDetail`` deklariert (problem+json). Storage/Scan sind optionale
Infra: fehlt MinIO → 503 (Upload), fehlt Redis → Datei bleibt in Quarantäne.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status

from app.deps import DbSession, SettingsDep, get_current_applicant, get_current_principal
from app.modules.applications.access import (
    MANAGE_PERMISSION,
    READ_PERMISSION,
    Access,
    _resolve_with_creator,
    require_app_edit,
    require_app_read,
    resolve_access,
)
from app.modules.auth.principal import Applicant, Principal
from app.modules.files.queue import scan_queue_from_pool
from app.modules.files.schemas import AttachmentOut, SignedUrlOut
from app.modules.files.service import FilesService
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
    """Service mit dem (optionalen) Storage + Scan-Queue aus dem App-State verdrahten."""
    storage = getattr(request.app.state, "object_storage", None)
    pool = getattr(request.app.state, "arq_pool", None)
    return FilesService(
        session,
        storage=storage,
        queue=scan_queue_from_pool(pool),
        settings=settings,
    )


ServiceDep = Annotated[FilesService, Depends(get_files_service)]


async def _read_capped(file: UploadFile, max_bytes: int) -> bytes:
    """Upload gekappt streamen: > ``max_bytes`` → 413 (nicht den ganzen Body puffern)."""
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
    # 401/403 Auth, 404 Antrag fehlt, 413 zu groß, 415 Typ/Sniff, 429 Rate-Limit,
    # 503 Storage aus.
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
    """Anhang hochladen. Liegt ``scanned=false`` bis der Worker ClamAV durch hat."""
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
    """Anhänge eines Antrags auflisten (Panel-Hydration nach Reload). A/P-Zugriff."""
    return await service.list_for_application(access.application_id)


@router.get(
    "/attachments/{attachment_id}",
    response_model=SignedUrlOut,
    responses=_errors(401, 404, 409, 410, 503),
)
async def get_attachment_url(
    attachment_id: UUID,
    service: ServiceDep,
    principal: Annotated[Principal | None, Depends(get_current_principal)],
    applicant: Annotated[Applicant | None, Depends(get_current_applicant)],
) -> SignedUrlOut:
    """Signierte Download-URL. Zugriff via Principal **oder** Antragsteller des Antrags."""
    # Fail-closed **vor** dem DB-Zugriff: ohne Identität 401 (kein 404-vs-401-Orakel,
    # das die Existenz eines Anhangs verraten würde).
    if principal is None and applicant is None:
        raise UnauthorizedError("Authentication required.")
    attachment = await service.get_attachment(attachment_id)
    # A/P-Zugriff gegen den Antrag des Anhangs prüfen. Cross-Tenant (auth, aber fremder
    # Antrag) → bewusst 404 statt 403: ein authentifizierter Fremder soll die Existenz
    # eines Anhangs nicht unterscheiden können (kein Existenz-Orakel). view-Scope genügt.
    try:
        resolve_access(
            attachment.application_id,
            principal,
            applicant,
            perm=READ_PERMISSION,
            scope="view",
        )
    except ForbiddenError as exc:
        raise NotFoundError(f"attachment {attachment_id} not found") from exc
    return await service.signed_url(attachment_id)


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
    """Anhang löschen — Principal (``application.manage``)/Antragsteller (edit-Scope)/
    eingeloggte:r Ersteller:in. Cross-Tenant → 404 (kein Existenz-Orakel)."""
    if principal is None and applicant is None:
        raise UnauthorizedError("Authentication required.")
    attachment = await service.get_attachment(attachment_id)
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
