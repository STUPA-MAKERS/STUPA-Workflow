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

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.gremium_roles import LEAD_ROLE_KEYS
from app.modules.admin.models import GremiumMembership, GremiumRole
from app.modules.auth.models import Principal as PrincipalRow
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
from app.modules.protocol.models import Protocol
from app.modules.voting.models import Vote
from app.modules.voting.schemas import VoteClosed, VoteOut
from app.shared.errors import ForbiddenError, NotFoundError


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
    def _to_out(
        meeting: Meeting,
        protocol_id: UUID | None = None,
        can_control: bool = False,
    ) -> MeetingOut:
        return MeetingOut(
            id=meeting.id,
            gremiumId=meeting.gremium_id,
            title=meeting.title,
            date=meeting.date,
            startTime=meeting.start_time,
            status=meeting.status,  # type: ignore[arg-type]
            activeApplicationId=meeting.active_application_id,
            protocolId=protocol_id,
            createdAt=meeting.created_at,
            canControl=can_control,
        )

    # -------------------------------------------------- Sitzungsleitung (#Meetings)
    async def _led_gremium_ids(self, sub: str) -> set[UUID]:
        """Gremium-IDs, in denen ``sub`` aktuell Vorstand/Schriftführung ist."""
        now = datetime.now(UTC)
        rows = (
            await self.session.execute(
                select(GremiumMembership.gremium_id)
                .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
                .join(PrincipalRow, PrincipalRow.id == GremiumMembership.principal_id)
                .where(
                    PrincipalRow.sub == sub,
                    GremiumRole.key.in_(LEAD_ROLE_KEYS),
                    (GremiumMembership.valid_from.is_(None))
                    | (GremiumMembership.valid_from <= now),
                    (GremiumMembership.valid_until.is_(None))
                    | (GremiumMembership.valid_until > now),
                )
            )
        ).scalars()
        return set(rows)

    async def can_control(self, gremium_id: UUID, principal: Principal) -> bool:
        """Admin **oder** Sitzungsleitung (Vorstand/Schriftführung) des Gremiums."""
        if "admin" in principal.roles:
            return True
        return gremium_id in await self._led_gremium_ids(principal.sub)

    async def _get(self, meeting_id: UUID) -> Meeting:
        meeting = (
            await self.session.execute(select(Meeting).where(Meeting.id == meeting_id))
        ).scalar_one_or_none()
        if meeting is None:
            raise NotFoundError(f"meeting {meeting_id} not found")
        return meeting

    async def _protocol_id(self, meeting_id: UUID) -> UUID | None:
        """``protocol.id`` der Sitzung (UNIQUE ``meeting_id``) oder ``None``."""
        return (
            await self.session.execute(
                select(Protocol.id).where(Protocol.meeting_id == meeting_id)
            )
        ).scalar_one_or_none()

    async def get(
        self, meeting_id: UUID, principal: Principal | None = None
    ) -> MeetingOut:
        """Sitzungs-State (404, falls unbekannt).

        ``principal`` optional: der WS-Pfad (Reconnect-State) braucht ``canControl``
        nicht und ruft ohne Principal auf.
        """
        meeting = await self._get(meeting_id)
        can = (
            await self.can_control(meeting.gremium_id, principal)
            if principal is not None
            else False
        )
        return self._to_out(meeting, await self._protocol_id(meeting.id), can)

    async def list(
        self, principal: Principal, gremium_id: UUID | None = None
    ) -> list[MeetingOut]:
        """Sitzungen (neueste zuerst), optional auf ein Gremium gefiltert.

        Erlaubt das **Wiederfinden** angelegter Sitzungen (#104): ohne Liste war eine
        frisch erstellte Sitzung nach Reload nur über ihre UUID erreichbar.
        """
        stmt = select(Meeting).order_by(Meeting.created_at.desc())
        if gremium_id is not None:
            stmt = stmt.where(Meeting.gremium_id == gremium_id)
        meetings = (await self.session.execute(stmt)).scalars().all()
        if not meetings:
            return []
        # Protokoll-IDs gebündelt laden (kein N+1): meeting_id → protocol.id.
        proto_rows = (
            await self.session.execute(
                select(Protocol.meeting_id, Protocol.id).where(
                    Protocol.meeting_id.in_([m.id for m in meetings])
                )
            )
        ).all()
        proto_by_meeting = {meeting_id: pid for meeting_id, pid in proto_rows}
        led = (
            {m.gremium_id for m in meetings}
            if "admin" in principal.roles
            else await self._led_gremium_ids(principal.sub)
        )
        return [
            self._to_out(m, proto_by_meeting.get(m.id), m.gremium_id in led)
            for m in meetings
        ]

    async def create(self, payload: MeetingCreate, principal: Principal) -> MeetingOut:
        """Sitzung (``planned``) anlegen."""
        meeting = Meeting(
            gremium_id=payload.gremium_id,
            title=payload.title,
            date=payload.date,
            start_time=payload.start_time,
            status="planned",
            created_by=principal.sub,
        )
        self.session.add(meeting)
        await self.session.flush()
        await self.session.commit()
        return self._to_out(meeting)

    async def patch(
        self, meeting_id: UUID, payload: MeetingPatch, principal: Principal
    ) -> MeetingOut:
        """Steuerung anwenden + ``meeting_state`` broadcasten.

        Nur Sitzungsleitung (Vorstand/Schriftführung) oder Admin (#Meetings);
        ``meeting.manage`` allein genügt nicht."""
        meeting = await self._get(meeting_id)
        if not await self.can_control(meeting.gremium_id, principal):
            raise ForbiddenError("only the committee lead may control this meeting")
        if payload.status is not None:
            meeting.status = payload.status
        if payload.active_application_id is not None:
            meeting.active_application_id = payload.active_application_id
        if "date" in payload.model_fields_set:
            meeting.date = payload.date
        if "start_time" in payload.model_fields_set:
            meeting.start_time = payload.start_time
        await self.session.flush()
        await self.session.commit()
        out = self._to_out(meeting, can_control=True)
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
