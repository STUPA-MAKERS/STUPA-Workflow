"""Admin-Router DSGVO/Privacy (``/admin/privacy``, gegated mit ``privacy.manage``).

* ``GET    /admin/privacy/erasures``                 — Löschantrags-Queue.
* ``POST   /admin/privacy/erasures/{id}/execute``    — ausführen (anonymisieren/löschen).
* ``POST   /admin/privacy/erasures/{id}/reject``     — ablehnen (mit Grund).
* ``POST   /admin/privacy/principals/{id}/erase``    — Principal direkt löschen (Art. 17).
* ``GET    /admin/privacy/auskunft``                 — Auskunft (Art. 15) als XLSX.
* ``GET/PUT /admin/privacy/settings``                — globaler Aufbewahrungs-Default.

Benachrichtigungen (erasure_executed/rejected) feuert der Aufrufer best-effort als
Hintergrund-Task (notifications/privacy.py).
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response

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
)
from app.shared.errors import ProblemDetail
from app.shared.xlsx import XLSX_MEDIA_TYPE, build_auskunft_workbook

router = APIRouter(prefix="/admin/privacy", tags=["privacy"])

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
    """FilesService mit dem (optionalen) Object-Storage aus dem App-State — damit die
    Anonymisierung Antrags-Anhänge inkl. Storage-Objekte entfernt."""
    storage = getattr(request.app.state, "object_storage", None)
    return FilesService(session, storage=storage)


ErasureServiceDep = Annotated[ErasureRequestService, Depends(get_erasure_service)]
SettingsServiceDep = Annotated[PrivacySettingsService, Depends(get_settings_service)]


def _out(request_row: Any) -> ErasureRequestOut:
    return ErasureRequestOut.model_validate(request_row, from_attributes=True)


# --------------------------------------------------------------- erasure queue
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


# ------------------------------------------------------------ principal erasure
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


# ------------------------------------------------------------------- settings
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


# ------------------------------------------------------------------- Auskunft
@router.get("/auskunft", dependencies=[_CONFIG], responses=_errors(401, 403))
async def auskunft(
    session: DbSession,
    principal: ConfigPrincipal,
    email: Annotated[str, Query(min_length=1)],
) -> Response:
    """DSGVO Art. 15: alle zu ``email`` gespeicherten personenbezogenen Daten als XLSX.

    Auditiert als ``pii_export`` mit der angefragten E-Mail als ``target_id`` —
    Rechenschaftspflicht (Art. 30): es muss nachvollziehbar bleiben, WESSEN Daten
    exportiert wurden."""
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
            "hasPrincipal": data["principal"] is not None,
        },
    )
    await session.commit()
    return Response(
        content=workbook,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="auskunft.xlsx"'},
    )
