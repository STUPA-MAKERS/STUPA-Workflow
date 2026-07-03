"""Delegations router.

Member self-service for session-bound representations: list/create/revoke own
delegations, meeting context (deadline/recipients), vote status, and the
per-gremium substitute pool. RBAC is server-side authoritative — every route
requires a session; the domain rules (gates, deadline, recipient circle, chains)
are checked by the service. Admins (``admin.delegations``) see/revoke all;
the pool is managed by ``admin.delegations`` or the gremium role with
``session.manage``. Errors as ``ProblemDetail``.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response

from app.deps import DbSession, Principal, SettingsDep, require_principal
from app.modules.delegations.schemas import (
    DelegationCreate,
    DelegationOut,
    MeetingDelegationContext,
    RecipientOut,
    SubstituteCreate,
    SubstituteOut,
    VoteDelegationStatus,
)
from app.modules.delegations.service import DelegationService
from app.modules.notifications.auto import (
    AutoMailer,
    get_auto_mailer,
    meeting_delegation_mail_info,
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
# Auth is enough (any member may delegate their own vote); the domain
# entitlement (voting member etc.) is checked by the service.
Member = Annotated[Principal, Depends(require_principal())]


@router.get("", response_model=list[DelegationOut], responses=_errors(401))
async def list_delegations(
    service: ServiceDep,
    principal: Member,
    meeting_id: Annotated[UUID | None, Query(alias="meetingId")] = None,
) -> list[DelegationOut]:
    return await service.list(principal, meeting_id)


@router.post(
    "",
    response_model=DelegationOut,
    status_code=201,
    responses=_errors(400, 401, 403, 404, 409, 422),
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
    # Notify the delegate (kind "delegation", user opt-out possible).
    info = await meeting_delegation_mail_info(getattr(service, "session", None), out.id)
    pool = getattr(request.app.state, "arq_pool", None)
    background.add_task(mailer.delegation_changed, settings, info, granted=True, pool=pool)
    return out


@router.delete(
    "/{delegation_id}",
    status_code=204,
    responses=_errors(401, 403, 404, 422),
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
    # Collect mail data BEFORE revoking — the row is gone afterwards.
    info = await meeting_delegation_mail_info(getattr(service, "session", None), delegation_id)
    await service.revoke(delegation_id, principal)
    pool = getattr(request.app.state, "arq_pool", None)
    background.add_task(mailer.delegation_changed, settings, info, granted=False, pool=pool)
    return Response(status_code=204)


@router.get(
    "/meetings/{meeting_id}/context",
    response_model=MeetingDelegationContext,
    responses=_errors(401, 404),
)
async def meeting_context(
    meeting_id: UUID, service: ServiceDep, principal: Member
) -> MeetingDelegationContext:
    """Everything for the "set up representation" dialog (gates, deadline,
    recipients, own status)."""
    return await service.meeting_context(meeting_id, principal)


@router.get(
    "/meetings/{meeting_id}/recipients",
    response_model=list[RecipientOut],
    responses=_errors(401, 404),
)
async def recipients(
    meeting_id: UUID,
    service: ServiceDep,
    principal: Member,
    q: Annotated[str, Query(max_length=100)] = "",
) -> list[RecipientOut]:
    """Typeahead source for recipient selection (members, pool, maybe external)."""
    return await service.recipients(meeting_id, q, principal)


@router.get(
    "/votes/{vote_id}/status",
    response_model=VoteDelegationStatus,
    responses=_errors(401, 404),
)
async def vote_status(
    vote_id: UUID, service: ServiceDep, principal: Member
) -> VoteDelegationStatus:
    """Caller's delegation view of one vote (vote-cast banner)."""
    return await service.vote_status(vote_id, principal)


@router.get(
    "/substitutes",
    response_model=list[SubstituteOut],
    responses=_errors(401, 404),
)
async def list_substitutes(
    service: ServiceDep,
    principal: Member,
    gremium_id: Annotated[UUID, Query(alias="gremiumId")],
) -> list[SubstituteOut]:
    return await service.substitutes_list(gremium_id, principal)


@router.post(
    "/substitutes",
    response_model=SubstituteOut,
    status_code=201,
    responses=_errors(400, 401, 403, 404, 409, 422),
)
async def create_substitute(
    payload: SubstituteCreate, service: ServiceDep, principal: Member
) -> SubstituteOut:
    return await service.substitute_create(payload, principal)


@router.delete(
    "/substitutes/{substitute_id}",
    status_code=204,
    responses=_errors(401, 403, 404),
)
async def delete_substitute(
    substitute_id: UUID, service: ServiceDep, principal: Member
) -> Response:
    await service.substitute_delete(substitute_id, principal)
    return Response(status_code=204)
