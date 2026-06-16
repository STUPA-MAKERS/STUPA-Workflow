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

# Events, die der read-only Beamer-Stream durchlässt (api.md §4).
_BEAMER_EVENTS = frozenset(
    {"meeting_state", "vote_opened", "vote_tally", "vote_closed"}
)
# Close-Codes (anwendungsdefiniert, 4000–4999).
WS_UNAUTHENTICATED = 4401
WS_FORBIDDEN = 4403
WS_NOT_FOUND = 4404

# Inbound-Throttle (DoS-Schutz, security.md): jede Client-Nachricht (``cast``/
# ``subscribe``) trifft die DB bzw. nimmt einen verteilten Lock. Ein Token-Bucket
# begrenzt die Rate je Verbindung — ``_THROTTLE_BURST`` Frames sofort, danach
# nachfüllen mit ``_THROTTLE_RATE`` Tokens/Sekunde. Überzählige Frames bekommen
# ``rate_limited`` und werden verworfen (kein DB/Lock-Zugriff).
_THROTTLE_RATE = 5.0
_THROTTLE_BURST = 10.0


def _allowed_origins(settings: Settings) -> set[str]:
    """Erlaubte WS-Origins: die öffentliche Basis-URL + konfigurierte CORS-Origins.

    Normalisiert auf ``scheme://host[:port]`` (ohne Pfad/Trailing-Slash), passend zum
    ``Origin``-Header eines Browsers."""
    origins = {o.rstrip("/") for o in settings.cors_allow_origins if o}
    base = (settings.public_base_url or "").rstrip("/")
    if base:
        origins.add(base)
    return origins


def origin_allowed(origin: str | None, settings: Settings) -> bool:
    """CSRF-Schutz für den WS-Handshake (security.md, Risiko »Cookie beim Upgrade«).

    Die CSRF-Middleware (Double-Submit) läuft für WebSocket-Upgrades NICHT — ein
    cookie-authentifizierter Cross-Origin-Upgrade (forged-WebSocket/CSWSH) käme sonst
    durch. Deshalb prüfen wir den ``Origin``-Header hier eigenständig (unabhängig von
    SameSite, das ältere Browser nicht durchsetzen).

    Fehlt der Header komplett (Nicht-Browser-Clients: native/MCP/CLI/Tests senden
    keinen ``Origin``), greift der Cookie-/Session-Check als alleiniges Gate — diese
    Clients sind nicht CSRF-anfällig. Ist er gesetzt, MUSS er auf der Allowlist stehen.
    Ohne konfigurierte Origins (Default) bleibt das Verhalten unverändert (kein Gate).
    """
    if origin is None:
        return True
    allowed = _allowed_origins(settings)
    if not allowed:
        return True
    return origin.rstrip("/") in allowed


async def _neutralize_close(websocket: WebSocket) -> None:
    """``websocket.close`` zum No-op machen (idempotenter Close).

    Nach unserem 4403-Close würde der nachgelagerte ``close(4401)`` des Routers auf der
    bereits geschlossenen Verbindung mit ``RuntimeError`` scheitern (Starlette: »Cannot
    call send once a close message has been sent«). Wir ersetzen die Bound-Method durch
    einen No-op, damit der Doppel-Close geräuschlos verpufft (der Client hat den 4403
    bereits erhalten)."""

    async def _noop(code: int = 1000, reason: str | None = None) -> None:  # noqa: ARG001
        return None

    websocket.close = _noop  # type: ignore[method-assign]


async def resolve_ws_principal(
    websocket: WebSocket, db: AsyncSession, settings: Settings
) -> Principal | None:
    """Session-Cookie am WS-Handshake → Principal (``None`` ohne gültige Session).

    Vor dem Cookie-Check wird der ``Origin``-Header gegen die Allowlist geprüft
    (CSWSH-Schutz, s. :func:`origin_allowed`): bei Mismatch schließt der Handshake
    sofort mit ``4403`` und gibt ``None`` zurück."""
    # CSRF/CSWSH am Upgrade: fremder Origin ⇒ 4403, noch VOR dem Cookie. Den
    # ``close``-Aufruf des Routers (würde sonst doppelt schließen) entschärfen wir,
    # indem wir hier selbst schließen und ``close`` zum No-op machen.
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
        # Token-Bucket-Zustand (DoS-Throttle): volle Burst-Kapazität zum Verbindungs-
        # start, monoton getaktet (``time.monotonic``) — robust gegen Wall-Clock-Sprünge
        # und unabhängig von einer laufenden Event-Loop.
        self._tokens = _THROTTLE_BURST
        self._last_refill = time.monotonic()

    def _allow_frame(self) -> bool:
        """Token-Bucket: ``True``, wenn ein Inbound-Frame ein Token entnehmen darf.

        Füllt zunächst anteilig zur verstrichenen Zeit nach (gedeckelt auf den Burst),
        entnimmt dann ein Token. Reicht es nicht, ist die Verbindung über ihrem
        Ratenlimit → ``False`` (der Aufrufer verwirft den Frame)."""
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
                secret=vote_out.secret,
            ).dump()
        )
        # ``from_vote`` setzt die »Counts erst bei Close«-Regel für geheime Votes durch.
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
        # Eigene und Vertretungs-Abgabe getrennt locken (zwei legitime Casts).
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
                # Nicht-JSON-Frame: Verbindung bleibt offen, Client bekommt error.
                await self._send_error("invalid_message")
                continue
            # DoS-Throttle (vor jeder DB-/Lock-berührenden Verarbeitung): überzählige
            # Frames eines flutenden Clients werden verworfen, die Verbindung bleibt
            # offen (legitimer Burst läuft normal weiter).
            if not self._allow_frame():
                await self._send_error("rate_limited")
                continue
            if isinstance(raw, dict):
                await self._handle_message(raw)
            else:
                await self._send_error("invalid_message")

    async def run(self) -> None:
        """Abo öffnen, initialen State senden, Fan-out + Empfang bis Disconnect."""
        channel = meeting_channel(self.meeting_id)
        async with self.broker.subscribe(channel) as subscription:
            await self._send_state()
            # Presence (#live-viewers): Voter-Verbindungen registrieren und den
            # Stand broadcasten — der eigene Broadcast liefert dem frischen Client
            # zugleich den Initial-Snapshot (Abo besteht bereits). Beamer zählen
            # nicht (Anzeige, keine Person); ihr Event-Filter blendet `viewers` aus.
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
                # Beide Tasks RENNEN gegeneinander (FIRST_COMPLETED): endet ``_pump``
                # zuerst (z. B. ``send_json``-/Serialisierungsfehler), reißt das die
                # Verbindung ab — sonst stoppte der Client still den Broadcast-Empfang,
                # während der Socket offen bliebe. Endet ``_receive`` zuerst
                # (Disconnect), läuft alles wie gehabt.
                done, _pending = await asyncio.wait(
                    {pump, receive}, return_when=asyncio.FIRST_COMPLETED
                )
                # Exception des fertigen Tasks abrufen (sonst geschluckt) — Disconnect
                # ist erwartet, ein toter Pump wird geloggt.
                for task in done:
                    try:
                        task.result()
                    except WebSocketDisconnect:
                        pass
                    except Exception:  # noqa: BLE001 — Pump-Fehler reißt die Verbindung ab
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
                    except Exception:  # noqa: BLE001 — Abgang darf den Close nicht stören
                        logger.debug("viewers broadcast on leave failed", exc_info=True)
