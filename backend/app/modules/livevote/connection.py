"""WebSocket-Verbindungs-Handler für den Live-Vote-Kanal (api.md §4, flows §5).

Trennt Auth/RBAC (Handshake), den Empfang von Client-Nachrichten (``cast``/
``subscribe``) und den Broker-Fan-out (Server→Client) sauber:

* **Auth am Handshake** (security.md, Risiko »Cookie beim Upgrade«): Session-Cookie →
  Principal. Kein Principal → Close ``4401``. Voter-Kanal verlangt Gruppen-
  Mitgliedschaft des Sitzungs-Gremiums; Beamer-Kanal verlangt ``meeting.manage``.
  Verstoß ⇒ ``{"type":"error","code":"not_eligible"}`` + Close ``4403``.
* **Beamer = read-only**: erhält nur ``meeting_state|vote_opened|vote_tally|
  vote_closed`` (Fan-out gefiltert) und darf **nicht** casten (``read_only``).
* **Cast**: serialisiert pro Wähler über den verteilten Lock ``vote:{id}:cast:{sub}``,
  dann ``VotingService.cast`` (idempotent, DB-unique) → ``vote_tally`` broadcast.
* **Disconnect**: beide Tasks werden bei ``WebSocketDisconnect`` sauber abgeräumt
  (Abo via Broker-Context-Manager geschlossen).
"""

from __future__ import annotations

import asyncio
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
    VoteOpenedEvent,
    VoteTallyEvent,
)
from app.modules.livevote.locks import Locker
from app.modules.livevote.service import BrokerPublisher, MeetingService, meeting_channel
from app.modules.voting.service import VotingService
from app.settings import Settings
from app.shared.errors import AppError, ForbiddenError

# Events, die der read-only Beamer-Stream durchlässt (api.md §4).
_BEAMER_EVENTS = frozenset(
    {"meeting_state", "vote_opened", "vote_tally", "vote_closed"}
)
# Close-Codes (anwendungsdefiniert, 4000–4999).
WS_UNAUTHENTICATED = 4401
WS_FORBIDDEN = 4403
WS_NOT_FOUND = 4404


async def resolve_ws_principal(
    websocket: WebSocket, db: AsyncSession, settings: Settings
) -> Principal | None:
    """Session-Cookie am WS-Handshake → Principal (``None`` ohne gültige Session)."""
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
    if row is None:
        return None
    return await rbac.resolve_principal(db, row, now)


class LiveVoteConnection:
    """Eine WS-Sitzung (Voter **oder** Beamer) auf dem Kanal ``meeting:{id}``."""

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

    # ---------------------------------------------------------------- helpers
    async def _send(self, payload: dict[str, object]) -> None:
        await self.ws.send_json(payload)

    async def _send_error(self, code: str) -> None:
        await self._send(ErrorEvent(code=code).dump())

    async def _send_state(self) -> None:
        """Aktuellen State liefern (Connect + ``subscribe``-Reconnect, flows §5)."""
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
            ).dump()
        )
        await self._send(
            VoteTallyEvent(
                voteId=vote_out.id,
                counts=vote_out.tally.counts,
                eligible=vote_out.tally.eligible,
                quorumMet=vote_out.tally.quorum_met,
                leading=vote_out.tally.leading,
            ).dump()
        )

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
        lock_key = f"vote:{msg.vote_id}:cast:{self.principal.sub}"
        async with self.locker.acquire(lock_key) as acquired:
            if not acquired:
                await self._send_error("locked")
                return
            try:
                await self.voting.cast(
                    msg.vote_id, self.principal, msg.choice, now=datetime.now(UTC)
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
            raw = await self.ws.receive_json()
            if isinstance(raw, dict):
                await self._handle_message(raw)
            else:
                await self._send_error("invalid_message")

    async def run(self) -> None:
        """Abo öffnen, initialen State senden, Fan-out + Empfang bis Disconnect."""
        channel = meeting_channel(self.meeting_id)
        async with self.broker.subscribe(channel) as subscription:
            await self._send_state()
            pump = asyncio.create_task(self._pump(subscription))
            receive = asyncio.create_task(self._receive())
            try:
                await receive
            except WebSocketDisconnect:
                pass
            finally:
                pump.cancel()
                receive.cancel()
