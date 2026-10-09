"""Flow API router: list the available transitions and fire one.

RBAC is fail-closed. A request without a session gets 401. A request without the
permission gets 403. A principal who cannot read the application (`resolve_app_read`)
also gets 403. Every error is declared as `ProblemDetail` (problem+json contract).

An unconfirmed guest application rests in the flow until the magic link confirms it.
Every route here passes `allow_unconfirmed=False` and answers 404 for it.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends

from app.deps import DbSession, require_principal
from app.modules.applications.access import (
    Access,
    require_app_applicant,
    resolve_app_read,
)
from app.modules.applications.decision import not_allowed_problem
from app.modules.applications.schemas import StateOut
from app.modules.auth.principal import Principal
from app.modules.flow.dispatch import ActionDispatcher, NullActionDispatcher
from app.modules.flow.schemas import (
    ForceStatusRequest,
    TransitionOut,
    TransitionRequest,
    TransitionResult,
)
from app.modules.flow.service import FlowService
from app.modules.livevote.publisher import MeetingPublisher, get_meeting_publisher
from app.shared.errors import ProblemDetail

router = APIRouter(tags=["flow"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}

# Fire manual transitions. This permission is separate from full application management.
# The per-transition actor gates in the guard refine it.
MANAGE_PERMISSION = "application.transition"

# Force an application directly into any state. This bypasses guards and transitions.
# It stays separate from application.transition on purpose: it is an audited override.
FORCE_PERMISSION = "application.force_status"


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def get_action_dispatcher() -> ActionDispatcher:
    """Return the flow action dispatcher.

    The default dispatcher only logs. `app.main` overrides this dependency with the
    full chain (`build_worker_dispatcher`). The voting and live-vote routers use the
    same dependency, so the override reaches every route that fires a transition.
    """
    return NullActionDispatcher()


def get_flow_service(
    session: DbSession,
    dispatcher: Annotated[ActionDispatcher, Depends(get_action_dispatcher)],
    # A transition that leaves a vote state cancels its votes. The publisher sends
    # `vote_cancelled` to the live clients of the meeting.
    publisher: Annotated[MeetingPublisher, Depends(get_meeting_publisher)],
) -> FlowService:
    return FlowService(session, dispatcher, publisher)


ServiceDep = Annotated[FlowService, Depends(get_flow_service)]


async def require_transition_principal(
    application_id: UUID,
    db: DbSession,
    principal: Annotated[Principal, Depends(require_principal(MANAGE_PERMISSION))],
) -> Principal:
    """Admit a principal with `application.transition` who can read the application.

    The permission is global. The read check (`resolve_app_read`) limits it to the
    applications that the principal may open: `application.read`, the Gremium read
    scope or the own application. Without the check a holder of the permission lists
    and fires transitions of applications that the holder cannot open. The task list
    (`ListingOps.list_tasks`) applies the same two checks, so a task is always a
    transition that this route accepts.
    """
    await resolve_app_read(db, application_id, principal, None)
    return principal


async def require_force_principal(
    application_id: UUID,
    db: DbSession,
    principal: Annotated[Principal, Depends(require_principal(FORCE_PERMISSION))],
) -> Principal:
    """Admit a principal with `application.force_status` who can read the application."""
    await resolve_app_read(db, application_id, principal, None)
    return principal


PrincipalDep = Annotated[Principal, Depends(require_transition_principal)]
ForcePrincipalDep = Annotated[Principal, Depends(require_force_principal)]


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
    """List the transitions whose guard the principal satisfies."""
    return await service.available_transitions(
        application_id, principal, allow_unconfirmed=False
    )


@router.post(
    "/applications/{application_id}/transition",
    response_model=TransitionResult,
    # 400 means a malformed JSON body. The FastAPI parser raises it before validation.
    responses=_errors(400, 401, 403, 404, 409, 422),
)
async def fire_transition(
    application_id: UUID,
    payload: TransitionRequest,
    service: ServiceDep,
    principal: PrincipalDep,
) -> TransitionResult:
    """Fire a transition: 200 with `{newStateId}`, or 409 on a guard or state conflict.

    With `meetingId` the application goes on the agenda of that meeting in the same
    transaction. The call gives 422 when the transition has no `addToNextSession`
    action, its target is not a vote state, or the meeting is not visible, not
    `planned` or of another Gremium.
    """
    return await service.fire(
        application_id,
        payload.transition_id,
        principal,
        note=payload.note,
        meeting_id=payload.meeting_id,
        non_public=payload.non_public,
        allow_unconfirmed=False,
        decision=payload.decision,
    )


@router.get(
    "/applications/{application_id}/flow-states",
    response_model=list[StateOut],
    responses=_errors(401, 403, 404),
)
async def list_flow_states(
    application_id: UUID,
    service: ServiceDep,
    principal: ForcePrincipalDep,
) -> list[StateOut]:
    """List all states of the application flow. These are the force-status picker options."""
    return await service.list_states(application_id, allow_unconfirmed=False)


@router.post(
    "/applications/{application_id}/force-status",
    response_model=TransitionResult,
    # 400 means a malformed JSON body. The FastAPI parser raises it before validation.
    responses=_errors(400, 401, 403, 404, 409, 422),
)
async def force_status(
    application_id: UUID,
    payload: ForceStatusRequest,
    service: ServiceDep,
    principal: ForcePrincipalDep,
) -> TransitionResult:
    """Force an application directly into `payload.stateId`.

    The route returns 200 with `{newStateId}`. It returns 409 when the application has
    no current state, already sits in the target state, or a concurrent change moved it
    first.
    """
    return await service.force_status(
        application_id,
        payload.state_id,
        principal,
        note=payload.note,
        allow_unconfirmed=False,
    )


@router.get(
    "/applications/{application_id}/applicant-transitions",
    response_model=list[TransitionOut],
    responses=_errors(401, 403, 404),
)
async def list_applicant_transitions(
    application_id: UUID,
    service: ServiceDep,
    access: Annotated[Access, Depends(require_app_applicant)],
) -> list[TransitionOut]:
    """List the transitions the applicant may fire. Only `actorIsApplicant` opens one.

    The route admits the same callers as the fire route: the magic-link applicant and
    the logged-in creator. Another principal gets 403, also with `application.read`,
    so the list never offers an action that the fire route refuses.
    """
    return await service.available_applicant_transitions(
        access.application_id, allow_unconfirmed=False
    )


@router.post(
    "/applications/{application_id}/applicant-transition",
    response_model=TransitionResult,
    responses=_errors(400, 401, 403, 404, 409, 422),
)
async def fire_applicant_transition(
    application_id: UUID,
    payload: TransitionRequest,
    service: ServiceDep,
    access: Annotated[Access, Depends(require_app_applicant)],
) -> TransitionResult:
    """Fire a transition as the applicant.

    The caller is the magic-link holder or the logged-in creator. The creator does
    not need `application.manage`. A principal who is not the creator gets 403, also
    with `application.manage` or `application.edit_any`. A transition that
    `actorIsApplicant` does not open gives 403. The applicant never sets a decision
    (F1): a `decision` gives 422 `decision_not_allowed`.
    """
    if payload.decision is not None:
        raise not_allowed_problem("The applicant cannot set a decision.")
    return await service.fire_as_applicant(
        access.application_id,
        payload.transition_id,
        note=payload.note,
        allow_unconfirmed=False,
    )
