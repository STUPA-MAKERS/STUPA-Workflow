"""Unit tests of the board pings (``live``) and the to-do socket (``socket``).

The collector, the publish after the commit and its swallowed fault run without a
database. The socket runs on a fake WebSocket or through the TestClient with an
in-memory broker; the subscribe reads boards through a scripted session and a fake
``BoardAccess``. The integration test covers the real handshake rights.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.db import get_session
from app.main import create_app
from app.modules.auth.principal import Principal
from app.modules.livevote.broker import InMemoryBroker
from app.modules.todos import socket as socket_mod
from app.modules.todos.live import BoardPings, board_channel, publish_pings
from app.modules.todos.models import TodoBoard
from app.modules.todos.socket import (
    MAX_BOARDS,
    RECHECK_SECONDS,
    TodoLiveConnection,
    get_todo_ws_broker,
    get_todo_ws_principal,
    get_todo_ws_resolver,
)
from tests.unit.modules.todos.fakes import ScriptedSession

B1 = uuid.UUID(int=11)
B2 = uuid.UUID(int=12)
C1 = uuid.UUID(int=21)
C2 = uuid.UUID(int=22)
USER = Principal(sub="live-user", permissions={"todo.write"})


# -- the collector ----------------------------------------------------------------


def test_one_card_pings_the_card_and_several_collapse_to_the_board() -> None:
    pings = BoardPings()
    pings.touch(B1, C1)
    pings.touch(B1, C1)
    pings.touch(B2, C1)
    pings.touch(B2, C2)
    assert pings.messages() == [
        {"type": "card", "boardId": str(B1), "cardId": str(C1)},
        {"type": "board", "boardId": str(B2)},
    ]


def test_a_board_change_and_a_removed_card() -> None:
    pings = BoardPings()
    pings.touch(B1)
    pings.touch(B1, C1)
    pings.touch(B2, C1, removed=True)
    # A card that left stays gone, also after a later write in the same request.
    pings.touch(B2, C1)
    assert pings.drain() == [
        {"type": "board", "boardId": str(B1)},
        {"type": "card_removed", "boardId": str(B2), "cardId": str(C1)},
    ]
    assert pings.drain() == []


class _Broker:
    def __init__(self, fail_on: str | None = None) -> None:
        self.sent: list[tuple[str, dict[str, object]]] = []
        self.fail_on = fail_on

    async def publish(self, channel: str, message: dict[str, object]) -> None:
        if channel == self.fail_on:
            raise RuntimeError("redis down")
        self.sent.append((channel, message))


async def test_a_failed_publish_is_swallowed_and_the_next_still_goes() -> None:
    broker = _Broker(fail_on=board_channel(B1))
    messages: list[dict[str, object]] = [
        {"type": "board", "boardId": str(B1)},
        {"type": "board", "boardId": str(B2)},
    ]
    await publish_pings(broker, messages)  # type: ignore[arg-type]
    assert broker.sent == [(f"todo-board:{B2}", {"type": "board", "boardId": str(B2)})]


# -- the connection -----------------------------------------------------------------


class _Access:
    """``BoardAccess`` that reads the boards of ``allowed``."""

    allowed: set[uuid.UUID] = set()

    def __init__(self, _session: Any) -> None:
        pass

    async def can_read(self, board: TodoBoard, _principal: Principal) -> bool:
        return board.id in self.allowed


@pytest.fixture
def access(monkeypatch: pytest.MonkeyPatch) -> type[_Access]:
    monkeypatch.setattr(socket_mod, "BoardAccess", _Access)
    _Access.allowed = {B1}
    return _Access


def _session(*boards: uuid.UUID) -> ScriptedSession:
    session = ScriptedSession(
        scalars=[[TodoBoard(id=b, kind="gremium", name="B") for b in boards] for _ in range(3)]
    )
    session.rolled_back = 0  # type: ignore[attr-defined]

    async def _rollback() -> None:
        session.rolled_back += 1  # type: ignore[attr-defined]

    session.rollback = _rollback  # type: ignore[method-assign]
    return session


class _Raw(str):
    """A text frame sent as it is (not JSON-encoded by the fake)."""


def _asgi(frame: Any) -> dict[str, Any]:
    """The ASGI message of a fake frame: bytes are binary, a ``_Raw`` is raw text."""
    if isinstance(frame, bytes):
        return {"type": "websocket.receive", "bytes": frame}
    if isinstance(frame, _Raw):
        return {"type": "websocket.receive", "text": str(frame)}
    return {"type": "websocket.receive", "text": json.dumps(frame)}


class _Ws:
    def __init__(self, frames: list[Any]) -> None:
        self.frames = list(frames)
        self.sent: list[dict[str, Any]] = []
        self.closed: list[int] = []
        self.done = asyncio.Event()

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)

    async def close(self, code: int = 1000) -> None:
        self.closed.append(code)

    async def receive(self) -> dict[str, Any]:
        if not self.frames:
            self.done.set()
            await asyncio.Event().wait()
        frame = self.frames.pop(0)
        if isinstance(frame, Exception):
            raise frame
        return _asgi(frame)


async def _run(frames: list[Any], session: ScriptedSession, publish: list[dict[str, Any]]) -> _Ws:
    ws = _Ws(frames)
    broker = InMemoryBroker()
    conn = TodoLiveConnection(
        ws,  # type: ignore[arg-type]
        principal=USER,
        session=session,  # type: ignore[arg-type]
        broker=broker,
    )
    task = asyncio.create_task(conn.run())
    await asyncio.wait_for(ws.done.wait(), 2)
    for message in publish:
        await broker.publish(board_channel(uuid.UUID(message["boardId"])), message)
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    return ws


async def test_subscribe_keeps_the_readable_boards_and_forwards_their_pings(
    access: type[_Access],
) -> None:
    session = _session(B1, B2)
    unknown = uuid.uuid4()
    ws = await _run(
        [{"type": "subscribe", "boardIds": [str(B1), str(B2), str(unknown), str(B1)]}],
        session,
        [
            {"type": "card", "boardId": str(B2), "cardId": str(C1)},
            {"type": "card", "boardId": str(B1), "cardId": str(C1)},
        ],
    )
    assert ws.sent == [
        {"type": "subscribed", "boardIds": [str(B1)]},
        {"type": "card", "boardId": str(B1), "cardId": str(C1)},
    ]
    assert session.rolled_back == 1  # type: ignore[attr-defined]


async def test_a_new_subscribe_checks_the_rights_again(
    access: type[_Access], monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _session(B1)
    frames: list[Any] = [
        {"type": "subscribe", "boardIds": [str(B1)]},
        {"type": "subscribe", "boardIds": [str(B1)]},
        {"type": "subscribe", "boardIds": []},
    ]

    async def _lose(*_a: Any) -> bool:
        return False

    ws = _Ws(frames)
    conn = TodoLiveConnection(ws, principal=USER, session=session, broker=InMemoryBroker())  # type: ignore[arg-type]
    await conn._subscribe(frames[0])
    assert conn.board_ids == {str(B1)}
    monkeypatch.setattr(access, "can_read", _lose)
    await conn._subscribe(frames[1])
    assert conn.board_ids == frozenset()
    await conn._subscribe(frames[2])
    assert ws.sent[-1] == {"type": "subscribed", "boardIds": []}


async def test_bad_frames_get_an_error_and_keep_the_socket(access: type[_Access]) -> None:
    too_many = {"type": "subscribe", "boardIds": [str(uuid.uuid4()) for _ in range(MAX_BOARDS + 1)]}
    ws = await _run(
        [
            _Raw("{kein json"),
            b"\x00\x01",
            ["a"],
            {"type": "nope"},
            {"type": "subscribe", "boardIds": ["not-a-uuid"]},
            too_many,
        ],
        _session(),
        [],
    )
    codes = [m["code"] for m in ws.sent]
    assert codes == [
        "invalid_message",
        "invalid_message",
        "invalid_message",
        "unknown_type",
        "invalid_message",
        "too_many_boards",
    ]


async def test_bad_frames_count_against_the_throttle(access: type[_Access]) -> None:
    ws = await _run([b"\x00"] * 6 + [_Raw("{")] * 6, _session(), [])
    codes = [m["code"] for m in ws.sent]
    assert codes == ["invalid_message"] * 10 + ["rate_limited"] * 2


async def test_a_disconnect_frame_ends_the_run(access: type[_Access]) -> None:
    class _Gone(_Ws):
        async def receive(self) -> dict[str, Any]:
            return {"type": "websocket.disconnect", "code": 1001}

    conn = TodoLiveConnection(
        _Gone([]),  # type: ignore[arg-type]
        principal=USER,
        session=_session(),  # type: ignore[arg-type]
        broker=InMemoryBroker(),
    )
    await asyncio.wait_for(conn.run(), 2)


async def test_every_subscribe_resolves_the_principal_again(
    access: type[_Access], monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _session(B1)
    admin = Principal(sub="live-user", roles=["admin"])
    current: list[Principal | None] = [admin]
    seen: list[Principal] = []

    async def _resolve() -> Principal | None:
        return current[0]

    class _Seen(_Access):
        async def can_read(self, board: TodoBoard, principal: Principal) -> bool:
            seen.append(principal)
            return board.id in self.allowed

    monkeypatch.setattr(socket_mod, "BoardAccess", _Seen)
    ws = _Ws([])
    conn = TodoLiveConnection(
        ws,  # type: ignore[arg-type]
        principal=USER,
        session=session,  # type: ignore[arg-type]
        broker=InMemoryBroker(),
        resolve=_resolve,
    )
    frame = {"type": "subscribe", "boardIds": [str(B1)]}
    assert await conn._subscribe(frame) is True
    assert seen == [admin] and conn.principal is admin
    current[0] = None
    assert await conn._subscribe(frame) is False
    assert ws.closed == [4401] and conn.board_ids == frozenset()
    assert ws.sent == [{"type": "subscribed", "boardIds": [str(B1)]}]
    assert session.rolled_back == 2  # type: ignore[attr-defined]


async def test_a_gone_session_closes_the_socket_and_ends_the_run(access: type[_Access]) -> None:
    async def _gone() -> Principal | None:
        return None

    ws = _Ws([{"type": "subscribe", "boardIds": [str(B1)]}])
    conn = TodoLiveConnection(
        ws,  # type: ignore[arg-type]
        principal=USER,
        session=_session(B1),  # type: ignore[arg-type]
        broker=InMemoryBroker(),
        resolve=_gone,
    )
    await asyncio.wait_for(conn.run(), 2)
    assert ws.closed == [4401] and ws.sent == []


class _Clock:
    """A monotonic clock that a test moves by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def _pings(*messages: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    for message in messages:
        yield message


def _ping(board_id: uuid.UUID) -> dict[str, Any]:
    return {"type": "card", "boardId": str(board_id), "cardId": str(C1)}


async def test_the_pump_checks_again_after_the_recheck_age(
    access: type[_Access], monkeypatch: pytest.MonkeyPatch
) -> None:
    access.allowed = {B1, B2}
    clock = _Clock()
    calls: list[float] = []

    async def _resolve() -> Principal | None:
        calls.append(clock.now)
        return USER

    session = _session(B1, B2)
    ws = _Ws([])
    conn = TodoLiveConnection(
        ws,  # type: ignore[arg-type]
        principal=USER,
        session=session,  # type: ignore[arg-type]
        broker=InMemoryBroker(),
        resolve=_resolve,
        clock=clock,
    )
    await conn._subscribe({"type": "subscribe", "boardIds": [str(B1), str(B2)]})
    clock.now += RECHECK_SECONDS - 1
    await conn._pump(_pings(_ping(B2)))
    assert calls == [1000.0] and ws.sent[-1] == _ping(B2)
    # The right to B2 is gone; after the recheck age the next ping checks again.
    access.allowed = {B1}
    clock.now += 2
    await conn._pump(_pings(_ping(B2), _ping(B1)))
    assert calls == [1000.0, clock.now]
    assert conn.board_ids == {str(B1)}
    assert ws.sent[-2:] == [_ping(B2), _ping(B1)]
    assert session.rolled_back == 2  # type: ignore[attr-defined]
    # A ping of a board that is not subscribed never triggers a check.
    clock.now += RECHECK_SECONDS * 2
    await conn._pump(_pings(_ping(B2)))
    assert len(calls) == 2 and ws.closed == []


async def test_the_pump_closes_4401_when_the_session_is_gone(access: type[_Access]) -> None:
    clock = _Clock()
    current: list[Principal | None] = [USER]

    async def _resolve() -> Principal | None:
        return current[0]

    ws = _Ws([])
    conn = TodoLiveConnection(
        ws,  # type: ignore[arg-type]
        principal=USER,
        session=_session(B1),  # type: ignore[arg-type]
        broker=InMemoryBroker(),
        resolve=_resolve,
        clock=clock,
    )
    await conn._subscribe({"type": "subscribe", "boardIds": [str(B1)]})
    current[0] = None
    clock.now += RECHECK_SECONDS
    await conn._pump(_pings(_ping(B1), _ping(B1)))
    assert ws.closed == [4401] and conn.board_ids == frozenset()
    assert ws.sent == [{"type": "subscribed", "boardIds": [str(B1)]}]


async def test_a_recheck_after_a_parallel_subscribe_reads_nothing(
    access: type[_Access],
) -> None:
    clock = _Clock()
    calls: list[float] = []

    async def _resolve() -> Principal | None:
        calls.append(clock.now)
        return USER

    ws = _Ws([])
    conn = TodoLiveConnection(
        ws,  # type: ignore[arg-type]
        principal=USER,
        session=_session(B1),  # type: ignore[arg-type]
        broker=InMemoryBroker(),
        resolve=_resolve,
        clock=clock,
    )
    clock.now += RECHECK_SECONDS
    # The subscribe holds the lock; the recheck waits and then finds a fresh check.
    async with conn._check_lock:
        recheck = asyncio.create_task(conn._recheck())
        await asyncio.sleep(0)
        await conn._readable([B1])
    assert await recheck is True
    assert calls == [clock.now]


async def test_the_resolver_reads_the_handshake_cookie_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Any, Any, Any]] = []

    async def _fake(websocket: Any, db: Any, settings: Any) -> Principal | None:
        calls.append((websocket, db, settings))
        return USER

    monkeypatch.setattr(socket_mod, "resolve_ws_principal", _fake)
    resolve = get_todo_ws_resolver("ws", "db", "settings")  # type: ignore[arg-type]
    assert await resolve() is USER
    assert calls == [("ws", "db", "settings")]


