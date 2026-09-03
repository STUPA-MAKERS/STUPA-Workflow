"""Voting API router.

* ``POST /api/applications/{id}/votes`` - create a vote. P(vote.manage).
* ``POST /api/votes/{id}/open``         - open a vote. P(vote.manage).
* ``POST /api/votes/{id}/close``        - close -> result -> flow. P(vote.manage).
* ``POST /api/votes/{id}/ballot``       - cast a vote. Roster of the vote, human only.
* ``GET  /api/votes/{id}``              - vote state + tally (secret: only counts).

RBAC is fail-closed: 401 without a session, 403 without the permission or group
membership (``cast``). The group lives on the vote and is dynamic. The service
therefore runs the check after it loads the vote. The routes declare their errors as
``ProblemDetail`` (problem+json).
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
# The lifecycle routes (create/open/close/cancel) do not use a global-only gate. The
# router gate requires only a session. The service then runs the fail-closed
# gremium-scoped ``vote.manage`` check (``assert_can_manage*``), which admits admin, a
# global ``vote.manage`` holder, or a per-gremium role. This is symmetric with the
# scoped read (``get_scoped``).
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
    ``vote.manage`` for the ``eligibleGroup`` gremium. A caller cannot create a vote in
    another gremium.
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
    """Open a vote and move it from ``draft`` to ``open``.

    Gremium-scoped ``vote.manage``. The call returns 409 when the vote is not
    ``draft``. If a meeting holds the vote, the publisher broadcasts ``vote_opened``
    on the live-vote channel. Without a meeting the broadcast is a no-op.
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
    """Close a vote, compute the tally, set the result and fire the flow branch.

    The close calls ``flow.fire(result_branch)``. Gremium-scoped ``vote.manage`` blocks
    a cross-tenant close, which would fire the flow of another application. The
    publisher broadcasts ``vote_closed`` on the meeting channel. Without a meeting the
    broadcast is a no-op.
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
    """Cancel an open vote.

    The vote moves from ``open`` to ``cancelled``. It gets no result and fires no
    branch. The application stays in the ``vote`` state. This is the escape hatch when
    the vote does not reach the quorum, because ``close`` is then blocked.
    Gremium-scoped ``vote.manage``.
    """
    await service.assert_can_manage_vote(vote_id, principal)
    vote = await service.cancel(vote_id)
    await publisher.vote_cancelled(vote)
    return vote


@router.delete(
    "/votes/{vote_id}",
    status_code=204,
    responses=_errors(401, 403, 404, 409),
)
async def delete_vote(
    vote_id: UUID,
    service: ServiceDep,
    principal: ReaderDep,
) -> None:
    """Delete a standalone application-bound vote that never ran.

    The vote must still be ``draft`` and must hold no ballot. Everything
    further along stays with ``cancel``, so the record of the Gremium keeps
    every vote that ever opened. A meeting-bound vote answers 409 and belongs
    to ``DELETE /meetings/{meeting_id}/votes/{vote_id}``, which applies the
    meeting-scoped check.

    Gremium-scoped ``vote.manage``, like open, close and cancel.
    """
    await service.assert_can_manage_vote(vote_id, principal)
    await service.delete_standalone(vote_id, actor=principal.sub)


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
    # Auth-only gate: an external substitute is in no gremium of the vote. The service
    # holds the authorization. It checks the roster of the vote for the own ballot, and
    # a delegation row for the represented ballot. Both need a human session.
    principal: ReaderDep,
) -> BallotAccepted:
    """Cast a vote.

    The call returns 403 when the caller is not in the group. It returns 409 when the
    vote is closed or the caller already voted. It returns 422 for an unknown option.
    The router then broadcasts ``vote_tally`` so the 'N of M voted' counter of every
    client stays fresh. The event carries aggregates only. The reveal rule hides the
    counts and the leading option until all present members have voted
    (``VoteTallyEvent.from_vote``).
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
    """Return the vote state and the aggregated tally.

    A secret vote exposes only ``counts`` and never the voters. The service scopes the
    read to the read audience of the vote: meeting members, meeting participants, or a
    holder of a read or manage permission. Other gremien get 403, so there is no
    cross-tenant read.
    """
    return await service.get_scoped(vote_id, principal)
