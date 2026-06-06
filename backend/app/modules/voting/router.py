"""Voting-API-Router (T-15, api.md »voting«).

* ``POST /api/applications/{id}/votes`` — P(vote.manage); Abstimmung anlegen.
* ``POST /api/votes/{id}/open``         — P(vote.manage); öffnen.
* ``POST /api/votes/{id}/close``        — P(vote.manage); schließen → Ergebnis → Flow.
* ``POST /api/votes/{id}/ballot``       — P(vote.cast)+Gruppe; Stimme abgeben.
* ``GET  /api/votes/{id}``              — P; Vote-State + Tally (secret: nur counts).

RBAC ist fail-closed: 401 ohne Session, 403 ohne Permission bzw. ohne Gruppen-
Mitgliedschaft (``cast``). Die Gruppe steht am Vote (dynamisch) → die Prüfung passiert
im Service nach dem Laden. Fehler werden als ``ProblemDetail`` deklariert (problem+json).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends

from app.deps import DbSession, require_principal
from app.modules.auth.principal import Principal
from app.modules.flow.dispatch import ActionDispatcher, NullActionDispatcher
from app.modules.voting.schemas import (
    BallotAccepted,
    BallotIn,
    VoteClosed,
    VoteCreate,
    VoteOut,
)
from app.modules.voting.service import VotingService
from app.shared.errors import ProblemDetail

router = APIRouter(tags=["voting"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}

MANAGE_PERMISSION = "vote.manage"
CAST_PERMISSION = "vote.cast"


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def get_action_dispatcher() -> ActionDispatcher:
    """Worker-Dispatcher für die Flow-Actions beim Close (Default: No-op/Log)."""
    return NullActionDispatcher()


def get_voting_service(
    session: DbSession,
    dispatcher: Annotated[ActionDispatcher, Depends(get_action_dispatcher)],
) -> VotingService:
    return VotingService(session, dispatcher)


ServiceDep = Annotated[VotingService, Depends(get_voting_service)]
ManagerDep = Annotated[Principal, Depends(require_principal(MANAGE_PERMISSION))]
VoterDep = Annotated[Principal, Depends(require_principal(CAST_PERMISSION))]
ReaderDep = Annotated[Principal, Depends(require_principal())]


@router.post(
    "/applications/{application_id}/votes",
    response_model=VoteOut,
    responses=_errors(400, 401, 403, 404, 422),
)
async def create_vote(
    application_id: UUID,
    payload: VoteCreate,
    service: ServiceDep,
    _principal: ManagerDep,
) -> VoteOut:
    """Abstimmung (``draft``) zu einem Antrag anlegen."""
    return await service.create(application_id, payload)


@router.post(
    "/votes/{vote_id}/open",
    response_model=VoteOut,
    responses=_errors(401, 403, 404, 409),
)
async def open_vote(
    vote_id: UUID,
    service: ServiceDep,
    _principal: ManagerDep,
) -> VoteOut:
    """Abstimmung öffnen (``draft`` → ``open``) → 409, wenn nicht ``draft``."""
    return await service.open(vote_id, now=datetime.now(UTC))


@router.post(
    "/votes/{vote_id}/close",
    response_model=VoteClosed,
    responses=_errors(401, 403, 404, 409),
)
async def close_vote(
    vote_id: UUID,
    service: ServiceDep,
    principal: ManagerDep,
) -> VoteClosed:
    """Abstimmung schließen → auszählen → Ergebnis → ``flow.fire(result_branch)``."""
    return await service.close(vote_id, principal)


@router.post(
    "/votes/{vote_id}/ballot",
    response_model=BallotAccepted,
    responses=_errors(400, 401, 403, 404, 409, 422),
)
async def cast_ballot(
    vote_id: UUID,
    payload: BallotIn,
    service: ServiceDep,
    principal: VoterDep,
) -> BallotAccepted:
    """Stimme abgeben — 403 (nicht in Gruppe), 409 (geschlossen/Doppel), 422 (Option)."""
    return await service.cast(vote_id, principal, payload.choice, now=datetime.now(UTC))


@router.get(
    "/votes/{vote_id}",
    response_model=VoteOut,
    responses=_errors(401, 403, 404),
)
async def get_vote(
    vote_id: UUID,
    service: ServiceDep,
    _principal: ReaderDep,
) -> VoteOut:
    """Vote-State + aggregiertes Tally (bei ``secret`` nur ``counts``, nie Wähler)."""
    return await service.get(vote_id)
