"""WebSocket-Verhalten Live-Vote (T-16, api.md §4) — via TestClient (httpx-ws-äquiv.).

Deckt Handshake-Auth/RBAC (4401/4404/not_eligible), Voter-Lifecycle
(connect→meeting_state, ``subscribe``-Reconnect-State, ``cast``→``vote_tally``-
Broadcast), Cast-Fehler (Lock/Conflict/Eligibility/Invalid) und den read-only
Beamer-Stream ab. Services/Principal/Broker/Lock sind via ``dependency_overrides``
ersetzt → kein DB/Redis nötig (echte Race/Fan-out im Integrationstest)."""

from __future__ import annotations

import types
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import create_app
from app.modules.auth.principal import Principal
from app.modules.livevote.broker import InMemoryBroker
from app.modules.livevote.locks import InMemoryLocker
from app.modules.livevote.router import (
    get_broker_ws,
    get_locker_ws,
    get_meeting_service_ws,
    get_voting_service_ws,
    get_ws_principal,
)
from app.modules.livevote.schemas import MeetingOut, MeetingStatus
from app.modules.voting.schemas import TallyOut, VoteOut
from app.shared.config_schemas import VoteConfig
from app.shared.errors import ConflictError, ForbiddenError

_CONFIG = VoteConfig.model_validate({"options": ["yes", "no"], "majorityRule": "simple"})
_GREMIUM = uuid4()


def _meeting(status: MeetingStatus = "live") -> MeetingOut:
    return MeetingOut(
        id=uuid4(), gremiumId=_GREMIUM, title="GV", status=status, activeApplicationId=None
    )


def _vote_out(meeting_id: UUID) -> VoteOut:
    return VoteOut(
        id=uuid4(),
        applicationId=uuid4(),
        meetingId=meeting_id,
        eligibleGroup="stupa",
        config=_CONFIG,
        status="open",  # type: ignore[arg-type]
        secret=False,
        tally=TallyOut(counts={"yes": 1, "no": 0}, eligible=5, quorumMet=False, leading="yes"),
    )


class _FakeSession:
    async def rollback(self) -> None:
        return None


class _FakeMeetingService:
    def __init__(self, meeting: MeetingOut | None, open_vote: object = None) -> None:
        self._meeting = meeting
        self._open_vote = open_vote

    async def get(self, _meeting_id: UUID) -> MeetingOut:
        if self._meeting is None:
            from app.shared.errors import NotFoundError

            raise NotFoundError("meeting not found")
        return self._meeting

    async def open_vote(self, _meeting_id: UUID) -> object:
        return self._open_vote


class _FakeVotingService:
    def __init__(self, vote_out: VoteOut, exc: Exception | None = None) -> None:
        self.session = _FakeSession()
        self._vote_out = vote_out
        self._exc = exc
        self.casts: list[tuple[UUID, str, str]] = []

    async def cast(self, vote_id: UUID, principal: Principal, choice: str, *, now) -> None:  # noqa: ANN001
        if self._exc is not None:
            raise self._exc
        self.casts.append((vote_id, choice, principal.sub))

    async def get(self, _vote_id: UUID) -> VoteOut:
        return self._vote_out


class _BusyLocker:
    """Liefert immer ``False`` (Lock belegt) — simuliert konkurrierenden Cast."""

    @asynccontextmanager
    async def acquire(self, key: str, *, ttl_ms: int = 5000) -> AsyncIterator[bool]:
        yield False


def _build(
    *,
    meeting: MeetingOut | None,
    principal: Principal | None,
    vote_out: VoteOut | None = None,
    open_vote: object = None,
    voting_exc: Exception | None = None,
    broker: InMemoryBroker | None = None,
    locker: object | None = None,
):
    app = create_app()
    broker = broker or InMemoryBroker()
    locker = locker or InMemoryLocker()
    vote_out = vote_out or _vote_out(meeting.id if meeting else uuid4())
    voting = _FakeVotingService(vote_out, voting_exc)
    meetings = _FakeMeetingService(meeting, open_vote)
    app.dependency_overrides[get_ws_principal] = lambda: principal
    app.dependency_overrides[get_meeting_service_ws] = lambda: meetings
    app.dependency_overrides[get_voting_service_ws] = lambda: voting
    app.dependency_overrides[get_broker_ws] = lambda: broker
    app.dependency_overrides[get_locker_ws] = lambda: locker
    return app, voting, vote_out


def _voter(groups: set[str] | None = None) -> Principal:
    members = {str(_GREMIUM)} if groups is None else groups
    return Principal(sub="p", permissions={"vote.cast"}, groups=members)


def _url(meeting: MeetingOut) -> str:
    return f"/api/ws/meetings/{meeting.id}"


# --------------------------------------------------------------------------- #
# Handshake / RBAC
# --------------------------------------------------------------------------- #
def test_unauthenticated_is_closed_before_accept() -> None:
    meeting = _meeting()
    app, _, _ = _build(meeting=meeting, principal=None)
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(_url(meeting)):
        pass


def test_unknown_meeting_is_closed() -> None:
    app, _, _ = _build(meeting=None, principal=_voter())
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(
        "/api/ws/meetings/" + str(uuid4())
    ):
        pass


def test_not_in_group_gets_not_eligible_error() -> None:
    meeting = _meeting()
    app, _, _ = _build(meeting=meeting, principal=_voter(groups=set()))
    client = TestClient(app)
    with client.websocket_connect(_url(meeting)) as ws:
        assert ws.receive_json() == {"type": "error", "code": "not_eligible"}


