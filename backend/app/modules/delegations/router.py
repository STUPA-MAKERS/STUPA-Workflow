"""Delegations-Router (T-45, R1.5).

Mitglied-Self-Service: ``GET`` eigene Delegationen, ``POST`` anlegen, ``DELETE``
widerrufen. RBAC ist serverseitig **autoritativ** — jede Route verlangt eine Session
(``require_principal`` → 401); *welche* Rolle delegiert werden darf, prüft der Service
(nur selbst gehaltene Rollen, sonst 403). Admins (``admin.roles``) sehen/widerrufen
alle Delegationen. Fehler werden als ``ProblemDetail`` deklariert (problem+json).
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response

from app.deps import DbSession, Principal, SettingsDep, require_principal
from app.modules.delegations.schemas import DelegationCreate, DelegationOut
from app.modules.delegations.service import DelegationService
from app.modules.notifications.auto import (
    AutoMailer,
    assignment_mail_info,
    get_auto_mailer,
)
from app.shared.errors import ProblemDetail

router = APIRouter(prefix="/delegations", tags=["delegations"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def get_delegation_service(session: DbSession, settings: SettingsDep) -> DelegationService:
    return DelegationService(session, settings)


ServiceDep = Annotated[DelegationService, Depends(get_delegation_service)]
AutoMailerDep = Annotated[AutoMailer, Depends(get_auto_mailer)]
# Auth genügt (jedes Mitglied darf eigene Rechte delegieren); Rollen-Besitz prüft der Service.
Member = Annotated[Principal, Depends(require_principal())]


@router.get("", response_model=list[DelegationOut], responses=_errors(401))
async def list_delegations(service: ServiceDep, principal: Member) -> list[DelegationOut]:
    return await service.list(principal)


@router.post(
    "",
    response_model=DelegationOut,
    status_code=201,
    responses=_errors(400, 401, 403, 404, 422),
)
async def create_delegation(
    payload: DelegationCreate,
    service: ServiceDep,
    principal: Member,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
    mailer: AutoMailerDep,
) -> DelegationOut:
    out = await service.create(payload, principal)
    # Delegat informieren (#4-3, Art delegation, abwählbar #4-2).
    info = await assignment_mail_info(getattr(service, "session", None), out.id)
    pool = getattr(request.app.state, "arq_pool", None)
    background.add_task(
        mailer.assignment_changed, settings, info, granted=True, pool=pool
    )
    return out


@router.delete(
    "/{delegation_id}",
    status_code=204,
    responses=_errors(401, 403, 404),
)
async def revoke_delegation(
    delegation_id: UUID,
    service: ServiceDep,
    principal: Member,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
    mailer: AutoMailerDep,
) -> Response:
    # Mail-Daten VOR dem Widerruf einsammeln (#4-3) — danach ist die Zeile weg.
    info = await assignment_mail_info(getattr(service, "session", None), delegation_id)
    await service.revoke(delegation_id, principal)
    pool = getattr(request.app.state, "arq_pool", None)
    background.add_task(
        mailer.assignment_changed, settings, info, granted=False, pool=pool
    )
    return Response(status_code=204)
