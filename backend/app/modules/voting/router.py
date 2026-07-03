"""Voting API router.

* ``POST /api/applications/{id}/votes`` - P(vote.manage); create a vote.
* ``POST /api/votes/{id}/open``         - P(vote.manage); open.
* ``POST /api/votes/{id}/close``        - P(vote.manage); close -> result -> flow.
* ``POST /api/votes/{id}/ballot``       - P(vote.cast)+group; cast a vote.
* ``GET  /api/votes/{id}``              - vote state + tally (secret: only counts).

RBAC is fail-closed: 401 without a session, 403 without the permission or group
membership (``cast``). The group lives on the vote (dynamic), so the check runs in
the service after loading. Errors are declared as ``ProblemDetail`` (problem+json).
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
    """Dispatcher for flow actions on close (default: no-op/log)."""
    return NullActionDispatcher()


def get_voting_service(
    session: DbSession,
    dispatcher: Annotated[ActionDispatcher, Depends(get_action_dispatcher)],
) -> VotingService:
    return VotingService(session, dispatcher)


ServiceDep = Annotated[VotingService, Depends(get_voting_service)]
PublisherDep = Annotated[MeetingPublisher, Depends(get_meeting_publisher)]
# Lifecycle (create/open/close/cancel) is not global-only gated: the router gate only
# requires auth; the gremium-scoped ``vote.manage`` check (admin / global vote.manage /
# per-gremium role) is fail-closed in the service (``assert_can_manage*``), symmetric
# with the scoped read (``get_scoped``).
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
    """Create a draft vote on an application.

    Gremium-scoped: admin, global ``vote.manage``, or a gremium role with
    ``vote.manage`` for the ``eligibleGroup`` gremium - no creating in other gremien.
    """
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
    """Open a vote (``draft`` -> ``open``); 409 if not ``draft``.

    Gremium-scoped ``vote.manage``. If the vote is bound to a meeting, the publisher
    broadcasts ``vote_opened`` on the live-vote channel; otherwise no-op.
    """
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
    """Close a vote -> tally -> result -> ``flow.fire(result_branch)``.

    Gremium-scoped ``vote.manage`` - no cross-tenant close (which would fire another
    application's flow). Broadcasts ``vote_closed`` on the meeting channel (no-op if no meeting).
    """
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
    """Cancel a vote: ``open`` -> ``cancelled`` - no result, no branch; the application
    stays in the ``vote`` state. The escape hatch when the quorum is not reached
    (``close`` is then blocked).

    Gremium-scoped ``vote.manage``.
    """
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
    # Auth-only gate: an external substitute has no global ``vote.cast``; the
    # authorization (vote.cast+group for the own vote, delegation row for the
    # represented vote) lives in the service.
    principal: ReaderDep,
) -> BallotAccepted:
    """Cast a vote - 403 (not in group), 409 (closed/double), 422 (option).

    Then broadcasts ``vote_tally`` so every client's 'N of M voted' counter stays
    fresh. Aggregates only - the reveal rule hides counts/leading until all present
    members have voted (``VoteTallyEvent.from_vote``).
    """
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
    """Vote state + aggregated tally (only ``counts`` when ``secret``, never voters).

    Scoped to the vote's read audience: meeting members/participants or a
    read/manage permission - 403 for other gremien (no cross-tenant read).
    """
    return await service.get_scoped(vote_id, principal)
