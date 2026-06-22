"""files-API-Router (T-13, api.md »files«, security.md §6).

* ``POST /api/applications/{id}/attachments`` — A(edit)/P; Multipart-Upload ≤ 10 MB →
  MIME-Sniff + ClamAV-Scan (async), ``scanned=false`` bis sauber.
* ``GET  /api/attachments/{id}``             — A/P; liefert die app-relative, authz-gated
  ``/download``-Route (kein direkter Bucket-Zugriff, KEINE signierte MinIO-URL — #AUD-055).
  409 solange in Quarantäne, 410 wenn entfernt (Befund).

Fehler werden als ``ProblemDetail`` deklariert (problem+json). Storage/Scan sind optionale
Infra: fehlt MinIO → 503 (Upload), fehlt Redis → Datei bleibt in Quarantäne.
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


async def _resolve_attachment_read(
    db: DbSession,
    application_id: UUID,
    principal: Principal | None,
    applicant: Applicant | None,
) -> Access:
    """Lesezugriff auf den Antrag eines Anhangs — deckt **dieselben** Pfade wie
    :func:`require_app_read` ab (statt nur globalem ``application.read`` via
    ``resolve_access``): ``application.read_all``, ``view``-Antragsteller, eingeloggte:r
    Ersteller:in (#24) **oder** Gremium-Mitglied im Lesescope (#committee-read).

    Spiegelt bewusst die Antrags-Read-Logik, damit ein Antrag, den jemand lesen darf,
    auch dessen Anhänge liefert (keine Verfügbarkeitslücke). Der Cross-Object-404 bleibt
    Sache des Routers (kein Existenz-Orakel)."""
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
    """Anhänge eines Antrags auflisten (Panel-Hydration nach Reload). A/P-Zugriff.

    Eine unbestätigte Gast-Einreichung bleibt für Principals/Gremium unsichtbar (404),
    nur der besitzende Magic-Link-Antragsteller liest sie — spiegelnd zur
    Listen-Semantik (#AUD-032)."""
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
    """Signierte Download-URL. Zugriff via Principal **oder** Antragsteller des Antrags."""
    # Fail-closed **vor** dem DB-Zugriff: ohne Identität 401 (kein 404-vs-401-Orakel,
    # das die Existenz eines Anhangs verraten würde).
    if principal is None and applicant is None:
        raise UnauthorizedError("Authentication required.")
    attachment = await service.get_attachment(attachment_id)
    # Lesezugriff gegen den Antrag des Anhangs prüfen — gleiche Pfade wie require_app_read
    # (read_all/Ersteller/Gremium-Read), nicht nur globales application.read. Cross-Tenant
    # (auth, aber kein Lesezugriff) → bewusst 404 statt 403: ein authentifizierter Fremder
    # soll die Existenz eines Anhangs nicht unterscheiden können (kein Existenz-Orakel).
    try:
        access = await _resolve_attachment_read(
            db, attachment.application_id, principal, applicant
        )
    except ForbiddenError as exc:
        raise NotFoundError(f"attachment {attachment_id} not found") from exc
    # Unbestätigte Gast-Einreichung bleibt für Principals/Gremium unsichtbar (404), nur
    # der besitzende Magic-Link-Antragsteller liest sie — spiegelnd zur Listen-Semantik
    # und zum Antrags-Detail-Gate (#AUD-032).
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
    """Anhang-Bytes server-seitig streamen — MinIO liegt im internen Docker-Netz, eine
    presigned S3-URL bindet den internen Host und ist vom Browser unerreichbar. Über
    nginx ``/api/`` ist dieser Endpunkt erreichbar (gleiches Muster wie der Protokoll-PDF).

    Das Objekt wird CHUNK-WEISE aus dem Storage gestreamt (#AUD-073) — der API-Prozess
    puffert nie die ganze Datei im RAM. ``Content-Length`` aus der gespeicherten Größe.

    Zugriff wie :func:`get_attachment_url` (A/P; Cross-Tenant → 404, kein Existenz-Orakel).
    ``Content-Disposition: attachment`` erzwingt Download statt Inline-Render (security.md §6)."""
    if principal is None and applicant is None:
        raise UnauthorizedError("Authentication required.")
    attachment = await service.get_attachment(attachment_id)
    try:
        access = await _resolve_attachment_read(
            db, attachment.application_id, principal, applicant
        )
    except ForbiddenError as exc:
        raise NotFoundError(f"attachment {attachment_id} not found") from exc
    # Unbestätigte Gast-Einreichung bleibt für Principals/Gremium unsichtbar (404), nur
    # der besitzende Magic-Link-Antragsteller lädt sie — spiegelnd zur Listen-Semantik
    # und zum Antrags-Detail-Gate (#AUD-032). Die Quarantäne-Gates (409/410/503) laufen
    # im Service VOR dem Stream-Start — der StreamingResponse beginnt erst nach den Gates.
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
    """Anhang löschen — Principal (``application.manage`` **oder**
    ``application.edit_any``)/Antragsteller (edit-Scope)/eingeloggte:r Ersteller:in.
    Cross-Tenant → 404 (kein Existenz-Orakel).

    Spiegelt bewusst :func:`require_app_edit` (Upload): ``application.edit_any`` ist ein
    globales Schreibrecht und muss denselben Anhang auch löschen dürfen, sonst wäre RBAC
    inkonsistent (Upload ja, Delete 404) — #AUD-040."""
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