# --------------------------------------------------------------------------- #
# Voter-Lifecycle
# --------------------------------------------------------------------------- #
def test_connect_sends_meeting_state() -> None:
    meeting = _meeting()
    app, _, _ = _build(meeting=meeting, principal=_voter())
    client = TestClient(app)
    with client.websocket_connect(_url(meeting)) as ws:
        state = ws.receive_json()
    assert state["type"] == "meeting_state"
    assert state["status"] == "live"


def test_subscribe_resends_state_with_open_vote() -> None:
    meeting = _meeting()
    vote_out = _vote_out(meeting.id)
    open_vote = types.SimpleNamespace(id=vote_out.id)
    app, _, _ = _build(
        meeting=meeting, principal=_voter(), vote_out=vote_out, open_vote=open_vote
    )
    client = TestClient(app)
    with client.websocket_connect(_url(meeting)) as ws:
        # Connect liefert bereits den vollständigen State (open vote).
        assert ws.receive_json()["type"] == "meeting_state"
        assert ws.receive_json()["type"] == "vote_opened"
        assert ws.receive_json()["type"] == "vote_tally"
        ws.send_json({"type": "subscribe"})
        assert ws.receive_json()["type"] == "meeting_state"
        assert ws.receive_json()["type"] == "vote_opened"
        assert ws.receive_json()["type"] == "vote_tally"


def test_cast_records_vote_and_broadcasts_tally() -> None:
    meeting = _meeting()
    vote_out = _vote_out(meeting.id)
    app, voting, _ = _build(meeting=meeting, principal=_voter(), vote_out=vote_out)
    client = TestClient(app)
    with client.websocket_connect(_url(meeting)) as ws:
        assert ws.receive_json()["type"] == "meeting_state"
        ws.send_json({"type": "cast", "voteId": str(vote_out.id), "choice": "yes"})
        tally = ws.receive_json()
    assert tally["type"] == "vote_tally"
    assert tally["counts"] == {"yes": 1, "no": 0}
    assert voting.casts == [(vote_out.id, "yes", "p")]


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (ForbiddenError("nope"), "not_eligible"),
        (ConflictError("already", code="conflict"), "conflict"),
    ],
)
def test_cast_errors_map_to_error_event(exc: Exception, expected: str) -> None:
    meeting = _meeting()
    vote_out = _vote_out(meeting.id)
    app, _, _ = _build(
        meeting=meeting, principal=_voter(), vote_out=vote_out, voting_exc=exc
    )
    client = TestClient(app)
    with client.websocket_connect(_url(meeting)) as ws:
        assert ws.receive_json()["type"] == "meeting_state"
        ws.send_json({"type": "cast", "voteId": str(vote_out.id), "choice": "yes"})
        assert ws.receive_json() == {"type": "error", "code": expected}


def test_cast_when_locked_reports_locked() -> None:
    meeting = _meeting()
    app, _, _ = _build(meeting=meeting, principal=_voter(), locker=_BusyLocker())
    client = TestClient(app)
    with client.websocket_connect(_url(meeting)) as ws:
        assert ws.receive_json()["type"] == "meeting_state"
        ws.send_json({"type": "cast", "voteId": str(uuid4()), "choice": "yes"})
        assert ws.receive_json() == {"type": "error", "code": "locked"}


def test_invalid_cast_message_reports_invalid() -> None:
    meeting = _meeting()
    app, _, _ = _build(meeting=meeting, principal=_voter())
    client = TestClient(app)
    with client.websocket_connect(_url(meeting)) as ws:
        assert ws.receive_json()["type"] == "meeting_state"
        ws.send_json({"type": "cast"})  # voteId/choice fehlen
        assert ws.receive_json() == {"type": "error", "code": "invalid_message"}


def test_unknown_message_type_reports_error() -> None:
    meeting = _meeting()
    app, _, _ = _build(meeting=meeting, principal=_voter())
    client = TestClient(app)
    with client.websocket_connect(_url(meeting)) as ws:
        assert ws.receive_json()["type"] == "meeting_state"
        ws.send_json({"type": "weird"})
        assert ws.receive_json() == {"type": "error", "code": "unknown_type"}


# --------------------------------------------------------------------------- #
# Beamer (read-only, P(meeting.manage))
# --------------------------------------------------------------------------- #
def _beamer() -> Principal:
    return Principal(sub="adm", permissions={"meeting.manage"}, groups=set())


def test_beamer_requires_manage_permission() -> None:
    meeting = _meeting()
    app, _, _ = _build(meeting=meeting, principal=_voter(groups=set()))
    client = TestClient(app)
    with client.websocket_connect(_url(meeting) + "/beamer") as ws:
        assert ws.receive_json() == {"type": "error", "code": "not_eligible"}


def test_beamer_receives_state_but_cannot_cast() -> None:
    meeting = _meeting()
    app, voting, _ = _build(meeting=meeting, principal=_beamer())
    client = TestClient(app)
    with client.websocket_connect(_url(meeting) + "/beamer") as ws:
        assert ws.receive_json()["type"] == "meeting_state"
        ws.send_json({"type": "cast", "voteId": str(uuid4()), "choice": "yes"})
        assert ws.receive_json() == {"type": "error", "code": "read_only"}
    assert voting.casts == []
