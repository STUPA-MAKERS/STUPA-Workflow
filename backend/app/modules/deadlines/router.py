"""Admin-Router der Deadline-Policy-Registry (benannte Fristen).

CRUD unter ``/admin/deadline-policies``, gegated mit ``admin.types`` (autoritativ, #6).
Der Flow referenziert eine Policy über ``key``; das Datum (z. B. pro Semester) lässt
sich hier pflegen, **ohne** den Flow neu zu versionieren.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.deps import DbSession, Principal, require_any_permission, require_principal
from app.modules.deadlines.schemas import (
    DeadlinePolicyCreate,
    DeadlinePolicyOut,
    DeadlinePolicyUpdate,
)
from app.modules.deadlines.service import DeadlinePolicyError, DeadlinePolicyService
from app.shared.errors import ConflictError, NotFoundError, ProblemDetail

router = APIRouter(prefix="/admin/deadline-policies", tags=["deadlines"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}
# Frist-Policies gehören zur Typ-/Flow-Konfiguration (#6: admin.types).
_CONFIG = Depends(require_principal("admin.types"))
# Lesen auch für den Flow-Editor (flow.configure) erlaubt — er braucht die Policies
# als Auswahl für Fristen-Guards/Aktionen (#5-2). Schreiben bleibt admin.types.
_CONFIG_READ = Depends(require_any_permission("admin.types", "flow.configure"))


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def get_service(session: DbSession) -> DeadlinePolicyService:
    return DeadlinePolicyService(session)


ServiceDep = Annotated[DeadlinePolicyService, Depends(get_service)]
ConfigAdmin = Annotated[Principal, Depends(require_principal("admin.types"))]


@router.get("", response_model=list[DeadlinePolicyOut], dependencies=[_CONFIG_READ])
async def list_policies(service: ServiceDep) -> list[DeadlinePolicyOut]:
    return [DeadlinePolicyOut.model_validate(p, from_attributes=True) for p in await service.list()]


@router.post(
    "",
    response_model=DeadlinePolicyOut,
    status_code=201,
    dependencies=[_CONFIG],
    responses=_errors(401, 403, 409, 422),
)
async def create_policy(
    body: DeadlinePolicyCreate, service: ServiceDep
) -> DeadlinePolicyOut:
    try:
        policy = await service.create(
            key=body.key,
            label=body.label,
            kind=body.kind,
            absolute_at=body.absolute_at,
            offset_days=body.offset_days,
        )
    except DeadlinePolicyError as exc:
        raise ConflictError(str(exc), code="deadline_policy_key") from exc
    return DeadlinePolicyOut.model_validate(policy, from_attributes=True)


@router.patch(
    "/{policy_id}",
    response_model=DeadlinePolicyOut,
    dependencies=[_CONFIG],
    responses=_errors(401, 403, 404, 422),
)
async def update_policy(
    policy_id: UUID, body: DeadlinePolicyUpdate, service: ServiceDep
) -> DeadlinePolicyOut:
    policy = await service.get(policy_id)
    if policy is None:
        raise NotFoundError(f"deadline policy {policy_id} not found")
    updated = await service.update(
        policy,
        label=body.label,
        kind=body.kind,
        absolute_at=body.absolute_at,
        offset_days=body.offset_days,
    )
    return DeadlinePolicyOut.model_validate(updated, from_attributes=True)


@router.delete(
    "/{policy_id}",
    status_code=204,
    dependencies=[_CONFIG],
    responses=_errors(401, 403, 404),
)
async def delete_policy(policy_id: UUID, service: ServiceDep) -> Response:
    policy = await service.get(policy_id)
    if policy is None:
        raise NotFoundError(f"deadline policy {policy_id} not found")
    await service.delete(policy)
    return Response(status_code=204)
