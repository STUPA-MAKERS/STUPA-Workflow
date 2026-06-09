"""Flow-API-Router (T-14, api.md »flow«).

* ``GET  /api/applications/{id}/transitions`` — P(application.manage); verfügbare
  Übergänge (Guards geprüft) für den aktuellen Principal.
* ``POST /api/applications/{id}/transition``  — P(application.manage); Übergang feuern
  → 409 bei Guard-Fail/State-Konflikt.

RBAC ist fail-closed (401 ohne Session, 403 ohne Permission). Fehler werden als
``ProblemDetail`` deklariert (problem+json-Contract, T-05/T-10-Hook).
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends

from app.deps import DbSession, require_principal
from app.modules.auth.principal import Principal
from app.modules.flow.dispatch import ActionDispatcher, NullActionDispatcher
from app.modules.flow.schemas import (
    TransitionOut,
    TransitionRequest,
    TransitionResult,
)
from app.modules.flow.service import FlowService
from app.shared.errors import ProblemDetail

router = APIRouter(tags=["flow"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}

# Manuelle Übergänge feuern (#28-Redesign): eigene Permission, getrennt von der
# vollen Antrags-Verwaltung. Akteur-Gates im Guard verfeinern pro Übergang.
MANAGE_PERMISSION = "application.transition"


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def get_action_dispatcher() -> ActionDispatcher:
    """Worker-Dispatcher (Default: No-op/Log; konkrete Queue-Anbindung T-18/19/20/17/15)."""
    return NullActionDispatcher()


def get_flow_service(
    session: DbSession,
    dispatcher: Annotated[ActionDispatcher, Depends(get_action_dispatcher)],
) -> FlowService:
    return FlowService(session, dispatcher)


ServiceDep = Annotated[FlowService, Depends(get_flow_service)]
PrincipalDep = Annotated[Principal, Depends(require_principal(MANAGE_PERMISSION))]


@router.get(
    "/applications/{application_id}/transitions",
    response_model=list[TransitionOut],
    responses=_errors(401, 403, 404),
)
async def list_transitions(
    application_id: UUID,
    service: ServiceDep,
    principal: PrincipalDep,
) -> list[TransitionOut]:
    """Verfügbare Übergänge (Guards für den Principal erfüllt)."""
    return await service.available_transitions(application_id, principal)


@router.post(
    "/applications/{application_id}/transition",
    response_model=TransitionResult,
    # 400 = malformed JSON body (FastAPI-Parser, vor der Validierung) — wie T-12.
    responses=_errors(400, 401, 403, 404, 409, 422),
)
async def fire_transition(
    application_id: UUID,
    payload: TransitionRequest,
    service: ServiceDep,
    principal: PrincipalDep,
) -> TransitionResult:
    """Übergang feuern → 200 ``{newStateId}`` oder 409 (Guard/State-Konflikt)."""
    return await service.fire(
        application_id,
        payload.transition_id,
        principal,
        note=payload.note,
    )
