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

from fastapi import APIRouter, Depends, Response

from app.deps import DbSession, Principal, SettingsDep, require_principal
from app.modules.delegations.schemas import DelegationCreate, DelegationOut
from app.modules.delegations.service import DelegationService
from app.shared.errors import ProblemDetail

router = APIRouter(prefix="/delegations", tags=["delegations"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def get_delegation_service(session: DbSession, settings: SettingsDep) -> DelegationService:
    return DelegationService(session, settings)


ServiceDep = Annotated[DelegationService, Depends(get_delegation_service)]
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
    payload: DelegationCreate, service: ServiceDep, principal: Member
) -> DelegationOut:
    return await service.create(payload, principal)


@router.delete(
    "/{delegation_id}",
    status_code=204,
    responses=_errors(401, 403, 404),
)
async def revoke_delegation(
    delegation_id: UUID, service: ServiceDep, principal: Member
) -> Response:
    await service.revoke(delegation_id, principal)
    return Response(status_code=204)
