"""Admin privacy router (`/admin/privacy`, gated by `privacy.manage`).

The router serves the erasure-request queue (list, execute, reject), the direct
principal erasure, the direct erasure of an address without an account, the GDPR
access export (XLSX, Art. 15), and the global retention default. It sends the erasure
notifications best-effort as background tasks.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response
from pydantic import EmailStr, TypeAdapter, ValidationError

from app.deps import DbSession, Principal, SettingsDep, require_principal
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.files.service import FilesService
from app.modules.notifications.provider import mail_queue_from_pool
from app.modules.privacy.mails import notify_erasure_executed, notify_erasure_rejected
from app.modules.privacy.models import ErasureRequest
from app.modules.privacy.paperless import (
    Documents,
    documents_of_email,
    documents_of_principal,
    documents_of_requests,
    export_rows,
)
from app.modules.privacy.schemas import (
    EmailErasureBody,
    EmailErasureOut,
    ErasureRejectBody,
    ErasureRequestOut,
    PrincipalErasureOut,
    PrivacySettingsOut,
    PrivacySettingsUpdate,
    TicketMailCountOut,
)
from app.modules.privacy.service import (
    AuskunftService,
    ErasureRequestService,
    PrincipalService,
    PrivacySettingsService,
    build_auskunft_workbook,
    erase_email,
)
from app.modules.tickets.privacy import mail_counts_of, mail_counts_of_principal
from app.shared.errors import ProblemDetail, ValidationProblem
from app.shared.xlsx import XLSX_MEDIA_TYPE

router = APIRouter(prefix="/admin/privacy", tags=["privacy"])

_EMAIL_ADAPTER: TypeAdapter[str] = TypeAdapter(EmailStr)


def _canonical_email(raw: str) -> str:
    """Trim the address, validate it against the RFC, and lowercase it.

    This keeps the `pii_export` audit `target_id` a valid canonical email. It also
    stops a typo from producing a silently empty export.

    Raises:
        ValidationProblem: The value is not a valid email address. The client gets
            a 422 response.
    """
    try:
        return _EMAIL_ADAPTER.validate_python(raw.strip()).lower()
    except ValidationError as exc:
        raise ValidationProblem(
            "email is not a valid e-mail address", code="invalid_email"
        ) from exc


_PROBLEM: dict[str, Any] = {"model": ProblemDetail}
_CONFIG = Depends(require_principal("privacy.manage"))
ConfigPrincipal = Annotated[Principal, Depends(require_principal("privacy.manage"))]


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return dict.fromkeys(codes, _PROBLEM)


def get_erasure_service(session: DbSession) -> ErasureRequestService:
    """Build the erasure-request service."""
    return ErasureRequestService(session)


def get_settings_service(session: DbSession) -> PrivacySettingsService:
    """Build the privacy-settings service."""
    return PrivacySettingsService(session)


def _files_with_storage(session: DbSession, request: Request) -> FilesService:
    """Build a FilesService that uses the object storage of the app state.

    Anonymization then also removes the attachment objects.
    """
    storage = getattr(request.app.state, "object_storage", None)
    return FilesService(session, storage=storage)


ErasureServiceDep = Annotated[ErasureRequestService, Depends(get_erasure_service)]
SettingsServiceDep = Annotated[PrivacySettingsService, Depends(get_settings_service)]


def _out(request_row: ErasureRequest, documents: Documents = ()) -> ErasureRequestOut:
    return ErasureRequestOut.model_validate(request_row, from_attributes=True).model_copy(
        update={"paperless_documents": documents}
    )


@router.get(
    "/erasures",
    response_model=list[ErasureRequestOut],
    dependencies=[_CONFIG],
    responses=_errors(401, 403),
)
async def list_erasures(
    service: ErasureServiceDep,
    session: DbSession,
    status: Annotated[str | None, Query()] = None,
) -> list[ErasureRequestOut]:
    """List the erasure requests, optionally by status, with their Paperless documents."""
    rows = await service.list(status=status)
    documents = await documents_of_requests(session, rows)
    return [_out(r, documents.get(r.id, ())) for r in rows]


@router.post(
    "/erasures/{request_id}/execute",
    response_model=ErasureRequestOut,
    dependencies=[_CONFIG],
    responses=_errors(401, 403, 404, 409),
)
async def execute_erasure(
    request_id: UUID,
    service: ErasureServiceDep,
    principal: ConfigPrincipal,
    session: DbSession,
    request: Request,
    background: BackgroundTasks,
    settings: SettingsDep,
) -> ErasureRequestOut:
    """Execute an erasure request and mail the confirmation in the background."""
    files = _files_with_storage(session, request)
    before = await session.get(ErasureRequest, request_id)
    mails = await mail_counts_of(session, before.email if before is not None else None)
    result = await service.execute(request_id, actor=principal.sub, files=files)
    pool = getattr(request.app.state, "arq_pool", None)
    background.add_task(
        notify_erasure_executed,
        queue=mail_queue_from_pool(pool),
        settings=settings,
        request_id=result.id,
        email=result.email,
        subject_type=result.subject_type,
    )
    documents = await documents_of_requests(session, [result])
    return _out(result, documents.get(result.id, ())).model_copy(
        update={"ticket_mails": TypeAdapter(tuple[TicketMailCountOut, ...]).validate_python(mails)}
    )


@router.post(
    "/erasures/{request_id}/reject",
    response_model=ErasureRequestOut,
    dependencies=[_CONFIG],
    responses=_errors(401, 403, 404, 409),
)
async def reject_erasure(
    request_id: UUID,
    body: ErasureRejectBody,
    service: ErasureServiceDep,
    principal: ConfigPrincipal,
    request: Request,
    background: BackgroundTasks,
    settings: SettingsDep,
) -> ErasureRequestOut:
    """Reject an erasure request and mail the reason in the background."""
    result = await service.reject(request_id, actor=principal.sub, reason=body.reason)
    pool = getattr(request.app.state, "arq_pool", None)
    background.add_task(
        notify_erasure_rejected,
        queue=mail_queue_from_pool(pool),
        settings=settings,
        request_id=result.id,
        email=result.email,
        reason=result.reason,
    )
    return _out(result)


@router.post(
    "/principals/{principal_id}/erase",
    response_model=PrincipalErasureOut,
    dependencies=[_CONFIG],
    responses=_errors(401, 403, 404, 409),
)
async def erase_principal(
    principal_id: UUID,
    principal: ConfigPrincipal,
    session: DbSession,
    request: Request,
) -> PrincipalErasureOut:
    """Erase a principal (GDPR Art. 17) and name the documents that stay in Paperless.

    The route reads the documents before the erasure, because the erasure removes the
    address that finds them.
    """
    documents = await documents_of_principal(session, principal_id)
    mails = await mail_counts_of_principal(session, principal_id)
    await PrincipalService(session).erase(
        principal_id,
        actor=principal.sub,
        files=_files_with_storage(session, request),
    )
    return PrincipalErasureOut.model_validate(
        {"paperlessDocuments": documents, "ticketMails": mails}
    )


@router.post(
    "/erase-email",
    response_model=EmailErasureOut,
    dependencies=[_CONFIG],
    responses=_errors(401, 403, 422),
)
async def erase_by_email(
    body: EmailErasureBody,
    principal: ConfigPrincipal,
    session: DbSession,
    request: Request,
) -> EmailErasureOut:
    """Anonymize the applications and the ticket reports of one address (Art. 17).

    This covers a person without an account, for example the reporter of a ticket
    without a session, who has no application to file an erasure request from. An
    account under the address stays and comes back as ``principalId``.
    """
    email = _canonical_email(body.email)
    documents = await documents_of_email(session, email)
    mails = await mail_counts_of(session, email)
    result = await erase_email(
        session,
        email,
        actor=principal.sub,
        files=_files_with_storage(session, request),
    )
    return EmailErasureOut.model_validate({**result, "ticketMails": mails}).model_copy(
        update={"paperless_documents": documents}
    )


@router.get(
    "/settings",
    response_model=PrivacySettingsOut,
    dependencies=[_CONFIG],
    responses=_errors(401, 403),
)
async def get_settings(service: SettingsServiceDep) -> PrivacySettingsOut:
    """Read the privacy settings."""
    settings = await service.get()
    return PrivacySettingsOut.model_validate(settings, from_attributes=True)


@router.put(
    "/settings",
    response_model=PrivacySettingsOut,
    dependencies=[_CONFIG],
    responses=_errors(401, 403, 422),
)
async def put_settings(
    body: PrivacySettingsUpdate, service: SettingsServiceDep
) -> PrivacySettingsOut:
    """Change the global retention default."""
    settings = await service.update(default_retention_months=body.default_retention_months)
    return PrivacySettingsOut.model_validate(settings, from_attributes=True)


@router.get("/export", dependencies=[_CONFIG], responses=_errors(401, 403, 422))
async def auskunft(
    session: DbSession,
    principal: ConfigPrincipal,
    email: Annotated[str, Query(min_length=1)],
) -> Response:
    """Export all personal data stored for `email` as XLSX (GDPR Art. 15).

    The route writes a `pii_export` audit entry with the canonical email as
    `target_id`. The audit log therefore shows whose data left the platform.
    """
    email = _canonical_email(email)
    data = await AuskunftService(session).collect(email)
    paperless_documents = await export_rows(session, email)
    workbook = build_auskunft_workbook(**data, paperless_documents=paperless_documents)
    await audit_record(
        session,
        actor=principal.sub,
        action=AuditAction.PII_EXPORT,
        target_type="auskunft",
        target_id=email,
        data={
            "email": email,
            "applications": len(data["applications"]),
            "comments": len(data["comments"]),
            "attachments": len(data["attachments"]),
            "attendance": len(data["attendance"]),
            "tickets": len(data["tickets"]),
            "todos": len(data["todos"]),
            "todoComments": len(data["todo_comments"]),
            "appointments": len(data["appointments"]),
            "orders": len(data["orders"]),
            "paperlessDocuments": len(paperless_documents),
            "hasPrincipal": data["principal"] is not None,
        },
    )
    await session.commit()
    return Response(
        content=workbook,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="auskunft.xlsx"'},
    )
