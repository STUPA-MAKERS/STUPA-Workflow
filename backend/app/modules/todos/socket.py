"""The live channel of the boards: ``WS /api/ws/todos``.

The handshake authenticates like the meeting socket (``app.shared.ws``): the
``Origin`` header must be on the allowlist, and only the session cookie counts,
never an OAuth token. Without a session the socket closes with ``4401``; above the
cap of ``MAX_CONNECTIONS_PER_PRINCIPAL`` open sockets of one account (per process)
the server sends ``too_many_connections`` and closes with ``4403``.

Client frames: ``{"type": "subscribe", "boardIds": [...]}`` replaces the set of
boards (at most ``MAX_BOARDS``). The server keeps the boards that the principal
reads (``BoardAccess.can_read``, checked again on every subscribe) and drops an
unreadable or unknown id without a word; it answers ``{"type": "subscribed",
"boardIds": [...]}`` with the kept ids. Then it forwards the pings of these boards
(see ``live``). A ping carries ids only, so a board that the viewer lost since the
last subscribe says "changed", and the REST read then answers 404.

Errors keep the socket open: ``invalid_message`` (not JSON, or a bad frame),
``too_many_boards``, ``unknown_type`` and ``rate_limited`` (a token bucket per
socket, as on the meeting socket). Every subscribe ends its transaction, because
the socket keeps its request session for its whole life, and an open transaction
would hold a pool connection.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import DbSession
from app.modules.auth.principal import Principal
from app.modules.livevote.broker import PatternBroker, Subscription
from app.modules.todos.access import BoardAccess
from app.modules.todos.live import CHANNEL_PATTERN, todo_broker
from app.modules.todos.models import TodoBoard
from app.settings import Settings, get_settings
from app.shared.ws import WS_FORBIDDEN, WS_UNAUTHENTICATED, resolve_ws_principal

logger = logging.getLogger("app.todos.live")

ws_router = APIRouter(tags=["todos"])

#: The most boards that one subscribe names.
MAX_BOARDS = 100
#: The open sockets of one account per process (a denial-of-service guard).
MAX_CONNECTIONS_PER_PRINCIPAL = 5
_connection_counts: dict[str, int] = {}

# The inbound throttle of the meeting socket: a burst of 10 frames, then 5 per second.
_THROTTLE_RATE = 5.0
_THROTTLE_BURST = 10.0


class SubscribeMessage(BaseModel):
    """``{"type": "subscribe", "boardIds": [...]}``: the boards of the socket."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    type: Literal["subscribe"]
    board_ids: list[uuid.UUID] = Field(default_factory=list, alias="boardIds")


def _try_acquire_slot(sub: str) -> bool:
    current = _connection_counts.get(sub, 0)
    if current >= MAX_CONNECTIONS_PER_PRINCIPAL:
        return False
    _connection_counts[sub] = current + 1
    return True


def _release_slot(sub: str) -> None:
    current = _connection_counts.get(sub, 0)
    if current <= 1:
        _connection_counts.pop(sub, None)
    else:
        _connection_counts[sub] = current - 1


