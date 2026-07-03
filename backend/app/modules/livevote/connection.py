"""WebSocket connection handler for the live-vote channel.

Separates handshake auth/RBAC, client message handling (``cast``/``subscribe``)
and broker fan-out (server→client):

* **Auth at handshake**: session cookie → principal; none → close ``4401``.
  The voter channel requires gremium membership, the beamer channel
  ``meeting.manage``; violation ⇒ ``not_eligible`` error + close ``4403``.
* **Beamer is read-only**: receives only ``meeting_state|vote_opened|vote_tally|
  vote_closed`` (filtered fan-out) and must not cast (``read_only``).
* **Cast**: serialized per voter via the distributed lock
  ``vote:{id}:cast:{sub}``, then ``VotingService.cast`` (idempotent, DB-unique)
  → ``vote_tally`` broadcast.
* **Disconnect**: both tasks are torn down cleanly on ``WebSocketDisconnect``
  (subscription closed via the broker context manager).
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

# Inbound throttle (DoS protection): every client message hits the DB or takes a
# distributed lock. A per-connection token bucket allows ``_THROTTLE_BURST``
# frames at once, refilled at ``_THROTTLE_RATE`` tokens/second; excess frames get
# ``rate_limited`` and are dropped without touching DB/lock.
_THROTTLE_RATE = 5.0
_THROTTLE_BURST = 10.0


def _allowed_origins(settings: Settings) -> set[str]:
    """Allowed WS origins: the public base URL plus configured CORS origins.

    Normalized to ``scheme://host[:port]`` (no path/trailing slash), matching a
    browser's ``Origin`` header."""
    origins = {o.rstrip("/") for o in settings.cors_allow_origins if o}
    base = (settings.public_base_url or "").rstrip("/")
    if base:
        origins.add(base)
    return origins


def origin_allowed(origin: str | None, settings: Settings) -> bool:
    """CSRF protection for the WS handshake.

    The double-submit CSRF middleware does not run for WebSocket upgrades, so a
    cookie-authenticated cross-origin upgrade (CSWSH) would get through; the
    ``Origin`` header is therefore checked here, independent of SameSite.

    A missing header (non-browser clients: native/MCP/CLI/tests) falls back to
    the cookie/session check alone — those clients are not CSRF-prone. If set,
    it MUST be on the allowlist. With no configured origins (default) there is
    no gate.
    """
    if origin is None:
        return True
    allowed = _allowed_origins(settings)
    if not allowed:
        return True
    return origin.rstrip("/") in allowed


async def _neutralize_close(websocket: WebSocket) -> None:
    """Make ``websocket.close`` a no-op (idempotent close).

    After our 4403 close, the router's follow-up ``close(4401)`` would raise
    ``RuntimeError`` in Starlette ("Cannot call send once a close message has
    been sent"); replacing the bound method silences the double close."""

    async def _noop(code: int = 1000, reason: str | None = None) -> None:  # noqa: ARG001
        return None

    websocket.close = _noop  # type: ignore[method-assign]


async def resolve_ws_principal(
    websocket: WebSocket, db: AsyncSession, settings: Settings
) -> Principal | None:
    """Resolve the session cookie at the WS handshake to a principal (``None`` if invalid).

    Before the cookie check the ``Origin`` header is validated against the
    allowlist (CSWSH protection, see :func:`origin_allowed`); on mismatch the
    handshake closes with ``4403`` and returns ``None``."""
    # CSWSH at upgrade: foreign origin ⇒ 4403 BEFORE the cookie check; we close
    # here ourselves and turn the router's later ``close`` into a no-op.
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
    """One WS session (voter or beamer) on the ``meeting:{id}`` channel."""

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
        # Token-bucket state (DoS throttle): full burst capacity at connect,
        # clocked with ``time.monotonic`` — robust against wall-clock jumps.
        self._tokens = _THROTTLE_BURST
        self._last_refill = time.monotonic()

    def _allow_frame(self) -> bool:
        """Token bucket: ``True`` if an inbound frame may take a token.

        Refills proportionally to elapsed time (capped at the burst), then takes
        one token; if none is left the caller drops the frame."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._last_refill = now
        self._tokens = min(_THROTTLE_BURST, self._tokens + elapsed * _THROTTLE_RATE)
        if self._tokens < 1.0:
            return False
        self._tokens -= 1.0
        return True

    # ---------------------------------------------------------------- helpers
    async def _send(self, payload: dict[str, object]) -> None:
        await self.ws.send_json(payload)

    async def _send_error(self, code: str) -> None:
        await self._send(ErrorEvent(code=code).dump())

    async def _send_state(self) -> None:
        """Send the current state (connect and ``subscribe`` reconnect)."""
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
        # ``from_vote`` enforces the counts-only-after-close rule for secret votes.
        await self._send(VoteTallyEvent.from_vote(vote_out).dump())

    # ------------------------------------------------------------------ cast
    async def _handle_cast(self, raw: dict[str, object]) -> None:
        if self.beamer:
            await self._send_error("read_only")
            return
        try:
            msg = CastMessage.model_validate(raw)
        except ValidationError:
            await self._send_error("invalid_message")
            return
        # Defense-in-depth channel binding: the vote MUST belong to the meeting this
        # connection is authorized for; cross-meeting or unknown votes are rejected
        # before lock/DB even though ``VotingService.cast`` re-checks eligibility.
        try:
            target = await self.voting.get(msg.vote_id)
        except AppError:
            await self._send_error("not_eligible")
            return
        if target.meeting_id != self.meeting_id:
            await self._send_error("not_eligible")
            return
        # Lock own and delegated casts separately (two legitimate casts).
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

    # ------------------------------------------------------------------ loop
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
                # Non-JSON frame: connection stays open, client gets an error.
                await self._send_error("invalid_message")
                continue
            # DoS throttle before any DB/lock work: excess frames of a flooding
            # client are dropped, the connection stays open.
            if not self._allow_frame():
                await self._send_error("rate_limited")
                continue
            if isinstance(raw, dict):
                await self._handle_message(raw)
            else:
                await self._send_error("invalid_message")

    async def run(self) -> None:
        """Open the subscription, send initial state, fan out and receive until disconnect."""
        channel = meeting_channel(self.meeting_id)
        async with self.broker.subscribe(channel) as subscription:
            await self._send_state()
            # Presence: register voter connections and broadcast the roster — the
            # own broadcast doubles as the fresh client's initial snapshot (the
            # subscription already exists). Beamers do not count (display, not a
            # person); their event filter hides `viewers`.
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
                # Race both tasks (FIRST_COMPLETED): if ``_pump`` ends first (e.g.
                # a send/serialization error) the connection is torn down — the
                # client must not silently stop receiving broadcasts on an open
                # socket. ``_receive`` ending first is a normal disconnect.
                done, _pending = await asyncio.wait(
                    {pump, receive}, return_when=asyncio.FIRST_COMPLETED
                )
                # Fetch the finished task's exception (otherwise swallowed) —
                # disconnect is expected, a dead pump is logged.
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
