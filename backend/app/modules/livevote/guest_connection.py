"""WebSocket of a guest of a public meeting (#17).

The guest channel listens on the same pub/sub channel `meeting:{id}` as the members,
but it filters every event:

* The own state comes as `guest_status`. A `guest_updated` event of another guest is
  dropped, so a guest never learns the name of another person. After `rejected`,
  `removed`, `left` or a voided request (`expired`) the server closes the socket.
* A waiting guest gets nothing else.
* An admitted guest gets `meeting_state` (status and current agenda item only), the
  vote events of PUBLIC agenda items, and `guest_counts` with the number of admitted
  guests. Never `viewers` (names), never the lead events, never a vote of a non-public
  item. A `meeting_state` with `closed` ends the socket.

The client never casts over this socket; it uses the REST ballot route. Its only
message is `subscribe`, which sends the state again.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.livevote.broker import MeetingBroker
from app.modules.livevote.events import (
    ErrorEvent,
    GuestStatusEvent,
    VoteOpenedEvent,
    VoteTallyEvent,
)
from app.modules.livevote.guests import GuestService
from app.modules.livevote.models import Meeting, MeetingGuest
from app.modules.livevote.service.pubsub import meeting_channel
from app.modules.voting.models import Vote
from app.modules.voting.service import VotingService

logger = logging.getLogger("app.livevote.guest")

# The vote events that an admitted guest gets for a public agenda item.
_VOTE_EVENTS = frozenset({"vote_opened", "vote_tally", "vote_closed", "vote_cancelled"})
# After these states the guest has no business on the channel any more.
_TERMINAL = frozenset({"rejected", "removed", "left", "expired"})


class _Closed(Exception):
    """The connection ends on purpose (terminal state or closed meeting)."""


class GuestConnection:
    """One WebSocket of one guest device."""

    def __init__(
        self,
        websocket: WebSocket,
        *,
        session: AsyncSession,
        broker: MeetingBroker,
        meeting_id: UUID,
        guest: MeetingGuest,
    ) -> None:
        self.ws = websocket
        self.session = session
        self.broker = broker
        self.meeting_id = meeting_id
        self.guest_id = guest.id
        self.number = guest.seq
        self.display_name = guest.display_name
        self.status = guest.status
        self.guests = GuestService(session)
        # One task at a time uses the database session.
        self._db = asyncio.Lock()
        # vote id -> True when the vote belongs to a public item of this meeting.
        self._public_votes: dict[UUID, bool] = {}

    async def _send(self, payload: dict[str, Any]) -> None:
        await self.ws.send_json(payload)

    async def _send_status(self, reason: str | None = None) -> None:
        await self._send(
            GuestStatusEvent(
                status=self.status,  # type: ignore[arg-type]
                displayName=self.display_name,
                number=self.number,
                reason=reason,  # type: ignore[arg-type]
            ).dump()
        )

    async def _vote_is_public(self, vote_id: UUID) -> bool:
        cached = self._public_votes.get(vote_id)
        if cached is not None:
            return cached
        async with self._db:
            try:
                public = await self.guests.vote_is_public(vote_id, self.meeting_id)
            finally:
                await self.session.commit()
        self._public_votes[vote_id] = public
        return public

    async def send_state(self) -> None:
        """Send the own state and, once admitted, the state of the meeting."""
        await self._send_status()
        if self.status != "admitted":
            return
        async with self._db:
            try:
                meeting = await self.session.get(Meeting, self.meeting_id, populate_existing=True)
                if meeting is None:  # pragma: no cover - the cascade removes the guest too
                    raise _Closed
                admitted, _ = await self.guests.counts(self.meeting_id)
                state = {
                    "type": "meeting_state",
                    "status": meeting.status,
                    "currentAgendaItemId": (
                        str(meeting.current_agenda_item_id)
                        if meeting.current_agenda_item_id
                        else None
                    ),
                }
                open_vote = (
                    await self.session.execute(
                        select(Vote)
                        .where(Vote.meeting_id == self.meeting_id, Vote.status == "open")
                        .order_by(Vote.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                vote_out = None
                if open_vote is not None and await self.guests.vote_is_public(
                    open_vote.id, self.meeting_id
                ):
                    vote_out = await VotingService(self.session).get(open_vote.id)
            finally:
                await self.session.commit()
        await self._send(state)
        await self._send({"type": "guest_counts", "admittedGuests": admitted})
        if vote_out is not None:
            await self._send(
                VoteOpenedEvent(
                    voteId=vote_out.id,
                    applicationId=vote_out.application_id,
                    agendaItemId=vote_out.agenda_item_id,
                    question=vote_out.question,
                    options=vote_out.config.options,
                    closesAt=vote_out.closes_at,
                    secret=vote_out.secret,
                    replay=True,
                ).dump()
            )
            await self._send(VoteTallyEvent.from_vote(vote_out).dump())
        if state["status"] == "closed":
            raise _Closed

    async def handle(self, message: dict[str, Any]) -> None:
        """Filter one channel event for this guest and send what the guest may see.

        Raises:
            _Closed: The guest reached a terminal state, or the meeting closed.
        """
        kind = message.get("type")
        if kind == "guest_updated":
            guest = message.get("guest")
            if not isinstance(guest, dict) or guest.get("id") != str(self.guest_id):
                return
            self.status = str(guest.get("status"))
            self.display_name = guest.get("displayName")  # type: ignore[assignment]
            number = guest.get("number")
            if isinstance(number, int):
                self.number = number
            reason = message.get("reason")
            await self._send_status(reason if isinstance(reason, str) else None)
            if self.status in _TERMINAL:
                raise _Closed
            if self.status == "admitted":
                await self.send_state()
            return
        if self.status != "admitted":
            return
        if kind == "meeting_state":
            status = message.get("status")
            await self._send(
                {
                    "type": "meeting_state",
                    "status": status,
                    "currentAgendaItemId": message.get("currentAgendaItemId"),
                }
            )
            if status == "closed":
                raise _Closed
        elif kind == "guest_counts":
            admitted = message.get("admittedGuests")
            await self._send({"type": "guest_counts", "admittedGuests": admitted})
        elif kind in _VOTE_EVENTS:
            raw = message.get("voteId")
            try:
                vote_id = UUID(str(raw))
            except ValueError:
                return
            if await self._vote_is_public(vote_id):
                await self._send(message)

    async def _pump(self, subscription: object) -> None:
        async for message in subscription:  # type: ignore[attr-defined]
            await self.handle(message)

    async def _receive(self) -> None:
        while True:
            try:
                raw = await self.ws.receive_json()
            except json.JSONDecodeError:
                await self._send(ErrorEvent(code="invalid_message").dump())
                continue
            if isinstance(raw, dict) and raw.get("type") == "subscribe":
                await self.send_state()
            else:
                await self._send(ErrorEvent(code="unknown_type").dump())

    async def run(self) -> None:
        """Subscribe, send the state, then filter the channel until the end."""
        async with self.broker.subscribe(meeting_channel(self.meeting_id)) as subscription:
            try:
                await self.send_state()
            except _Closed:
                await self.ws.close(code=1000)
                return
            pump = asyncio.create_task(self._pump(subscription))
            receive = asyncio.create_task(self._receive())
            try:
                done, _pending = await asyncio.wait(
                    {pump, receive}, return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    try:
                        task.result()
                    except _Closed:
                        await self.ws.close(code=1000)
                    except WebSocketDisconnect:
                        pass
                    except Exception:  # noqa: BLE001 - a failed task ends the connection
                        logger.warning("guest pump/receive task failed", exc_info=True)
            finally:
                pump.cancel()
                receive.cancel()