def test_the_throttle_drops_a_flood() -> None:
    conn = TodoLiveConnection(
        object(),  # type: ignore[arg-type]
        principal=USER,
        session=object(),  # type: ignore[arg-type]
        broker=InMemoryBroker(),
    )
    allowed = [conn._allow_frame() for _ in range(15)]
    assert allowed.count(True) == 10 and not allowed[-1]


async def test_a_failing_pump_ends_the_run(access: type[_Access]) -> None:
    class _Dead:
        async def send_json(self, _payload: Any) -> None:
            raise RuntimeError("socket gone")

        async def receive(self) -> Any:
            await asyncio.Event().wait()

    broker = InMemoryBroker()
    conn = TodoLiveConnection(_Dead(), principal=USER, session=_session(), broker=broker)  # type: ignore[arg-type]
    conn.board_ids = frozenset({str(B1)})
    task = asyncio.create_task(conn.run())
    await asyncio.sleep(0.05)
    await broker.publish(board_channel(B1), {"type": "board", "boardId": str(B1)})
    await asyncio.wait_for(task, 2)


# -- the endpoint ---------------------------------------------------------------------


def _app(principal: Principal | None, broker: InMemoryBroker) -> Any:
    app = create_app()

    async def _db() -> AsyncIterator[ScriptedSession]:
        yield _session(B1)

    app.dependency_overrides[get_session] = _db
    app.dependency_overrides[get_todo_ws_principal] = lambda: principal

    async def _again() -> Principal | None:
        return principal

    app.dependency_overrides[get_todo_ws_resolver] = lambda: _again
    app.dependency_overrides[get_todo_ws_broker] = lambda: broker
    return app


