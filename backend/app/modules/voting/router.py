"""Voting API router.

* ``POST /api/applications/{id}/votes`` - create a vote. Manage right in the gremium.
* ``POST /api/votes/{id}/open``         - open a vote. Manage right in the gremium.
* ``POST /api/votes/{id}/close``        - close -> result -> flow. Manage right.
* ``POST /api/votes/{id}/cancel``       - cancel an open vote. Manage right.
* ``DELETE /api/votes/{id}``            - delete a draft vote. Manage right.
* ``POST /api/votes/{id}/ballot``       - cast a vote. Roster of the vote, human only.
* ``GET  /api/votes/{id}``              - vote state + tally (secret: only counts).
* ``GET  /api/votes``                   - the votes the caller can read, with the own
  ballot state (no tally).
* ``POST /api/votes/{id}/draw-lot``     - draw the lot of a tied election (F2).
* ``POST /api/votes/{id}/runoff``       - create the runoff of an election (F2).

The manage right is the admin role or the gremium permission ``vote.manage`` or
``session.manage`` in the gremium of the vote (``VotingService.can_manage_group``). The
cast right is the gremium permission ``vote.cast``. No global permission grants a vote
right.

RBAC is fail-closed: 401 without a session, 403 without the right. The gremium lives on
the vote. The service therefore runs the check after it loads the vote. The routes
declare their errors as ``ProblemDetail`` (problem+json).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.deps import DbSession, require_principal
from app.modules.auth.principal import Principal
from app.modules.flow.dispatch import ActionDispatcher
from app.modules.flow.router import get_action_dispatcher
from app.modules.livevote.publisher import MeetingPublisher, get_meeting_publisher
from app.modules.voting.election import ElectionService
from app.modules.voting.schemas import (
    BallotAccepted,
    BallotIn,
    VoteClosed,
    VoteCreate,
    VoteListItem,
    VoteOut,
    VoteStatus,
)
from app.modules.voting.service import VotingService
from app.shared.errors import ProblemDetail
from app.shared.paging import DEFAULT_LIMIT, MAX_LIMIT, Page

router = APIRouter(tags=["voting"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def get_voting_service(
    session: DbSession,
    # The flow dependency, so the override in `app.main` also reaches the close
    # route. A close fires the pass or fail branch with all its actions.
    dispatcher: Annotated[ActionDispatcher, Depends(get_action_dispatcher)],
) -> VotingService:
    return VotingService(session, dispatcher)


ServiceDep = Annotated[VotingService, Depends(get_voting_service)]
PublisherDep = Annotated[MeetingPublisher, Depends(get_meeting_publisher)]
# The lifecycle routes (create/open/close/cancel/delete) have no permission gate of
# their own. The router gate requires only a session. The service then runs the
# fail-closed gremium-scoped check (``assert_can_manage*``), which admits the admin role
# or a gremium role with ``vote.manage`` or ``session.manage`` in the gremium of the
# vote. This is symmetric with the scoped read (``get_scoped``).
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

    ``eligibleGroup`` is the UUID of a gremium. A free group key or an
    ``eligibleCount`` in the body gives 422. The gremium must be the gremium of the
    application (422 ``eligible_group_mismatch``). If the application and its state
    name no gremium, only the admin role can create the vote (403). The server counts
    the eligible voters from the roster of the gremium.

    Gremium-scoped: the admin role, or a gremium role with ``vote.manage`` or
    ``session.manage`` in the ``eligibleGroup`` gremium. A caller cannot create a vote
    in another gremium.
    """
    await service.assert_can_manage_group(str(payload.eligible_group), None, principal)
    return await service.create(application_id, payload, principal)


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

    Gremium-scoped manage right. The call returns 409 when the vote is not
    ``draft``. If a meeting holds the vote, the publisher broadcasts ``vote_opened``
    on the live-vote channel. Without a meeting the broadcast is a no-op.
    """
    await service.assert_can_manage_vote(vote_id, principal)
    vote = await service.open(vote_id, now=datetime.now(UTC), actor=principal.sub)
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

    The close and the ``pass`` or ``fail`` transition commit together. When the branch
    cannot fire (guard failed, lost race, no such transition), the vote still closes:
    ``branchFired`` is False, the audit log holds ``vote_branch_blocked``, and a person
    must move the application by hand. The gremium-scoped manage right blocks a
    cross-tenant close, which would fire the flow of another application. The
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
    Gremium-scoped manage right.
    """
    await service.assert_can_manage_vote(vote_id, principal)
    vote = await service.cancel(vote_id, now=datetime.now(UTC), actor=principal.sub)
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

    Gremium-scoped manage right, like open, close and cancel.
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
    vote is closed, or 409 ``already_voted`` when the caller already voted: a ballot
    never changes after the cast. It returns 422 for an unknown option.
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


