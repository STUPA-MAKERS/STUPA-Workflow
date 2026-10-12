"""The checks of a meeting vote before it opens.

The create of a meeting vote and the open of a prepared draft run the same checks. A
draft can wait a long time, also in a planned meeting, so its open runs them again
against the current state: the meeting must be live, the application must still be in
a vote state that the Gremium of the meeting decides, a vote with guests needs a
meeting where guests vote and a public agenda item, and the quorum denominator comes
from the current roster. Both open routes call ``draft_open_checks``: the route of the
meeting and the generic ``POST /votes/{id}/open``, so neither opens a draft without
them.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.principal import Principal
from app.modules.livevote.agenda_service import AgendaService
from app.modules.livevote.schemas import MeetingOut
from app.modules.livevote.service import MeetingService
from app.shared.errors import ConflictError, NotFoundError


async def check_draft_open(
    session: AsyncSession, meeting_id: UUID, vote_id: UUID, principal: Principal
) -> int:
    """Run ``draft_open_checks`` for a meeting vote outside the meeting routes.

    Returns:
        The quorum denominator from the current roster.
    """
    meetings = MeetingService(session)
    meeting = await meetings.get(meeting_id, principal)
    return await draft_open_checks(meetings, AgendaService(session), meeting, vote_id)


async def draft_open_checks(
    service: MeetingService, agenda: AgendaService, meeting: MeetingOut, vote_id: UUID
) -> int:
    """Refuse the open of a draft that the current state does not allow.

    Returns:
        The quorum denominator from the current roster.

    Raises:
        NotFoundError: The meeting has no such vote.
        ConflictError: The meeting is not live, the vote is no longer a draft, guests
            no longer vote on it (``guests_vote_unavailable``), or its application
            cannot be decided now.
    """
    assert_vote_window(meeting, draft=False)
    vote = next((v for v in meeting.votes if v.id == vote_id), None)
    if vote is None:
        raise NotFoundError(f"vote {vote_id} not found in this meeting")
    if vote.status != "draft":
        raise ConflictError(f"vote is {vote.status}, cannot open.", code="conflict")
    if vote.guests_vote:
        guests_allowed = meeting.public_join and meeting.guests_mode == "vote"
        non_public = (
            vote.agenda_item_id is not None
            and (await agenda.item(meeting.id, vote.agenda_item_id)).non_public
        )
        if not guests_allowed or non_public:
            raise ConflictError(
                "Guests no longer vote on this question. Delete it and prepare it again.",
                code="guests_vote_unavailable",
            )
    if vote.application_id is not None:
        await assert_application_votable(service, meeting, vote.application_id)
    return await eligible_count(service, meeting, guests_vote=vote.guests_vote)


def assert_vote_window(meeting: MeetingOut, *, draft: bool) -> None:
    """Refuse a vote outside the state of the meeting that allows it.

    A vote opens only in a ``live`` meeting. A ``draft`` also waits in a ``planned``
    one.

    Raises:
        ConflictError: The meeting has not started (``meeting_not_started``) or is
            closed (``meeting_closed``).
    """
    if meeting.status == "closed":
        raise ConflictError(
            "the meeting is closed — a vote can no longer open", code="meeting_closed"
        )
    if meeting.status == "planned" and not draft:
        raise ConflictError(
            "the meeting has not started — start it before opening a vote",
            code="meeting_not_started",
        )


async def assert_application_votable(
    service: MeetingService, meeting: MeetingOut, application_id: UUID
) -> None:
    """Refuse a vote on an application that this meeting cannot decide now.

    An application vote fires the pass or fail branch of the current state on close.
    If the application is not in a vote state, nobody can close the vote, and the cast
    ballots are lost. Only the Gremium that decides the current vote state votes: a
    stale agenda item (the application left the state and came back for another
    Gremium) must not let this meeting decide.

    Raises:
        ConflictError: The application is not in a vote state (``conflict``), or the
            Gremium of the meeting does not decide it (``vote_gremium_mismatch``).
    """
    if await service.application_state_kind(application_id) != "vote":
        raise ConflictError(
            "The application is not in a vote state — move it into its "
            "decision state before opening the vote.",
            code="conflict",
        )
    if await service.application_vote_gremium(application_id) != meeting.gremium_id:
        raise ConflictError(
            "The Gremium of this meeting does not decide the current vote of the "
            "application.",
            code="vote_gremium_mismatch",
        )


async def eligible_count(
    service: MeetingService, meeting: MeetingOut, *, guests_vote: bool
) -> int:
    """Return the quorum denominator of a meeting vote from the current roster.

    The server always derives it from the real roster and never from the client. A
    holder of ``canManageVotes`` cannot manipulate it. A vote with guests counts the
    present members and the admitted guests; the close fixes the number again (a
    display value, there is no quorum).
    """
    if guests_vote:
        return await service.present_member_count(meeting.id) + meeting.admitted_guests
    return await service.vote_eligible_count(meeting.gremium_id)
