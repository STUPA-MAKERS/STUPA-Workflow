"""Delegations-Router (#delegation-rework).

Mitglied-Self-Service für **sitzungsgebundene** Vertretungen: ``GET`` eigene
Delegationen, ``POST`` anlegen, ``DELETE`` widerrufen, plus Sitzungs-Kontext
(Deadline/Empfänger), Vote-Status (FE-Banner) und der pro Gremium gepflegte
Stellvertreter-Pool. RBAC ist serverseitig **autoritativ** — jede Route verlangt
eine Session (``require_principal`` → 401); die fachlichen Regeln (Gates,
Deadline, Empfänger-Kreis, Ketten) prüft der Service. Admins (``admin.roles``)
sehen/widerrufen alle Delegationen; den Pool pflegt ``admin.roles`` oder die
Gremium-Rolle mit ``session.manage``. Fehler als ``ProblemDetail``.
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
# Auth genügt (jedes Mitglied darf die eigene Stimme delegieren); die fachliche
# Berechtigung (stimmberechtigtes Mitglied etc.) prüft der Service.
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
    # Vertreter:in informieren (#4-3, Art delegation, abwählbar #4-2).
    info = await meeting_delegation_mail_info(
        getattr(service, "session", None), out.id
    )
    pool = getattr(request.app.state, "arq_pool", None)
    background.add_task(
        mailer.delegation_changed, settings, info, granted=True, pool=pool
    )
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
    # Mail-Daten VOR dem Widerruf einsammeln (#4-3) — danach ist die Zeile weg.
    info = await meeting_delegation_mail_info(
        getattr(service, "session", None), delegation_id
    )
    await service.revoke(delegation_id, principal)
    pool = getattr(request.app.state, "arq_pool", None)
    background.add_task(
        mailer.delegation_changed, settings, info, granted=False, pool=pool
    )
    return Response(status_code=204)


@router.get(
    "/meetings/{meeting_id}/context",
    response_model=MeetingDelegationContext,
    responses=_errors(401, 404),
)
async def meeting_context(
    meeting_id: UUID, service: ServiceDep, principal: Member
) -> MeetingDelegationContext:
    """Alles für den »Vertretung einrichten«-Dialog (Gates, Deadline, Empfänger,
    eigener Status)."""
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
    """Typeahead-Quelle für die Empfänger-Wahl (Mitglieder, Pool, ggf. extern)."""
    return await service.recipients(meeting_id, q, principal)


@router.get(
    "/votes/{vote_id}/status",
    response_model=VoteDelegationStatus,
    responses=_errors(401, 404),
)
async def vote_status(
    vote_id: UUID, service: ServiceDep, principal: Member
) -> VoteDelegationStatus:
    """Delegations-Sicht des Aufrufers auf eine Abstimmung (vote-cast-Banner)."""
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
