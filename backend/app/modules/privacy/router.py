"""Admin privacy router (`/admin/privacy`, gated by `privacy.manage`).

The router serves the erasure-request queue (list, execute, reject), the direct
principal erasure, the GDPR access export (XLSX, Art. 15), and the global retention
default. It sends the erasure notifications best-effort as background tasks.
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
from app.modules.notifications.privacy import (
    notify_erasure_executed,
    notify_erasure_rejected,
)
from app.modules.notifications.provider import mail_queue_from_pool
from app.modules.privacy.schemas import (
    ErasureRejectBody,
    ErasureRequestOut,
    PrivacySettingsOut,
    PrivacySettingsUpdate,
)
from app.modules.privacy.service import (
    AuskunftService,
    ErasureRequestService,
    PrincipalService,
    PrivacySettingsService,
    build_auskunft_workbook,
)
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
    return {code: _PROBLEM for code in codes}


def get_erasure_service(session: DbSession) -> ErasureRequestService:
    return ErasureRequestService(session)


def get_settings_service(session: DbSession) -> PrivacySettingsService:
    return PrivacySettingsService(session)


def _files_with_storage(session: DbSession, request: Request) -> FilesService:
    """Build a FilesService that uses the object storage of the app state.

    Anonymization then also removes the attachment objects.
    """
    storage = getattr(request.app.state, "object_storage", None)
    return FilesService(session, storage=storage)


ErasureServiceDep = Annotated[ErasureRequestService, Depends(get_erasure_service)]
SettingsServiceDep = Annotated[PrivacySettingsService, Depends(get_settings_service)]


def _out(request_row: Any) -> ErasureRequestOut:
    return ErasureRequestOut.model_validate(request_row, from_attributes=True)


@router.get(
    "/erasures",
    response_model=list[ErasureRequestOut],
    dependencies=[_CONFIG],
    responses=_errors(401, 403),
)
async def list_erasures(
    service: ErasureServiceDep,
    status: Annotated[str | None, Query()] = None,
) -> list[ErasureRequestOut]:
    return [_out(r) for r in await service.list(status=status)]


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
    files = _files_with_storage(session, request)
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
    return _out(result)


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
    status_code=204,
    dependencies=[_CONFIG],
    responses=_errors(401, 403, 404),
)
async def erase_principal(
    principal_id: UUID,
    principal: ConfigPrincipal,
    session: DbSession,
) -> Response:
    await PrincipalService(session).erase(principal_id, actor=principal.sub)
    return Response(status_code=204)


@router.get(
    "/settings",
    response_model=PrivacySettingsOut,
    dependencies=[_CONFIG],
    responses=_errors(401, 403),
)
async def get_settings(service: SettingsServiceDep) -> PrivacySettingsOut:
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
    settings = await service.update(
        default_retention_months=body.default_retention_months
    )
    return PrivacySettingsOut.model_validate(settings, from_attributes=True)


@router.get("/auskunft", dependencies=[_CONFIG], responses=_errors(401, 403, 422))
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
    workbook = build_auskunft_workbook(**data)
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
            "hasPrincipal": data["principal"] is not None,
        },
    )
    await session.commit()
    return Response(
        content=workbook,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="auskunft.xlsx"'},
    )
