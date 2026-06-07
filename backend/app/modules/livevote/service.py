"""Live-Vote/Meeting-Service (T-16, api.md §4, flows §5).

* :class:`MeetingService` — Sitzungs-CRUD + Steuerung (``activeApplicationId``/
  ``status``); jede Steuerung publiziert ``meeting_state`` auf ``meeting:{id}``.
* :class:`BrokerPublisher` — baut die WS-Events aus den Voting-Schemata und schreibt
  sie über den :class:`~app.modules.livevote.broker.MeetingBroker`. Implementiert das
  leaf-:class:`~app.modules.livevote.publisher.MeetingPublisher`-Protokoll, an dem das
  Voting-Modul beim Open/Close hängt (kein Import-Zyklus).

**Aggregat-only (requirements N1a):** Tally-/Closed-Events tragen nur ``counts``/
``quorumMet``/``leading``/``result`` — nie Wähler-Identitäten. Damit ist der
Beamer-Stream konstruktionsbedingt namensfrei.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.principal import Principal
from app.modules.livevote.broker import MeetingBroker
from app.modules.livevote.events import (
    MeetingStateEvent,
    VoteClosedEvent,
    VoteOpenedEvent,
    VoteTallyEvent,
)
from app.modules.livevote.models import Meeting
from app.modules.livevote.schemas import MeetingCreate, MeetingOut, MeetingPatch
from app.modules.voting.models import Vote
from app.modules.voting.schemas import VoteClosed, VoteOut
from app.shared.errors import NotFoundError


def meeting_channel(meeting_id: UUID) -> str:
    """PubSub-Kanal einer Sitzung (api.md §4)."""
    return f"meeting:{meeting_id}"


class BrokerPublisher:
    """Übersetzt Domänen-Ergebnisse in WS-Events und fan-outet sie über den Broker."""

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
            options=vote.config.options,
            closesAt=vote.closes_at,
            secret=vote.secret,
        )
        await self._broker.publish(meeting_channel(vote.meeting_id), event.dump())

    async def vote_tally(self, vote: VoteOut) -> None:
        if vote.meeting_id is None:
            return
        # ``from_vote`` unterdrückt Choice-Counts solange der Vote geheim **und** offen
        # ist (kein Zwischenstand-Leak am Beamer/Voter); nur die Teilnahme reist mit.
        event = VoteTallyEvent.from_vote(vote)
        await self._broker.publish(meeting_channel(vote.meeting_id), event.dump())

    async def vote_closed(self, vote: VoteClosed) -> None:
        if vote.meeting_id is None:
            return
        event = VoteClosedEvent(
            voteId=vote.id, result=vote.result, counts=vote.tally.counts
        )
        await self._broker.publish(meeting_channel(vote.meeting_id), event.dump())


class MeetingService:
    """An eine ``AsyncSession`` (+ optionalen Publisher) gebundener Sitzungs-Service."""

    def __init__(
        self, session: AsyncSession, publisher: BrokerPublisher | None = None
    ) -> None:
        self.session = session
        self.publisher = publisher

    @staticmethod
    def _to_out(meeting: Meeting) -> MeetingOut:
        return MeetingOut(
            id=meeting.id,
            gremiumId=meeting.gremium_id,
            title=meeting.title,
            date=meeting.date,
            status=meeting.status,  # type: ignore[arg-type]
            activeApplicationId=meeting.active_application_id,
        )

    async def _get(self, meeting_id: UUID) -> Meeting:
        meeting = (
            await self.session.execute(select(Meeting).where(Meeting.id == meeting_id))
        ).scalar_one_or_none()
        if meeting is None:
            raise NotFoundError(f"meeting {meeting_id} not found")
        return meeting

    async def get(self, meeting_id: UUID) -> MeetingOut:
        """Sitzungs-State (404, falls unbekannt)."""
        return self._to_out(await self._get(meeting_id))

    async def create(self, payload: MeetingCreate, principal: Principal) -> MeetingOut:
        """Sitzung (``planned``) anlegen."""
        meeting = Meeting(
            gremium_id=payload.gremium_id,
            title=payload.title,
            date=payload.date,
            status="planned",
            created_by=principal.sub,
        )
        self.session.add(meeting)
        await self.session.flush()
        await self.session.commit()
        return self._to_out(meeting)

    async def patch(self, meeting_id: UUID, payload: MeetingPatch) -> MeetingOut:
        """Steuerung anwenden + ``meeting_state`` broadcasten."""
        meeting = await self._get(meeting_id)
        if payload.status is not None:
            meeting.status = payload.status
        if payload.active_application_id is not None:
            meeting.active_application_id = payload.active_application_id
        await self.session.flush()
        await self.session.commit()
        out = self._to_out(meeting)
        if self.publisher is not None:
            await self.publisher.meeting_state(out)
        return out

    async def open_vote(self, meeting_id: UUID) -> Vote | None:
        """Aktuell offener Vote dieser Sitzung (für ``subscribe``-Reconnect-State)."""
        return (
            await self.session.execute(
                select(Vote)
                .where(Vote.meeting_id == meeting_id, Vote.status == "open")
                .order_by(Vote.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
