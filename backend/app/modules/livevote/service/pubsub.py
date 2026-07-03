"""WS pub/sub glue: the ``meeting:{id}`` channel and the broker-backed publisher.

Aggregate-only: tally/closed events carry only ``counts``/``quorumMet``/``leading``/
``result`` — never voter identities — so the beamer stream is name-free by design.
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
    """Pub/sub channel of a meeting."""
    return f"meeting:{meeting_id}"


class BrokerPublisher:
    """Translates domain results into WS events and fans them out via the broker.

    Implements the leaf ``MeetingPublisher`` protocol the voting module hooks into
    on open/close (avoids an import cycle).
    """

    def __init__(self, broker: MeetingBroker) -> None:
        self._broker = broker

    async def meeting_state(self, meeting: MeetingOut) -> None:
        event = MeetingStateEvent(
            activeApplicationId=meeting.active_application_id, status=meeting.status
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
        # ``from_vote`` hides choice counts while the vote is secret AND open (no
        # interim leak to beamer/voters); only the participation travels along.
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
