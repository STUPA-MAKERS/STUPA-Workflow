"""WebSocket connection handler for the live-vote channel.

The handler keeps three concerns apart. The first is handshake authentication
and RBAC. The second is the client messages `cast` and `subscribe`. The third
is the broker fan-out from the server to the client.

Authentication at the handshake: the session cookie resolves to a principal.
Without a valid cookie the handler closes with `4401`. The voter channel needs
Gremium membership. The beamer channel needs `session.manage` in the Gremium
of the meeting, or the admin role. On a violation the handler sends
`not_eligible` and closes with `4403`.

The beamer is read-only. It receives only `meeting_state`, `vote_opened`,
`vote_tally` and `vote_closed` through the filtered fan-out. A cast from the
beamer gets `read_only`.

Body draft: while the protokollant of a live meeting types the text of an agenda
item, the client sends `body_draft` frames. The handler checks the sender against
the current protokollant on every frame (so a handover takes effect at once), the
agenda item against the meeting and the UTF-8 size against `AGENDA_BODY_MAX`. It then
publishes the frame on the meeting channel. It writes nothing to the database and
no audit entry. More than `_DRAFT_MAX_PER_SECOND` drafts in one second are dropped
without an answer, and the drafts do not take tokens of the general throttle, so
typing cannot block a cast.

Cast: the distributed lock `vote:{id}:cast:{sub}` serializes the casts of one
voter. `VotingService.cast` then runs. A unique constraint in the database backs
the cast. A ballot never changes after the cast (O11): a second cast gets the error
frame `already_voted`, the same code as the REST 409. The handler broadcasts
`vote_tally`.

Disconnect: `WebSocketDisconnect` tears both tasks down. The broker context
manager closes the subscription.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.livevote.broker import MeetingBroker
from app.modules.livevote.events import (
    BodyDraftEvent,
    BodyDraftMessage,
    CastMessage,
    ErrorEvent,
    MeetingStateEvent,
    ViewersEvent,
    VoteOpenedEvent,
    VoteTallyEvent,
)
from app.modules.livevote.locks import Locker
from app.modules.livevote.models import Meeting, MeetingAgendaItem
from app.modules.livevote.presence import PRESENCE
from app.modules.livevote.schemas import AGENDA_BODY_MAX
from app.modules.livevote.service import BrokerPublisher, MeetingService, meeting_channel
from app.modules.voting.schemas import VoteOut
from app.modules.voting.service import VotingService
from app.shared.errors import AppError, ForbiddenError

# The handshake helpers live in ``app.shared.ws`` (the to-do channel uses them too).
# The names stay importable from here, so the routers and the tests keep their imports.
from app.shared.ws import WS_FORBIDDEN as WS_FORBIDDEN
from app.shared.ws import WS_NOT_FOUND as WS_NOT_FOUND
from app.shared.ws import WS_UNAUTHENTICATED as WS_UNAUTHENTICATED
from app.shared.ws import origin_allowed as origin_allowed
from app.shared.ws import resolve_ws_principal as resolve_ws_principal

logger = logging.getLogger("app.livevote")

# Events the read-only beamer stream lets through. `guest_counts` carries counts and
# the join code only, never a name (#17).
_BEAMER_EVENTS = frozenset(
    {"meeting_state", "vote_opened", "vote_tally", "vote_closed", "vote_lot_drawn", "guest_counts"}
)
# #17: guest events with names. Only a connection of the meeting lead gets them.
_LEAD_EVENTS = frozenset({"guest_requested", "guest_updated"})

# Inbound throttle against denial of service. Every client message hits the
# database or takes a distributed lock. A per-connection token bucket allows
# `_THROTTLE_BURST` frames at once and refills at `_THROTTLE_RATE` tokens per
# second. The handler answers an excess frame with `rate_limited` and drops it
# before any database or lock work.
_THROTTLE_RATE = 5.0
_THROTTLE_BURST = 10.0
# Body drafts of one connection per one-second window. The client sends at most one
# frame per 300 ms, so only a faulty or hostile client reaches the cap.
_DRAFT_MAX_PER_SECOND = 10


async def account_can_act(db: AsyncSession, sub: str) -> bool:
    """Tell whether the account of ``sub`` is still active and not merged."""
    count = await db.scalar(
        select(func.count())
        .select_from(PrincipalRow)
        .where(
            PrincipalRow.sub == sub,
            PrincipalRow.active.is_not(False),
            PrincipalRow.merged_into.is_(None),
        )
    )
    return bool(count)


class LiveVoteConnection:
    """One WebSocket session, voter or beamer, on the `meeting:{id}` channel."""

    def __init__(
        self,
        websocket: WebSocket,
        meeting_id: UUID,
        *,
        beamer: bool,
        principal: Principal,
        meetings: MeetingService,
        voting: VotingService,
        broker: MeetingBroker,
        locker: Locker,
        can_manage: bool = False,
    ) -> None:
        self.ws = websocket
        # #17: the meeting lead gets the guest events with names and the join code.
        self.can_manage = can_manage
        self.meeting_id = meeting_id
        self.beamer = beamer
        self.principal = principal
        self.broker = broker
        self.locker = locker
        self.publisher = BrokerPublisher(broker)
        self.meetings = meetings
        self.voting = voting
        # Token-bucket state of the throttle. The bucket starts with the full
        # burst at connect. It reads `time.monotonic`, which a jump of the wall
        # clock does not affect.
        self._tokens = _THROTTLE_BURST
        self._last_refill = time.monotonic()
        # Fixed one-second window of the body draft cap.
        self._draft_window = time.monotonic()
        self._draft_count = 0

    def _allow_frame(self) -> bool:
        """Take one token of the bucket for an inbound frame.

        The bucket refills in proportion to the elapsed time, up to the burst
        size.

        Returns:
            True when a token was free. On False the caller drops the frame.
        """
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._last_refill = now
        self._tokens = min(_THROTTLE_BURST, self._tokens + elapsed * _THROTTLE_RATE)
        if self._tokens < 1.0:
            return False
        self._tokens -= 1.0
        return True

    def _allow_draft(self) -> bool:
        """Count one body draft in the current one-second window.

        Returns:
            True while the window holds at most `_DRAFT_MAX_PER_SECOND` drafts. On
            False the caller drops the draft without an answer.
        """
        now = time.monotonic()
        if now - self._draft_window >= 1.0:
            self._draft_window = now
            self._draft_count = 0
        self._draft_count += 1
        return self._draft_count <= _DRAFT_MAX_PER_SECOND

    async def _send(self, payload: dict[str, object]) -> None:
        await self.ws.send_json(payload)

    async def _send_error(self, code: str) -> None:
        await self._send(ErrorEvent(code=code).dump())

    async def _end_transaction(self) -> None:
        """End the transaction of one read cycle and give the connection back.

        The socket lives for the whole meeting, and so does its request session.
        A read that does not end its transaction keeps a pool connection "idle in
        transaction" until the disconnect, and a few sockets drain the pool. The
        reads of a cycle write nothing (``VotingService.cast`` commits its own
        write), so a rollback ends the transaction. The rollback also expires every
        loaded row, so the next cycle reads the current values and not the copies
        of the identity map (the session does not expire them on commit). Both
        services share the request session of the socket.
        """
        await self.voting.session.rollback()

    async def _send_state(self) -> None:
        """Send the current state on connect and on a `subscribe` reconnect."""
        try:
            meeting = await self.meetings.get(self.meeting_id)
            vote = await self.meetings.open_vote(self.meeting_id)
            vote_out = None if vote is None else await self.voting.get(vote.id)
        finally:
            await self._end_transaction()
        await self._send(
            MeetingStateEvent(
                activeApplicationId=meeting.active_application_id,
                currentAgendaItemId=meeting.current_agenda_item_id,
                status=meeting.status,
            ).dump()
        )
        if vote_out is None:
            return
        await self._send(VoteOpenedEvent.from_vote(vote_out, replay=True).dump())
        # `from_vote` applies the rule that a secret vote reveals the counts
        # only after the close.
        await self._send(VoteTallyEvent.from_vote(vote_out).dump())

    async def _handle_cast(self, raw: dict[str, object]) -> None:
        if self.beamer:
            await self._send_error("read_only")
            return
        try:
            msg = CastMessage.model_validate(raw)
        except ValidationError:
            await self._send_error("invalid_message")
            return
        try:
            vote_out = await self._cast(msg)
        finally:
            # Every path of the cast reads the database: the vote, the account and
            # the tally after the cast. End that transaction on every path, also
            # after a refused cast, whose partial work the rollback discards.
            await self._end_transaction()
        if vote_out is not None:
            await self.publisher.vote_tally(vote_out)

    async def _cast(self, msg: CastMessage) -> VoteOut | None:
        """Run one cast and return the vote after it, or None after an error frame."""
        # Channel binding as defense in depth. The vote MUST belong to the meeting
        # of this connection. The handler rejects a vote of another meeting, and an
        # unknown vote, before the lock and the database. `VotingService.cast`
        # checks the eligibility again.
        try:
            target = await self.voting.get(msg.vote_id)
        except AppError:
            await self._send_error("not_eligible")
            return None
        if target.meeting_id != self.meeting_id:
            await self._send_error("not_eligible")
            return None
        # Lock the own cast and the delegated cast apart. Both casts are valid.
        suffix = ":proxy" if msg.as_delegation else ""
        lock_key = f"vote:{msg.vote_id}:cast:{self.principal.sub}{suffix}"
        async with self.locker.acquire(lock_key) as acquired:
            if not acquired:
                await self._send_error("locked")
                return None
            # The socket resolved the principal at the handshake. Since then an admin
            # may have deactivated the account or merged it into another one, whose
            # ballots now carry this vote. Check the row again before every cast, so an
            # open socket cannot vote for a locked account (or vote twice for a person).
            if not await account_can_act(self.voting.session, self.principal.sub):
                await self._send_error("account_inactive")
                return None
            try:
                await self.voting.cast(
                    msg.vote_id,
                    self.principal,
                    msg.choice,
                    now=datetime.now(UTC),
                    as_delegation=msg.as_delegation,
                )
            except ForbiddenError:
                await self._send_error("not_eligible")
                return None
            except AppError as exc:
                await self._send_error(exc.code or "error")
                return None
        return await self.voting.get(msg.vote_id)

    async def _is_live_protokollant(self) -> bool:
        """Read whether the principal keeps the minutes of this live meeting now.

        The check reads the meeting row for every draft, so the old protokollant
        loses the right with the commit of a handover. A deactivated or merged
        account does not pass. The scope cap of ``protocol.write`` applies.
        """
        if not self.principal.scope_allows("protocol.write"):
            return False
        count = await self.voting.session.scalar(
            select(func.count())
            .select_from(Meeting)
            .join(PrincipalRow, PrincipalRow.id == Meeting.protokollant_id)
            .where(
                Meeting.id == self.meeting_id,
                Meeting.status == "live",
                PrincipalRow.sub == self.principal.sub,
                PrincipalRow.active.is_not(False),
                PrincipalRow.merged_into.is_(None),
            )
        )
        return bool(count)

    async def _item_in_meeting(self, item_id: UUID) -> bool:
        """Read whether the agenda item belongs to the meeting of this connection."""
        count = await self.voting.session.scalar(
            select(func.count())
            .select_from(MeetingAgendaItem)
            .where(
                MeetingAgendaItem.id == item_id,
                MeetingAgendaItem.meeting_id == self.meeting_id,
            )
        )
        return bool(count)

    async def _handle_body_draft(self, raw: dict[str, object]) -> None:
        """Check one body draft and publish it on the meeting channel."""
        if not self._allow_draft():
            return
        if self.beamer:
            await self._send_error("read_only")
            return
        try:
            msg = BodyDraftMessage.model_validate(raw)
        except ValidationError:
            await self._send_error("invalid_message")
            return
        # The cap counts UTF-8 bytes, not characters: a character can take up to 4
        # bytes, and the frame travels as bytes to every viewer.
        if len(msg.body.encode("utf-8", "surrogatepass")) > AGENDA_BODY_MAX:
            await self._send_error("too_large")
            return
        try:
            if not await self._is_live_protokollant():
                await self._send_error("not_protokollant")
                return
            if not await self._item_in_meeting(msg.agenda_item_id):
                await self._send_error("unknown_agenda_item")
                return
        finally:
            await self._end_transaction()
        await self.broker.publish(
            meeting_channel(self.meeting_id),
            BodyDraftEvent(agendaItemId=msg.agenda_item_id, body=msg.body, seq=msg.seq).dump(),
        )

    async def _handle_message(self, raw: dict[str, object]) -> None:
        kind = raw.get("type")
        if kind == "subscribe":
            await self._send_state()
        elif kind == "cast":
            await self._handle_cast(raw)
        else:
            await self._send_error("unknown_type")

    def _filter(self, message: dict[str, object]) -> dict[str, object] | None:
        """Return the message as this connection may see it, or None to drop it.

        The beamer gets its fixed event set. A guest event with names goes to the
        meeting lead only. A member without ``canManage`` gets the guest counts
        without the join code and without the open requests (#17).
        """
        kind = message.get("type")
        if self.beamer:
            return message if kind in _BEAMER_EVENTS else None
        if kind in _LEAD_EVENTS:
            return message if self.can_manage else None
        if kind == "guest_counts" and not self.can_manage:
            return {**message, "joinCode": None, "pendingGuests": 0}
        return message

    async def _pump(self, subscription: object) -> None:
        async for message in subscription:  # type: ignore[attr-defined]
            filtered = self._filter(message)
            if filtered is not None:
                await self._send(filtered)

    async def _receive(self) -> None:
        while True:
            try:
                raw = await self.ws.receive_json()
            except json.JSONDecodeError:
                # A frame that is not JSON keeps the connection open.
                await self._send_error("invalid_message")
                continue
            # A body draft has its own cap and does not take a token of the
            # general throttle, so a long run of typing cannot block a cast.
            if isinstance(raw, dict) and raw.get("type") == "body_draft":
                await self._handle_body_draft(raw)
                continue
            # Throttle before any database or lock work. The handler drops the
            # excess frames of a flooding client and keeps the connection open.
            if not self._allow_frame():
                await self._send_error("rate_limited")
                continue
            if isinstance(raw, dict):
                await self._handle_message(raw)
            else:
                await self._send_error("invalid_message")

    async def run(self) -> None:
        """Open the subscription and send the initial state.

        The connection then fans out and receives until the disconnect.
        """
        channel = meeting_channel(self.meeting_id)
        async with self.broker.subscribe(channel) as subscription:
            await self._send_state()
            # Register a voter connection and broadcast the roster. The
            # subscription already exists, so this broadcast is also the first
            # snapshot for the new client. A beamer does not count, because it is
            # a display and not a person. The event filter of the beamer hides
            # `viewers`.
            connection_id: str | None = None
            if not self.beamer:
                name = (
                    self.principal.display_name
                    or self.principal.email
                    or self.principal.sub
                )
                connection_id, names = PRESENCE.join(
                    self.meeting_id, self.principal.sub, name
                )
                await self.broker.publish(
                    channel, ViewersEvent(viewers=names).dump()
                )
            pump = asyncio.create_task(self._pump(subscription))
            receive = asyncio.create_task(self._receive())
            try:
                # Race both tasks with FIRST_COMPLETED. `_pump` can end first on
                # a send error or on a serialization error. The connection then
                # goes down. A client must never stop receiving broadcasts on an
                # open socket. An end of `_receive` first is a normal disconnect.
                done, _pending = await asyncio.wait(
                    {pump, receive}, return_when=asyncio.FIRST_COMPLETED
                )
                # Read the exception of the finished task. Without this call it
                # stays hidden. A disconnect is expected. A dead pump is logged.
                for task in done:
                    try:
                        task.result()
                    except WebSocketDisconnect:
                        pass
                    except Exception:  # pump failure tears the connection down
                        logger.warning(
                            "live-vote pump/receive task failed", exc_info=True
                        )
            finally:
                pump.cancel()
                receive.cancel()
                if connection_id is not None:
                    names = PRESENCE.leave(self.meeting_id, connection_id)
                    try:
                        await self.broker.publish(
                            channel, ViewersEvent(viewers=names).dump()
                        )
                    except Exception:  # leaving must not break the close
                        logger.debug("viewers broadcast on leave failed", exc_info=True)