def test_without_a_session_the_socket_closes_4401() -> None:
    client = TestClient(_app(None, InMemoryBroker()))
    with pytest.raises(WebSocketDisconnect) as exc, client.websocket_connect("/api/ws/todos"):
        pass
    assert exc.value.code == 4401


def test_the_socket_subscribes_and_the_cap_closes_4403(
    access: type[_Access], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(socket_mod, "MAX_CONNECTIONS_PER_PRINCIPAL", 1)
    client = TestClient(_app(USER, InMemoryBroker()))
    with client.websocket_connect("/api/ws/todos") as ws:
        ws.send_json({"type": "subscribe", "boardIds": [str(B1)]})
        assert ws.receive_json() == {"type": "subscribed", "boardIds": [str(B1)]}
        with client.websocket_connect("/api/ws/todos") as second:
            assert second.receive_json() == {"type": "error", "code": "too_many_connections"}
            with pytest.raises(WebSocketDisconnect) as exc:
                second.receive_json()
            assert exc.value.code == 4403
    assert socket_mod._connection_counts == {}


def test_the_real_handshake_refuses_a_foreign_origin_and_no_cookie() -> None:
    from app.settings import get_settings, load_settings

    app = create_app()

    async def _db() -> AsyncIterator[ScriptedSession]:
        yield _session()

    settings = load_settings(public_base_url="https://app.example")
    app.dependency_overrides[get_session] = _db
    app.dependency_overrides[get_settings] = lambda: settings
    client = TestClient(app)
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect("/api/ws/todos", headers={"origin": "https://evil.example"}),
    ):
        pass
    assert exc.value.code == 4403
    with pytest.raises(WebSocketDisconnect) as exc, client.websocket_connect("/api/ws/todos"):
        pass
    assert exc.value.code == 4401


def test_the_default_broker_is_the_app_broker() -> None:
    broker = InMemoryBroker()

    class _Socket:
        class app:
            class state:
                pass

    _Socket.app.state.broker = broker  # type: ignore[attr-defined]
    assert get_todo_ws_broker(_Socket()) is broker  # type: ignore[arg-type]
