"""Flow API router: list available transitions and fire one.

RBAC is fail-closed (401 without session, 403 without permission); errors are
declared as ``ProblemDetail`` (problem+json contract).
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends

from app.deps import DbSession, require_principal
from app.modules.applications.access import Access, require_app_edit, require_app_read
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

# Fire manual transitions: own permission, separate from full application management.
# Per-transition actor gates in the guard refine this.
MANAGE_PERMISSION = "application.transition"


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def get_action_dispatcher() -> ActionDispatcher:
    """Worker dispatcher (default: no-op/log; concrete queue wiring elsewhere)."""
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
    """Available transitions (guards satisfied for the principal)."""
    return await service.available_transitions(application_id, principal)


@router.post(
    "/applications/{application_id}/transition",
    response_model=TransitionResult,
    # 400 = malformed JSON body (FastAPI parser, before validation).
    responses=_errors(400, 401, 403, 404, 409, 422),
)
async def fire_transition(
    application_id: UUID,
    payload: TransitionRequest,
    service: ServiceDep,
    principal: PrincipalDep,
) -> TransitionResult:
    """Fire a transition → 200 ``{newStateId}`` or 409 (guard/state conflict)."""
    return await service.fire(
        application_id,
        payload.transition_id,
        principal,
        note=payload.note,
    )


# --- applicant actions: magic-link (A/P) access to transitions explicitly opened via
# the ``actorIsApplicant`` guard ---
@router.get(
    "/applications/{application_id}/applicant-transitions",
    response_model=list[TransitionOut],
    responses=_errors(401, 403, 404),
)
async def list_applicant_transitions(
    application_id: UUID,
    service: ServiceDep,
    access: Annotated[Access, Depends(require_app_read)],
) -> list[TransitionOut]:
    """Transitions the applicant may fire (only the ``actorIsApplicant`` gate)."""
    return await service.available_applicant_transitions(access.application_id)


@router.post(
    "/applications/{application_id}/applicant-transition",
    response_model=TransitionResult,
    responses=_errors(400, 401, 403, 404, 409, 422),
)
async def fire_applicant_transition(
    application_id: UUID,
    payload: TransitionRequest,
    service: ServiceDep,
    access: Annotated[Access, Depends(require_app_edit)],
) -> TransitionResult:
    """Fire a transition as the applicant — 403 if not opened via ``actorIsApplicant``
    (magic-link/creator, without ``application.manage``)."""
    return await service.fire_as_applicant(
        access.application_id, payload.transition_id, note=payload.note
    )
