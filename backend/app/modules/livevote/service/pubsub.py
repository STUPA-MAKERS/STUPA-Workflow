"""WebSocket pub/sub glue: the `meeting:{id}` channel and the broker-backed publisher.

The events carry aggregates only. A tally event and a closed event hold `counts`,
`quorumMet`, `leading`, and `result`, but never a voter identity. The beamer stream
therefore carries no names.
"""

from __future__ import annotations

from uuid import UUID

from app.modules.livevote.broker import MeetingBroker
from app.modules.livevote.events import (
    MeetingStateEvent,
    VoteCancelledEvent,
    VoteClosedEvent,
    VoteOpenedEvent,
    VoteTallyEvent,
)
from app.modules.livevote.schemas import MeetingOut
from app.modules.voting.schemas import VoteClosed, VoteOut


def meeting_channel(meeting_id: UUID) -> str:
    """Return the pub/sub channel of a meeting."""
    return f"meeting:{meeting_id}"


class BrokerPublisher:
    """Translate domain results into WebSocket events and send them over the broker.

    This class implements the leaf `MeetingPublisher` protocol. The voting module
    hooks into that protocol when it opens or closes a vote. The protocol avoids an
    import cycle.
    """

    def __init__(self, broker: MeetingBroker) -> None:
        self._broker = broker

    async def meeting_state(self, meeting: MeetingOut) -> None:
        event = MeetingStateEvent(
            activeApplicationId=meeting.active_application_id,
            currentAgendaItemId=meeting.current_agenda_item_id,
            status=meeting.status,
        )
        await self._broker.publish(meeting_channel(meeting.id), event.dump())

    async def vote_opened(self, vote: VoteOut) -> None:
        if vote.meeting_id is None:
            return
        event = VoteOpenedEvent(
            voteId=vote.id,
            applicationId=vote.application_id,
            agendaItemId=vote.agenda_item_id,
            question=vote.question,
            options=vote.config.options,
            closesAt=vote.closes_at,
            secret=vote.secret,
        )
        await self._broker.publish(meeting_channel(vote.meeting_id), event.dump())

    async def vote_tally(self, vote: VoteOut) -> None:
        if vote.meeting_id is None:
            return
        # `from_vote` hides the choice counts while the vote is secret and open.
        # This prevents an interim leak to the beamer and to the voters. Only the
        # participation count travels.
        event = VoteTallyEvent.from_vote(vote)
        await self._broker.publish(meeting_channel(vote.meeting_id), event.dump())

    async def vote_closed(self, vote: VoteClosed) -> None:
        if vote.meeting_id is None:
            return
        event = VoteClosedEvent(
            voteId=vote.id,
            result=vote.result,
            counts=vote.tally.counts,
            failedReason=vote.tally.failed_reason,
        )
        await self._broker.publish(meeting_channel(vote.meeting_id), event.dump())

    async def vote_cancelled(self, vote: VoteOut) -> None:
        if vote.meeting_id is None:
            return
        event = VoteCancelledEvent(voteId=vote.id)
        await self._broker.publish(meeting_channel(vote.meeting_id), event.dump())
