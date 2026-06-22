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
from app.modules.livevote.publisher import MeetingPublisher, get_meeting_publisher
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
PublisherDep = Annotated[MeetingPublisher, Depends(get_meeting_publisher)]
# Lifecycle (create/open/close/cancel) ist NICHT mehr global-only gegated (#AUD-027):
# das Router-Gate verlangt nur Auth (``ReaderDep``); die gremium-genaue ``vote.manage``-
# Prüfung (admin / globale vote.manage / per-Gremium-Rolle) liegt fail-closed im Service
# (``assert_can_manage*``), symmetrisch zum gescopten Read (``get_scoped``).
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
    principal: ReaderDep,
) -> VoteOut:
    """Abstimmung (``draft``) zu einem Antrag anlegen.

    Gremium-scoped (#sec-audit, AUD-027): Admin, globale ``vote.manage`` ODER eine
    Gremium-Rolle mit ``vote.manage`` für das Gremium des ``eligibleGroup`` — kein
    Anlegen in fremden Gremien."""
    await service.assert_can_manage_group(payload.eligible_group, None, principal)
    return await service.create(application_id, payload)


@router.post(
    "/votes/{vote_id}/open",
    response_model=VoteOut,
    responses=_errors(401, 403, 404, 409),
)
async def open_vote(
    vote_id: UUID,
    service: ServiceDep,
    publisher: PublisherDep,
    principal: ReaderDep,
) -> VoteOut:
    """Abstimmung öffnen (``draft`` → ``open``) → 409, wenn nicht ``draft``.

    Gremium-scoped (#sec-audit, AUD-027): Admin, globale ``vote.manage`` ODER eine
    Gremium-Rolle mit ``vote.manage`` für das Gremium des Votes. Hängt der Vote an
    einer Sitzung, broadcastet der Publisher ``vote_opened`` auf den Live-Vote-Kanal
    (T-16); andernfalls no-op."""
    await service.assert_can_manage_vote(vote_id, principal)
    vote = await service.open(vote_id, now=datetime.now(UTC))
    await publisher.vote_opened(vote)
    return vote


@router.post(
    "/votes/{vote_id}/close",
    response_model=VoteClosed,
    responses=_errors(401, 403, 404, 409),
)
async def close_vote(
    vote_id: UUID,
    service: ServiceDep,
    publisher: PublisherDep,
    principal: ReaderDep,
) -> VoteClosed:
    """Abstimmung schließen → auszählen → Ergebnis → ``flow.fire(result_branch)``.

    Gremium-scoped (#sec-audit, AUD-027): Admin, globale ``vote.manage`` ODER eine
    Gremium-Rolle mit ``vote.manage`` für das Gremium des Votes — kein Cross-Tenant-
    Schließen (das den Flow des fremden Antrags feuern würde). Live-Vote (T-16):
    broadcastet ``vote_closed`` auf den Sitzungs-Kanal (no-op ohne Sitzung)."""
    await service.assert_can_manage_vote(vote_id, principal)
    closed = await service.close(vote_id, principal)
    await publisher.vote_closed(closed)
    return closed


@router.post(
    "/votes/{vote_id}/cancel",
    response_model=VoteOut,
    responses=_errors(401, 403, 404, 409),
)
async def cancel_vote(
    vote_id: UUID,
    service: ServiceDep,
    publisher: PublisherDep,
    principal: ReaderDep,
) -> VoteOut:
    """Abstimmung abbrechen (#12): ``open`` → ``cancelled`` — kein Ergebnis, kein
    Branch; der Antrag bleibt im ``vote``-State. Der Ausweg, wenn das Quorum nicht
    zustande kommt (``close`` ist dann blockiert).

    Gremium-scoped (#sec-audit, AUD-027): Admin, globale ``vote.manage`` ODER eine
    Gremium-Rolle mit ``vote.manage`` für das Gremium des Votes."""
    await service.assert_can_manage_vote(vote_id, principal)
    vote = await service.cancel(vote_id)
    await publisher.vote_cancelled(vote)
    return vote


@router.post(
    "/votes/{vote_id}/ballot",
    response_model=BallotAccepted,
    responses=_errors(400, 401, 403, 404, 409, 422),
)
async def cast_ballot(
    vote_id: UUID,
    payload: BallotIn,
    service: ServiceDep,
    publisher: PublisherDep,
    # Nur Auth am Gate (#delegation-rework): ein externer Stellvertreter hat kein
    # globales ``vote.cast`` — die Autorisierung (vote.cast+Gruppe für die eigene
    # Stimme, Delegations-Zeile für die Vertretungs-Stimme) liegt im Service.
    principal: ReaderDep,
) -> BallotAccepted:
    """Stimme abgeben — 403 (nicht in Gruppe), 409 (geschlossen/Doppel), 422 (Option).

    Broadcastet anschließend ``vote_tally`` (#vote-progress): ohne das Event blieb
    der »N von M abgestimmt«-Zähler aller verbundenen Clients bis zum Reload stale.
    Nur Aggregate — die Reveal-Regel verdeckt counts/leading, bis alle Anwesenden
    abgestimmt haben (``VoteTallyEvent.from_vote``)."""
    accepted = await service.cast(
        vote_id,
        principal,
        payload.choice,
        now=datetime.now(UTC),
        as_delegation=payload.as_delegation,
    )
    await publisher.vote_tally(await service.get(vote_id))
    return accepted


@router.get(
    "/votes/{vote_id}",
    response_model=VoteOut,
    responses=_errors(401, 403, 404),
)
async def get_vote(
    vote_id: UUID,
    service: ServiceDep,
    principal: ReaderDep,
) -> VoteOut:
    """Vote-State + aggregiertes Tally (bei ``secret`` nur ``counts``, nie Wähler).

    Gescopt auf den Lesekreis des Votes (#sec-audit): Sitzungs-Mitglieder/Teilnehmer
    bzw. Lese-/Verwaltungs-Permission — 403 für Fremd-Gremien (kein Cross-Tenant-Lesen)."""
    return await service.get_scoped(vote_id, principal)
