"""Public guest routes and the guest WebSocket of #17, without a database.

`dependency_overrides` and a fake GuestService stand in for the service and the
broker. The tests cover the cookie handling, the route wiring, the WebSocket handshake
(origin, token, unknown guest, connection cap) and the event filter of a guest.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.db import get_session
from app.main import create_app
from app.modules.livevote import guest_connection as gc_mod
from app.modules.livevote import public_router
from app.modules.livevote.broker import InMemoryBroker
from app.modules.livevote.guest_connection import GuestConnection, _Closed
from app.modules.livevote.public_schemas import GuestMe, PublicMeetingHead
from app.modules.livevote.router import get_broker_rest, get_broker_ws
from app.modules.voting.schemas import BallotAccepted, TallyOut, VoteOut
from app.shared.config_schemas import VoteConfig
from app.shared.errors import NotFoundError, UnauthorizedError
from tests._support.flow_fakes import FakeSession, result

MID = uuid4()
HEAD = PublicMeetingHead(code="7KQ4MP", title="7. Sitzung", status="live", guestsMode="vote")


def _me(status: str = "pending") -> GuestMe:
    return GuestMe(guestId=uuid4(), number=1, displayName="Jana", status=status, meeting=HEAD)  # type: ignore[arg-type]


class FakeGuests:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.token: str | None = "new-token"

    async def head(self, code: str) -> PublicMeetingHead:
        self.calls.append(("head", code))
        return HEAD

    async def join(self, code: str, name: str, token: str | None, *, now: datetime) -> Any:
        self.calls.append(("join", (code, name, token)))
        return _me(), self.token

    async def me(self, code: str, token: str | None, *, now: datetime) -> GuestMe:
        self.calls.append(("me", token))
        return _me("admitted")

    async def rename_self(
        self, code: str, token: str | None, name: str, *, now: datetime
    ) -> GuestMe:
        self.calls.append(("rename", name))
        return _me()

    async def leave(self, code: str, token: str | None, *, now: datetime) -> None:
        self.calls.append(("leave", token))

    async def cast(
        self, code: str, token: str | None, vote_id: UUID, choice: str, **kw: Any
    ) -> BallotAccepted:
        self.calls.append(("cast", choice))
        return BallotAccepted()


@pytest.fixture
def rest() -> Any:
    app = create_app()
    fake = FakeGuests()
    app.dependency_overrides[public_router.get_public_guest_service] = lambda: fake
    app.dependency_overrides[public_router.get_public_voting_service] = lambda: object()

    async def _session() -> AsyncIterator[Any]:
        yield FakeSession()

    app.dependency_overrides[get_session] = _session
    with TestClient(app) as client:
        yield client, fake


def test_public_rest_routes(rest: Any) -> None:
    client, fake = rest
    assert client.get("/api/public/meetings/7KQ4MP").json()["code"] == "7KQ4MP"
    joined = client.post("/api/public/meetings/join/7KQ4MP", json={"displayName": "Jana Roth"})
    assert joined.status_code == 200
    cookie = joined.headers["set-cookie"]
    assert "mg_token=new-token" in cookie and "HttpOnly" in cookie
    assert "Path=/api/public/meetings" in cookie and "samesite=strict" in cookie.lower()
    fake.token = None
    again = client.post("/api/public/meetings/join/7KQ4MP", json={"displayName": "Jana Roth"})
    assert "set-cookie" not in again.headers or "mg_token" not in again.headers["set-cookie"]
    client.cookies.set("mg_token", "tok", path="/api/public/meetings")
    assert client.get("/api/public/meetings/7KQ4MP/me").json()["status"] == "admitted"
    # With the device cookie the writes need the CSRF double submit.
    assert (
        client.patch("/api/public/meetings/7KQ4MP/me", json={"displayName": "J R"}).status_code
        == 403
    )
    client.cookies.set("XSRF-TOKEN", "csrf-1")
    client.headers["X-XSRF-TOKEN"] = "csrf-1"
    assert (
        client.patch("/api/public/meetings/7KQ4MP/me", json={"displayName": "J R"}).status_code
        == 200
    )
    vote = uuid4()
    assert client.post(
        f"/api/public/meetings/7KQ4MP/votes/{vote}/ballot", json={"choice": "yes"}
    ).json() == {"status": "cast"}
    left = client.delete("/api/public/meetings/7KQ4MP/me")
    assert left.status_code == 204 and 'mg_token=""' in left.headers["set-cookie"]
    assert ("me", "tok") in fake.calls and ("cast", "yes") in fake.calls


# -- WebSocket ---------------------------------------------------------------------


def _guest(status: str = "pending") -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), meeting_id=MID, seq=3, display_name="Jana", status=status)


class WsGuests:
    """Stand-in for GuestService in the WebSocket route and the connection."""

    resolve_result: Any = None
    public: bool = True

    def __init__(self, session: Any = None, publisher: Any = None, **kw: Any) -> None:
        self.session = session

    async def resolve(self, code: str, token: str | None, **kw: Any) -> Any:
        result_ = type(self).resolve_result
        if isinstance(result_, Exception):
            raise result_
        return SimpleNamespace(id=MID), result_

    async def counts(self, meeting_id: UUID) -> tuple[int, int]:
        return 4, 1

    async def vote_is_public(self, vote_id: UUID, meeting_id: UUID) -> bool:
        return type(self).public


def _ws_app(monkeypatch: pytest.MonkeyPatch, resolve: Any, *, meeting: Any = None) -> Any:
    WsGuests.resolve_result = resolve
    WsGuests.public = True
    monkeypatch.setattr(public_router, "GuestService", WsGuests)
    monkeypatch.setattr(gc_mod, "GuestService", WsGuests)
    app = create_app()
    broker = InMemoryBroker()
    session = FakeSession()
    session.get_results = [
        meeting or SimpleNamespace(status="live", current_agenda_item_id=None)
    ] * 5

    async def _session() -> AsyncIterator[Any]:
        yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_broker_ws] = lambda: broker
    app.dependency_overrides[get_broker_rest] = lambda: broker
    return app, broker


def test_ws_refuses_bad_handshakes(monkeypatch: pytest.MonkeyPatch) -> None:
    for exc in (UnauthorizedError("x"), NotFoundError("x")):
        app, _ = _ws_app(monkeypatch, exc)
        client = TestClient(app)
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect("/api/public/meetings/7KQ4MP/ws") as ws,
        ):
            ws.receive_json()


def test_ws_handshake_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.shared.ratelimit import RateLimitResult

    class Full:
        async def hit(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
            return RateLimitResult(allowed=False, retry_after=60)

    app, _ = _ws_app(monkeypatch, _guest())
    monkeypatch.setattr(public_router, "get_rate_limiter", lambda request, settings: Full())
    client = TestClient(app)
    with (
        pytest.raises(WebSocketDisconnect) as err,
        client.websocket_connect("/api/public/meetings/7KQ4MP/ws") as ws,
    ):
        ws.receive_json()
    assert err.value.code == public_router.WS_RATE_LIMITED


def test_ws_refuses_a_foreign_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    app, _ = _ws_app(monkeypatch, _guest())
    monkeypatch.setattr(public_router, "origin_allowed", lambda origin, settings: False)
    client = TestClient(app)
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/api/public/meetings/7KQ4MP/ws") as ws,
    ):
        ws.receive_json()


def test_ws_terminal_guest_gets_its_status_and_the_end(monkeypatch: pytest.MonkeyPatch) -> None:
    app, _ = _ws_app(monkeypatch, _guest("rejected"))
    with (
        TestClient(app) as client,
        client.websocket_connect("/api/public/meetings/7KQ4MP/ws") as ws,
    ):
        assert ws.receive_json()["status"] == "rejected"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_ws_connection_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    g = _guest()
    app, _ = _ws_app(monkeypatch, g)
    public_router._guest_connections[g.id] = public_router._MAX_CONNECTIONS_PER_GUEST
    try:
        with (
            TestClient(app) as client,
            client.websocket_connect("/api/public/meetings/7KQ4MP/ws") as ws,
        ):
            assert ws.receive_json() == {"type": "error", "code": "too_many_connections"}
    finally:
        public_router._guest_connections.pop(g.id, None)
    public_router._guest_connections[g.id] = 2
    public_router._release(g.id)
    assert public_router._guest_connections[g.id] == 1
    public_router._release(g.id)
    assert g.id not in public_router._guest_connections


def test_ws_pending_guest_is_admitted_live(monkeypatch: pytest.MonkeyPatch) -> None:
    g = _guest()
    app, broker = _ws_app(monkeypatch, g)
    with (
        TestClient(app) as client,
        client.websocket_connect("/api/public/meetings/7KQ4MP/ws") as ws,
    ):
        assert ws.receive_json()["status"] == "pending"
        ws.send_json({"type": "nope"})
        assert ws.receive_json() == {"type": "error", "code": "unknown_type"}
        ws.send_text("not json")
        assert ws.receive_json()["code"] == "invalid_message"
        ws.send_json({"type": "subscribe"})
        assert ws.receive_json()["type"] == "guest_status"


async def _connection(
    status: str = "admitted", *, public: bool = True
) -> tuple[GuestConnection, list[Any]]:
    sent: list[Any] = []

    class Ws:
        async def send_json(self, payload: Any) -> None:
            sent.append(payload)

    session = FakeSession()
    session.get_results = [SimpleNamespace(status="live", current_agenda_item_id=uuid4())]
    WsGuests.public = public
    conn = GuestConnection(
        Ws(),  # type: ignore[arg-type]
        session=session,  # type: ignore[arg-type]
        broker=InMemoryBroker(),
        meeting_id=MID,
        guest=_guest(status),  # type: ignore[arg-type]
    )
    conn.guests = WsGuests(session)  # type: ignore[assignment]
    return conn, sent


async def test_guest_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    conn, sent = await _connection("pending")
    other = {"type": "guest_updated", "guest": {"id": str(uuid4()), "status": "admitted"}}
    await conn.handle(other)
    await conn.handle({"type": "guest_updated", "guest": "broken"})
    await conn.handle({"type": "meeting_state", "status": "live"})
    await conn.handle({"type": "viewers", "viewers": ["Anna"]})
    assert sent == []
    # The own admission switches the feed on and sends the state.
    mine = {
        "type": "guest_updated",
        "guest": {
            "id": str(conn.guest_id),
            "status": "admitted",
            "displayName": "Jana",
            "number": 4,
        },
    }
    await conn.handle(mine)
    assert sent[0]["status"] == "admitted" and sent[0]["number"] == 4
    assert {m["type"] for m in sent[1:]} == {"guest_status", "meeting_state", "guest_counts"}
    sent.clear()
    await conn.handle({"type": "guest_requested", "guest": {"displayName": "Bert"}})
    await conn.handle({"type": "viewers", "viewers": ["Anna"]})
    await conn.handle(
        {"type": "guest_counts", "admittedGuests": 5, "joinCode": "X", "pendingGuests": 2}
    )
    await conn.handle(
        {
            "type": "meeting_state",
            "status": "live",
            "currentAgendaItemId": None,
            "activeApplicationId": "a",
        }
    )
    vote = str(uuid4())
    await conn.handle({"type": "vote_tally", "voteId": vote, "cast": 1})
    await conn.handle({"type": "vote_tally", "voteId": vote, "cast": 2})  # cached
    await conn.handle({"type": "vote_closed", "voteId": "not-a-uuid"})
    assert sent == [
        {"type": "guest_counts", "admittedGuests": 5},
        {"type": "meeting_state", "status": "live", "currentAgendaItemId": None},
        {"type": "vote_tally", "voteId": vote, "cast": 1},
        {"type": "vote_tally", "voteId": vote, "cast": 2},
    ]
    with pytest.raises(_Closed):
        await conn.handle({"type": "meeting_state", "status": "closed"})
    removed = {
        "type": "guest_updated",
        "guest": {"id": str(conn.guest_id), "status": "removed"},
        "reason": "public_off",
    }
    with pytest.raises(_Closed):
        await conn.handle(removed)
    assert sent[-1]["reason"] == "public_off"


async def test_guest_filter_drops_non_public_votes() -> None:
    conn, sent = await _connection(public=False)
    await conn.handle({"type": "vote_opened", "voteId": str(uuid4()), "question": "NÖ"})
    assert sent == []


async def test_send_state_with_an_open_public_vote(monkeypatch: pytest.MonkeyPatch) -> None:
    conn, sent = await _connection()
    vote_id = uuid4()
    config = VoteConfig.model_validate({"options": ["yes", "no"], "majorityRule": "simple"})
    out = VoteOut(
        id=vote_id,
        meetingId=MID,
        eligibleGroup="g",
        config=config,
        status="open",
        secret=False,
        tally=TallyOut(counts={}, eligible=3, quorumMet=True, revealed=False),
    )

    async def fake_get(self: Any, vid: UUID) -> VoteOut:
        return out

    monkeypatch.setattr(gc_mod.VotingService, "get", fake_get)
    conn.session._results = [result(SimpleNamespace(id=vote_id))]  # type: ignore[attr-defined]
    await conn.send_state()
    assert [m["type"] for m in sent] == [
        "guest_status",
        "meeting_state",
        "guest_counts",
        "vote_opened",
        "vote_tally",
    ]
    assert sent[3]["replay"] is True


async def test_send_state_of_a_closed_meeting_ends() -> None:
    conn, _ = await _connection()
    conn.session.get_results = [SimpleNamespace(status="closed", current_agenda_item_id=None)]  # type: ignore[attr-defined]
    with pytest.raises(_Closed):
        await conn.send_state()


def test_ws_admitted_guest_closes_with_the_meeting(monkeypatch: pytest.MonkeyPatch) -> None:
    app, broker = _ws_app(
        monkeypatch,
        _guest("admitted"),
        meeting=SimpleNamespace(status="closed", current_agenda_item_id=None),
    )
    with (
        TestClient(app) as client,
        client.websocket_connect("/api/public/meetings/7KQ4MP/ws") as ws,
    ):
        assert ws.receive_json()["type"] == "guest_status"
        assert ws.receive_json()["status"] == "closed"
        ws.receive_json()  # guest_counts
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_now_is_aware() -> None:
    assert datetime.now(UTC).tzinfo is UTC


async def _run_with(conn: GuestConnection, message: dict[str, Any]) -> list[int]:
    import asyncio

    closed: list[int] = []

    class Ws:
        async def send_json(self, payload: Any) -> None:
            return None

        async def receive_json(self) -> Any:
            await asyncio.Event().wait()

        async def close(self, code: int = 1000) -> None:
            closed.append(code)

    conn.ws = Ws()  # type: ignore[assignment]
    task = asyncio.create_task(conn.run())
    await asyncio.sleep(0.05)
    await conn.broker.publish(f"meeting:{MID}", message)
    await asyncio.wait_for(task, 2)
    return closed


async def test_run_ends_on_removal_and_on_a_fault() -> None:
    conn, _ = await _connection()
    removed = {"type": "guest_updated", "guest": {"id": str(conn.guest_id), "status": "removed"}}
    assert await _run_with(conn, removed) == [1000]

    class Boom(WsGuests):
        async def vote_is_public(self, vote_id: UUID, meeting_id: UUID) -> bool:
            raise RuntimeError("db gone")

    conn, _ = await _connection()
    conn.guests = Boom()  # type: ignore[assignment]
    assert await _run_with(conn, {"type": "vote_tally", "voteId": str(uuid4())}) == []


async def test_run_of_a_closed_meeting_closes_at_once() -> None:
    conn, _ = await _connection()
    conn.session.get_results = [SimpleNamespace(status="closed", current_agenda_item_id=None)]  # type: ignore[attr-defined]
    import asyncio

    closed: list[int] = []

    class Ws:
        async def send_json(self, payload: Any) -> None:
            return None

        async def close(self, code: int = 1000) -> None:
            closed.append(code)

    conn.ws = Ws()  # type: ignore[assignment]
    await asyncio.wait_for(conn.run(), 2)
    assert closed == [1000]


async def test_waiting_guest_socket_ends_with_the_meeting() -> None:
    conn, sent = await _connection("pending")
    with pytest.raises(_Closed):
        await conn.handle({"type": "meeting_state", "status": "closed"})
    assert sent == [
        {
            "type": "guest_status",
            "status": "pending",
            "displayName": "Jana",
            "number": 3,
            "reason": "meeting_closed",
        }
    ]


async def test_item_turning_non_public_stops_its_vote_events() -> None:
    conn, sent = await _connection()
    vote = str(uuid4())
    await conn.handle({"type": "vote_tally", "voteId": vote, "cast": 1})
    assert len(sent) == 1
    # The item turns non-public: the agenda edit sends a meeting state, the cache goes.
    WsGuests.public = False
    await conn.handle({"type": "meeting_state", "status": "live", "currentAgendaItemId": None})
    sent.clear()
    await conn.handle({"type": "vote_tally", "voteId": vote, "cast": 2})
    assert sent == []