class TodoLiveConnection:
    """One socket: the subscribed boards, the pump of their pings and the client frames."""

    def __init__(
        self,
        websocket: WebSocket,
        *,
        principal: Principal,
        session: AsyncSession,
        broker: PatternBroker,
    ) -> None:
        self.ws = websocket
        self.principal = principal
        self.session = session
        self.broker = broker
        self.board_ids: frozenset[str] = frozenset()
        self._tokens = _THROTTLE_BURST
        self._last_refill = time.monotonic()

    def _allow_frame(self) -> bool:
        now = time.monotonic()
        self._tokens = min(
            _THROTTLE_BURST, self._tokens + (now - self._last_refill) * _THROTTLE_RATE
        )
        self._last_refill = now
        if self._tokens < 1.0:
            return False
        self._tokens -= 1.0
        return True

    async def _error(self, code: str) -> None:
        await self.ws.send_json({"type": "error", "code": code})

    async def _readable(self, ids: list[uuid.UUID]) -> list[uuid.UUID]:
        """The ids among ``ids`` whose board the principal reads now, in the given order."""
        wanted = list(dict.fromkeys(ids))
        if not wanted:
            return []
        try:
            boards = {
                b.id: b
                for b in (
                    await self.session.scalars(select(TodoBoard).where(TodoBoard.id.in_(wanted)))
                ).all()
            }
            # A new access per subscribe: its cache must not keep a right that is gone.
            access = BoardAccess(self.session)
            return [
                board_id
                for board_id in wanted
                if board_id in boards and await access.can_read(boards[board_id], self.principal)
            ]
        finally:
            await self.session.rollback()

    async def _subscribe(self, raw: dict[str, object]) -> None:
        try:
            msg = SubscribeMessage.model_validate(raw)
        except ValidationError:
            await self._error("invalid_message")
            return
        if len(msg.board_ids) > MAX_BOARDS:
            await self._error("too_many_boards")
            return
        kept = await self._readable(msg.board_ids)
        self.board_ids = frozenset(str(b) for b in kept)
        await self.ws.send_json({"type": "subscribed", "boardIds": [str(b) for b in kept]})

    async def _receive(self) -> None:
        while True:
            try:
                raw = await self.ws.receive_json()
            except json.JSONDecodeError:
                await self._error("invalid_message")
                continue
            if not self._allow_frame():
                await self._error("rate_limited")
                continue
            if not isinstance(raw, dict):
                await self._error("invalid_message")
            elif raw.get("type") == "subscribe":
                await self._subscribe(raw)  # pyright: ignore[reportUnknownArgumentType]
            else:
                await self._error("unknown_type")

    async def _pump(self, subscription: Subscription) -> None:
        async for message in subscription:
            if str(message.get("boardId")) in self.board_ids:
                await self.ws.send_json(message)

    async def run(self) -> None:
        """Forward the pings and read the client frames until the disconnect."""
        async with self.broker.subscribe_pattern(CHANNEL_PATTERN) as subscription:
            pump = asyncio.create_task(self._pump(subscription))
            receive = asyncio.create_task(self._receive())
            try:
                done, _pending = await asyncio.wait(
                    {pump, receive}, return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    try:
                        task.result()
                    except WebSocketDisconnect:
                        pass
                    except Exception:  # noqa: BLE001 — a dead task tears the socket down
                        logger.warning("to-do socket task failed", exc_info=True)
            finally:
                pump.cancel()
                receive.cancel()


async def get_todo_ws_principal(
    websocket: WebSocket,
    session: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Principal | None:
    """The principal of the session cookie (``None`` without a valid session)."""
    return await resolve_ws_principal(websocket, session, settings)


def get_todo_ws_broker(websocket: WebSocket) -> PatternBroker:
    """The broker of the app; a test overrides it."""
    return todo_broker(websocket.app.state)


@ws_router.websocket("/ws/todos")
async def todo_socket(
    websocket: WebSocket,
    session: DbSession,
    principal: Annotated[Principal | None, Depends(get_todo_ws_principal)],
    broker: Annotated[PatternBroker, Depends(get_todo_ws_broker)],
) -> None:
    """The change pings of the subscribed boards (``subscribe``, then ``card…``/``board``)."""
    # The handshake read the session and the principal: end that transaction first.
    await session.rollback()
    if principal is None:
        await websocket.close(code=WS_UNAUTHENTICATED)
        return
    if not _try_acquire_slot(principal.sub):
        await websocket.accept()
        await websocket.send_json({"type": "error", "code": "too_many_connections"})
        await websocket.close(code=WS_FORBIDDEN)
        return
    try:
        await websocket.accept()
        await TodoLiveConnection(
            websocket, principal=principal, session=session, broker=broker
        ).run()
    finally:
        _release_slot(principal.sub)