@router.post(
    "/votes/{vote_id}/draw-lot",
    response_model=VoteOut,
    responses=_errors(401, 403, 404, 409),
)
async def draw_lot(
    vote_id: UUID,
    service: ServiceDep,
    publisher: PublisherDep,
    principal: ReaderDep,
) -> VoteOut:
    """Draw the lot of a tied election (F2).

    Only a closed election with a pending lot (one seat, or a runoff round) takes the
    call; the server draws with ``secrets.choice``, stores the lot, elects the drawn
    candidates and audits ``vote_lot_drawn``. A second call gives 409
    ``lot_already_drawn``, a vote without a pending lot 409 ``no_lot_pending``, a
    motion 409 ``not_an_election``. Gremium-scoped manage right (the meeting lead).
    The publisher sends ``vote_lot_drawn`` to the meeting and the beamer.
    """
    await service.assert_can_manage_vote(vote_id, principal)
    vote = await ElectionService(service).draw_lot(vote_id, principal, now=datetime.now(UTC))
    await publisher.vote_lot_drawn(vote)
    return vote


@router.post(
    "/votes/{vote_id}/runoff",
    response_model=VoteOut,
    responses=_errors(401, 403, 404, 409),
)
async def create_runoff(
    vote_id: UUID,
    service: ServiceDep,
    principal: ReaderDep,
) -> VoteOut:
    """Create the draft runoff of an election with a tie at the seat boundary (F2).

    The runoff holds the tied candidates and the open seats, on the same agenda item,
    one round later; the meeting lead opens it with ``POST /votes/{id}/open``. 409
    ``no_runoff_pending`` when no runoff is due, ``runoff_exists`` when it exists,
    ``not_an_election`` for a motion; 409 when the meeting is not live.
    Gremium-scoped manage right.
    """
    await service.assert_can_manage_vote(vote_id, principal)
    return await ElectionService(service).create_runoff(vote_id)


@router.get(
    "/votes",
    response_model=Page[VoteListItem],
    responses=_errors(401, 422),
)
async def list_votes(
    service: ServiceDep,
    principal: ReaderDep,
    status: Annotated[list[VoteStatus] | None, Query()] = None,
    gremium_id: Annotated[UUID | None, Query(alias="gremiumId")] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[VoteListItem]:
    """List the votes that the caller can read, the open votes first.

    The read rule is the rule of ``GET /votes/{id}``: the meeting votes of the meetings
    the caller can read, and the votes without a meeting for a holder of
    ``application.read``, an eligible voter or a manager of the vote. ``status`` repeats
    (``?status=open&status=closed``). Without it the list leaves out the drafts.
    ``gremiumId`` keeps the votes of one gremium, and ``q`` searches the question and
    the meeting title. Each row carries ``canCast`` and the own ballot (``myBallot``; a
    secret vote gives only ``cast``) and no tally.
    """
    return await service.list_visible(
        principal,
        statuses=status,
        gremium_id=gremium_id,
        q=q,
        limit=limit,
        offset=offset,
    )


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
    read to the read audience of the vote: meeting members, meeting participants, the
    eligible voters, a holder of ``application.read``, or a manager of the vote. Other
    gremien get 403, so there is no cross-tenant read. ``canManage`` and ``canCast``
    tell what the caller may do with the vote. ``myBallot`` holds the own ballot of the
    caller (a secret vote gives only ``cast``), and ``representedCast`` tells whether
    the caller cast the ballot of a delegator. ``openedAt`` and ``closedAt`` are the real
    open and end times. ``closesAt`` is the planned end of the cast window.
    """
    return await service.get_scoped(vote_id, principal)
