"""The route that opens a vote: `POST /votes/{vote_id}/open`.

A meeting vote runs the checks of the meeting before it opens, so the route is in
`livevote` and not in `voting` (§S/backend/python/000650). The URL and the response
are those of the voting routes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Request

from app.deps import SettingsDep
from app.modules.livevote import vote_open
from app.modules.voting.router import PublisherDep, ReaderDep, ServiceDep, mail_poll_start
from app.modules.voting.schemas import VoteOut
from app.shared.errors import ProblemDetail

router = APIRouter(tags=["voting"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Document problem+json for the given error status codes."""
    return dict.fromkeys(codes, _PROBLEM)


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
    background: BackgroundTasks,
    request: Request,
    settings: SettingsDep,
) -> VoteOut:
    """Open a vote and move it from ``draft`` to ``open``.

    Gremium-scoped manage right. The call returns 409 when the vote is not
    ``draft``. If a meeting holds the vote, the publisher broadcasts ``vote_opened``
    on the live-vote channel. Without a meeting the broadcast is a no-op.

    A meeting vote runs the checks of the open route of the meeting first
    (``livevote.vote_open``): a prepared draft can wait while the state changes, and
    this route must not open it around them. The quorum denominator then comes from
    the current roster. A poll of a Gremium opens only with its end at least one hour
    ahead (422 ``closes_at_too_soon``) and sends ``poll_started``.

    The route is in `livevote`, because it runs the checks of a meeting, and `voting`
    imports no higher module (§S/backend/python/000650).
    """
    await service.assert_can_run_vote(vote_id, principal)
    meeting_id = await service.meeting_id_of(vote_id)
    eligible = (
        await vote_open.check_draft_open(service.session, meeting_id, vote_id, principal)
        if meeting_id is not None
        else None
    )
    vote = await service.open(
        vote_id, now=datetime.now(UTC), actor=principal.sub, eligible_count=eligible
    )
    await publisher.vote_opened(vote)
    mail_poll_start(vote, background, request, settings)
    return vote
