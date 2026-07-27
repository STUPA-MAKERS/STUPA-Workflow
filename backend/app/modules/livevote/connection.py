"""WebSocket connection handler for the live-vote channel.

The handler keeps three concerns apart. The first is handshake authentication
and RBAC. The second is the client messages `cast` and `subscribe`. The third
is the broker fan-out from the server to the client.

Authentication at the handshake: the session cookie resolves to a principal.
Without a valid cookie the handler closes with `4401`. The voter channel needs
Gremium membership. The beamer channel needs `meeting.manage`. On a violation
the handler sends `not_eligible` and closes with `4403`.

The beamer is read-only. It receives only `meeting_state`, `vote_opened`,
`vote_tally` and `vote_closed` through the filtered fan-out. A cast from the
beamer gets `read_only`.

Cast: the distributed lock `vote:{id}:cast:{sub}` serializes the casts of one
voter. `VotingService.cast` then runs. The cast is idempotent, because a unique
constraint in the database backs it. The handler broadcasts `vote_tally`.

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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth import rbac, sessions
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.livevote.broker import MeetingBroker
from app.modules.livevote.events import (
    CastMessage,
    ErrorEvent,
    MeetingStateEvent,
    ViewersEvent,
    VoteOpenedEvent,
    VoteTallyEvent,
)
from app.modules.livevote.locks import Locker
from app.modules.livevote.presence import PRESENCE
from app.modules.livevote.service import BrokerPublisher, MeetingService, meeting_channel
from app.modules.voting.service import VotingService
from app.settings import Settings
from app.shared.errors import AppError, ForbiddenError

logger = logging.getLogger("app.livevote")

# Events the read-only beamer stream lets through.
_BEAMER_EVENTS = frozenset(
    {"meeting_state", "vote_opened", "vote_tally", "vote_closed"}
)
# Application-defined close codes (4000–4999).
WS_UNAUTHENTICATED = 4401
WS_FORBIDDEN = 4403
WS_NOT_FOUND = 4404

# Inbound throttle against denial of service. Every client message hits the
# database or takes a distributed lock. A per-connection token bucket allows
# `_THROTTLE_BURST` frames at once and refills at `_THROTTLE_RATE` tokens per
# second. The handler answers an excess frame with `rate_limited` and drops it
# before any database or lock work.
_THROTTLE_RATE = 5.0
_THROTTLE_BURST = 10.0


def _allowed_origins(settings: Settings) -> set[str]:
    """Return the allowed WebSocket origins.

    The set holds the public base URL and the configured CORS origins. Every
    entry is normalized to `scheme://host[:port]` without a path and without a
    trailing slash. This matches the `Origin` header of a browser.
    """
    origins = {o.rstrip("/") for o in settings.cors_allow_origins if o}
    base = (settings.public_base_url or "").rstrip("/")
    if base:
        origins.add(base)
    return origins


def origin_allowed(origin: str | None, settings: Settings) -> bool:
    """Protect the WebSocket handshake against CSRF.

    The double-submit CSRF middleware does not run for a WebSocket upgrade. A
    cookie-authenticated cross-origin upgrade (CSWSH) would pass. This function
    therefore checks the `Origin` header here, independent of SameSite.

    A client that is not a browser (native, MCP, CLI or test) sends no `Origin`
    header. The handshake then relies on the cookie and session check alone,
    because such a client is not open to CSRF. A header that is present MUST be
    on the allowlist. Without configured origins, the default, there is no gate.
    """
    if origin is None:
        return True
    allowed = _allowed_origins(settings)
    if not allowed:
        return True
    return origin.rstrip("/") in allowed


async def _neutralize_close(websocket: WebSocket) -> None:
    """Make `websocket.close` a no-op, so a second close does nothing.

    After the 4403 close of this module, the follow-up `close(4401)` of the
    router would raise `RuntimeError` in Starlette. The message reads "Cannot
    call send once a close message has been sent". The replaced bound method
    absorbs the second close.
    """

    async def _noop(code: int = 1000, reason: str | None = None) -> None:  # noqa: ARG001
        return None

    websocket.close = _noop  # type: ignore[method-assign]


async def resolve_ws_principal(
    websocket: WebSocket, db: AsyncSession, settings: Settings
) -> Principal | None:
    """Resolve the session cookie of the WebSocket handshake to a principal.

    The function checks the `Origin` header against the allowlist first. See
    `origin_allowed` for the CSWSH protection. On a mismatch it closes the
    handshake with `4403`.

    Returns:
        The principal, or `None` when the origin, the cookie or the session is
        invalid.
    """
    # Close here on a foreign origin, then neutralize the later close of the
    # router.
    origin = websocket.headers.get("origin")
    if not origin_allowed(origin, settings):
        logger.info("ws handshake rejected: disallowed origin %r", origin)
        await websocket.close(code=WS_FORBIDDEN)
        await _neutralize_close(websocket)
        return None
    cookie = websocket.cookies.get(settings.session_cookie_name)
    if not cookie:
        return None
    now = datetime.now(UTC)
    session = await sessions.load_principal_session(
        db,
        secret=settings.session_secret,
        cookie_value=cookie,
        now=now,
        max_age=settings.session_ttl_hours * 3600,
    )
    if session is None:
        return None
    row = (
        await db.execute(
            select(PrincipalRow).where(PrincipalRow.id == session.principal_id)
        )
    ).scalar_one_or_none()
    if row is None or row.active is False:
        return None
    return await rbac.resolve_principal(db, row, now)


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
    ) -> None:
        self.ws = websocket
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

    async def _send(self, payload: dict[str, object]) -> None:
        await self.ws.send_json(payload)

    async def _send_error(self, code: str) -> None:
        await self._send(ErrorEvent(code=code).dump())

    async def _send_state(self) -> None:
        """Send the current state on connect and on a `subscribe` reconnect."""
        meeting = await self.meetings.get(self.meeting_id)
        await self._send(
            MeetingStateEvent(
                activeApplicationId=meeting.active_application_id,
                status=meeting.status,
            ).dump()
        )
        vote = await self.meetings.open_vote(self.meeting_id)
        if vote is None:
            return
        vote_out = await self.voting.get(vote.id)
        await self._send(
            VoteOpenedEvent(
                voteId=vote_out.id,
                applicationId=vote_out.application_id,
                options=vote_out.config.options,
                closesAt=vote_out.closes_at,
                secret=vote_out.secret,
            ).dump()
        )
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
        # Channel binding as defense in depth. The vote MUST belong to the meeting
        # of this connection. The handler rejects a vote of another meeting, and an
        # unknown vote, before the lock and the database. `VotingService.cast`
        # checks the eligibility again.
        try:
            target = await self.voting.get(msg.vote_id)
        except AppError:
            await self._send_error("not_eligible")
            return
        if target.meeting_id != self.meeting_id:
            await self._send_error("not_eligible")
            return
        # Lock the own cast and the delegated cast apart. Both casts are valid.
        suffix = ":proxy" if msg.as_delegation else ""
        lock_key = f"vote:{msg.vote_id}:cast:{self.principal.sub}{suffix}"
        async with self.locker.acquire(lock_key) as acquired:
            if not acquired:
                await self._send_error("locked")
                return
            try:
                await self.voting.cast(
                    msg.vote_id,
                    self.principal,
                    msg.choice,
                    now=datetime.now(UTC),
                    as_delegation=msg.as_delegation,
                )
            except ForbiddenError:
                await self.voting.session.rollback()
                await self._send_error("not_eligible")
                return
            except AppError as exc:
                await self.voting.session.rollback()
                await self._send_error(exc.code or "error")
                return
        vote_out = await self.voting.get(msg.vote_id)
        await self.publisher.vote_tally(vote_out)

    async def _handle_message(self, raw: dict[str, object]) -> None:
        kind = raw.get("type")
        if kind == "subscribe":
            await self._send_state()
        elif kind == "cast":
            await self._handle_cast(raw)
        else:
            await self._send_error("unknown_type")

    async def _pump(self, subscription: object) -> None:
        async for message in subscription:  # type: ignore[attr-defined]
            if self.beamer and message.get("type") not in _BEAMER_EVENTS:
                continue
            await self._send(message)

    async def _receive(self) -> None:
        while True:
            try:
                raw = await self.ws.receive_json()
            except json.JSONDecodeError:
                # A frame that is not JSON keeps the connection open.
                await self._send_error("invalid_message")
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
                    except Exception:  # noqa: BLE001 — pump failure tears the connection down
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
                    except Exception:  # noqa: BLE001 — leaving must not break the close
                        logger.debug("viewers broadcast on leave failed", exc_info=True)
