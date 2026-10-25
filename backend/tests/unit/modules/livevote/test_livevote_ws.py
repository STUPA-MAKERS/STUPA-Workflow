"""Live-vote WebSocket behavior, driven through TestClient.

TestClient stands in for httpx-ws. The tests cover the handshake auth and RBAC
(4401, 4404, not_eligible). They cover the voter lifecycle: connect to meeting_state,
the `subscribe` reconnect state and cast to `vote_tally` broadcast. They also cover the
cast errors (lock, conflict, eligibility, invalid) and the read-only beamer stream.
`dependency_overrides` replaces the services, the principal, the broker and the lock, so
the tests need no database and no Redis. The integration test covers the real race and
the real fan-out.

The handshake tests run the real auth path from the cookie to the session to the RBAC
principal. They do not override `get_ws_principal`, so the real `resolve_ws_principal`
unseals the cookie, loads the `auth_session` and the `principal` and resolves RBAC. Only
`get_session` returns a queued fake, so the tests need no Postgres. They cover a logged-in
user with the permission and a time-validated role assignment.
"""

from __future__ import annotations

import types
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.db import get_session
from app.main import create_app
from app.modules.auth import sessions
from app.modules.auth.models import AuthSession, RoleAssignment
from app.modules.auth.models import Principal as PrincipalRow
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
from app.settings import get_settings
from app.shared.config_schemas import VoteConfig
from app.shared.errors import ConflictError, ForbiddenError

_CONFIG = VoteConfig.model_validate({"options": ["yes", "no"], "majorityRule": "simple"})
_GREMIUM = uuid4()


def _meeting(status: MeetingStatus = "live") -> MeetingOut:
    return MeetingOut(
        id=uuid4(),
        gremiumId=_GREMIUM,
        title="GV",
        status=status,
        activeApplicationId=None,
        createdAt=datetime(2026, 6, 8, tzinfo=UTC),
    )


def _vote_out(meeting_id: UUID) -> VoteOut:
    return VoteOut(
        id=uuid4(),
        applicationId=uuid4(),
        meetingId=meeting_id,
        eligibleGroup="stupa",
        config=_CONFIG,
        status="open",
        secret=False,
        tally=TallyOut(counts={"yes": 1, "no": 0}, eligible=5, quorumMet=False, leading="yes"),
    )


class _FakeSession:
    async def rollback(self) -> None:
        return None

    async def scalar(self, _stmt: object) -> int:
        """Return one live account row, because the cast reads the account again."""
        return 1


class _FakeMeetingService:
    def __init__(self, meeting: MeetingOut | None, open_vote: object = None) -> None:
        self._meeting = meeting
        self._open_vote = open_vote

    async def get(self, _meeting_id: UUID, _principal: object = None) -> MeetingOut:
        if self._meeting is None:
            from app.shared.errors import NotFoundError

            raise NotFoundError("meeting not found")
        return self._meeting

    async def open_vote(self, _meeting_id: UUID) -> object:
        return self._open_vote

    async def is_member(self, gremium_id: UUID, principal: Principal) -> bool:
        """Mirror the active Gremium membership through the group.

        The live read access needs an active membership.
        """
        return "admin" in principal.roles or principal.in_group(str(gremium_id))

    async def can_manage(self, gremium_id: UUID, principal: Principal) -> bool:
        """Mirror `session.manage` in the gremium through the group `manage:<gremium id>`."""
        return "admin" in principal.roles or principal.in_group(f"manage:{gremium_id}")

    async def is_participant(
        self, _meeting_id: UUID, gremium_id: UUID, principal: Principal
    ) -> bool:
        """Pass a member or a delegation receiver.

        The fake knows no delegations, so the membership is enough here.
        """
        return await self.is_member(gremium_id, principal)


class _FakeVotingService:
    def __init__(self, vote_out: VoteOut, exc: Exception | None = None) -> None:
        self.session = _FakeSession()
        self._vote_out = vote_out
        self._exc = exc
        self.casts: list[tuple[UUID, str, str]] = []

    async def cast(
        self, vote_id: UUID, principal: Principal, choice: str, *, now, as_delegation: bool = False
    ) -> None:
        if self._exc is not None:
            raise self._exc
        self.casts.append((vote_id, choice, principal.sub))

    async def get(self, _vote_id: UUID) -> VoteOut:
        return self._vote_out


class _BusyLocker:
    """Return `False` always to model a taken lock during a concurrent cast."""

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


def _recv(ws) -> dict:
    """Return the next event and skip the presence frames.

    The `viewers` broadcast fires asynchronously on a connect or a disconnect. It can
    arrive between two expected events.

    The socket is the WebSocket session of the Starlette test client.
    """
    msg = ws.receive_json()
    while isinstance(msg, dict) and msg.get("type") == "viewers":
        msg = ws.receive_json()
    return msg


def _url(meeting: MeetingOut) -> str:
    return f"/api/ws/meetings/{meeting.id}"


def test_unauthenticated_is_closed_before_accept() -> None:
    meeting = _meeting()
    app, _, _ = _build(meeting=meeting, principal=None)
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(_url(meeting)):
        pass


def test_unknown_meeting_is_closed() -> None:
    app, _, _ = _build(meeting=None, principal=_voter())
    client = TestClient(app)
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/api/ws/meetings/" + str(uuid4())),
    ):
        pass


def test_not_in_group_gets_not_eligible_error() -> None:
    meeting = _meeting()
    app, _, _ = _build(meeting=meeting, principal=_voter(groups=set()))
    client = TestClient(app)
    with client.websocket_connect(_url(meeting)) as ws:
        assert _recv(ws) == {"type": "error", "code": "not_eligible"}


def test_connect_sends_meeting_state() -> None:
    """Send the meeting state on connect.

    The initial state carries the item the room handles now, so a follower who connects late
    lands on the right item.
    """
    meeting = _meeting()
    meeting.current_agenda_item_id = uuid4()
    app, _, _ = _build(meeting=meeting, principal=_voter())
    client = TestClient(app)
    with client.websocket_connect(_url(meeting)) as ws:
        state = _recv(ws)
    assert state["type"] == "meeting_state"
    assert state["status"] == "live"
    assert state["currentAgendaItemId"] == str(meeting.current_agenda_item_id)


def test_subscribe_resends_state_with_open_vote() -> None:
    """Send the state again with the open vote on a subscribe.

    The connect already delivers the full state, including the open vote.
    """
    meeting = _meeting()
    vote_out = _vote_out(meeting.id)
    open_vote = types.SimpleNamespace(id=vote_out.id)
    app, _, _ = _build(meeting=meeting, principal=_voter(), vote_out=vote_out, open_vote=open_vote)
    client = TestClient(app)
    with client.websocket_connect(_url(meeting)) as ws:
        assert _recv(ws)["type"] == "meeting_state"
        assert _recv(ws)["type"] == "vote_opened"
        assert _recv(ws)["type"] == "vote_tally"
        ws.send_json({"type": "subscribe"})
        assert _recv(ws)["type"] == "meeting_state"
        assert _recv(ws)["type"] == "vote_opened"
        assert _recv(ws)["type"] == "vote_tally"


def test_cast_records_vote_and_broadcasts_tally() -> None:
    meeting = _meeting()
    vote_out = _vote_out(meeting.id)
    app, voting, _ = _build(meeting=meeting, principal=_voter(), vote_out=vote_out)
    client = TestClient(app)
    with client.websocket_connect(_url(meeting)) as ws:
        assert _recv(ws)["type"] == "meeting_state"
        ws.send_json({"type": "cast", "voteId": str(vote_out.id), "choice": "yes"})
        tally = _recv(ws)
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
    app, _, _ = _build(meeting=meeting, principal=_voter(), vote_out=vote_out, voting_exc=exc)
    client = TestClient(app)
    with client.websocket_connect(_url(meeting)) as ws:
        assert _recv(ws)["type"] == "meeting_state"
        ws.send_json({"type": "cast", "voteId": str(vote_out.id), "choice": "yes"})
        assert _recv(ws) == {"type": "error", "code": expected}


def test_cast_when_locked_reports_locked() -> None:
    meeting = _meeting()
    app, _, _ = _build(meeting=meeting, principal=_voter(), locker=_BusyLocker())
    client = TestClient(app)
    with client.websocket_connect(_url(meeting)) as ws:
        assert _recv(ws)["type"] == "meeting_state"
        ws.send_json({"type": "cast", "voteId": str(uuid4()), "choice": "yes"})
        assert _recv(ws) == {"type": "error", "code": "locked"}


def test_invalid_cast_message_reports_invalid() -> None:
    """Answer `invalid_message` to a cast without `voteId` and `choice`."""
    meeting = _meeting()
    app, _, _ = _build(meeting=meeting, principal=_voter())
    client = TestClient(app)
    with client.websocket_connect(_url(meeting)) as ws:
        assert _recv(ws)["type"] == "meeting_state"
        ws.send_json({"type": "cast"})
        assert _recv(ws) == {"type": "error", "code": "invalid_message"}


def test_unknown_message_type_reports_error() -> None:
    meeting = _meeting()
    app, _, _ = _build(meeting=meeting, principal=_voter())
    client = TestClient(app)
    with client.websocket_connect(_url(meeting)) as ws:
        assert _recv(ws)["type"] == "meeting_state"
        ws.send_json({"type": "weird"})
        assert _recv(ws) == {"type": "error", "code": "unknown_type"}


def test_malformed_json_frame_does_not_crash_connection() -> None:
    """Keep the connection alive after a malformed JSON frame.

    A broken frame gives an error, not a crash, and the server serves the next valid
    message.
    """
    meeting = _meeting()
    app, _, _ = _build(meeting=meeting, principal=_voter())
    client = TestClient(app)
    with client.websocket_connect(_url(meeting)) as ws:
        assert _recv(ws)["type"] == "meeting_state"
        ws.send_text("not-json{")
        assert _recv(ws) == {"type": "error", "code": "invalid_message"}
        ws.send_json({"type": "subscribe"})
        assert _recv(ws)["type"] == "meeting_state"


def _beamer() -> Principal:
    return Principal(sub="chair", groups={str(_GREMIUM), f"manage:{_GREMIUM}"})


def test_beamer_requires_manage_permission() -> None:
    meeting = _meeting()
    app, _, _ = _build(meeting=meeting, principal=_voter(groups=set()))
    client = TestClient(app)
    with client.websocket_connect(_url(meeting) + "/beamer") as ws:
        assert _recv(ws) == {"type": "error", "code": "not_eligible"}


def test_beamer_refuses_a_member_without_session_manage() -> None:
    """A plain member of the gremium follows the voter channel, not the beamer."""
    meeting = _meeting()
    app, _, _ = _build(meeting=meeting, principal=_voter())
    client = TestClient(app)
    with client.websocket_connect(_url(meeting) + "/beamer") as ws:
        assert _recv(ws) == {"type": "error", "code": "not_eligible"}


def test_beamer_refuses_session_manage_of_another_gremium() -> None:
    """`session.manage` counts only in the gremium of the meeting (4403 otherwise)."""
    meeting = _meeting()
    other = Principal(sub="chair", groups={f"manage:{uuid4()}"})
    app, _, _ = _build(meeting=meeting, principal=other)
    client = TestClient(app)
    with client.websocket_connect(_url(meeting) + "/beamer") as ws:
        assert _recv(ws) == {"type": "error", "code": "not_eligible"}


def test_beamer_receives_state_but_cannot_cast() -> None:
    meeting = _meeting()
    app, voting, _ = _build(meeting=meeting, principal=_beamer())
    client = TestClient(app)
    with client.websocket_connect(_url(meeting) + "/beamer") as ws:
        assert _recv(ws)["type"] == "meeting_state"
        ws.send_json({"type": "cast", "voteId": str(uuid4()), "choice": "yes"})
        assert _recv(ws) == {"type": "error", "code": "read_only"}
    assert voting.casts == []


from tests._support.auth_fakes import fake_session, result  # noqa: E402

_SID = "ws-handshake-sid"


def _signed_cookie() -> tuple[str, str]:
    settings = get_settings()
    return settings.session_cookie_name, sessions._sign_sid(settings.session_secret, _SID)


def _auth_db(*, naive: bool):
    """Build a fake session for the real handshake: AuthSession, Principal, then RBAC.

    A naive value is how a `timestamp` column without a time zone comes from the database.
    """
    pid = uuid4()
    now = datetime.now(UTC)
    vf, vu = now - timedelta(days=1), now + timedelta(days=1)
    if naive:
        vf, vu = vf.replace(tzinfo=None), vu.replace(tzinfo=None)
    auth_session = AuthSession(
        sid=_SID,
        principal_id=pid,
        expires_at=now + timedelta(hours=1),
        refresh_token=None,
        id_token=None,
        revalidated_at=now,
    )
    principal_row = PrincipalRow(sub="member", email=None, display_name="M", oidc_groups=[])
    principal_row.id = pid
    assignment = RoleAssignment(
        principal_id=pid,
        role_id=uuid4(),
        gremium_id=_GREMIUM,
        valid_from=vf,
        valid_until=vu,
    )

    def factory():
        """Return the scripted session.

        The results, in order: the auth session, the principal row, the role assignment in
        the meeting Gremium, no group mapping, the role permission and the role key.
        """
        return fake_session(
            result(auth_session),
            result(principal_row),
            result(assignment),
            result(),
            result("vote.cast"),
            result("member"),
        )

    async def _override():
        yield factory()

    return _override


def _build_real_handshake(*, naive: bool):
    meeting = _meeting()
    app = create_app()
    app.dependency_overrides[get_session] = _auth_db(naive=naive)
    app.dependency_overrides[get_meeting_service_ws] = lambda: _FakeMeetingService(meeting, None)
    app.dependency_overrides[get_voting_service_ws] = lambda: _FakeVotingService(
        _vote_out(meeting.id)
    )
    app.dependency_overrides[get_broker_ws] = lambda: InMemoryBroker()
    app.dependency_overrides[get_locker_ws] = lambda: InMemoryLocker()
    return app, meeting


def test_handshake_with_valid_cookie_opens_socket() -> None:
    app, meeting = _build_real_handshake(naive=False)
    client = TestClient(app)
    name, value = _signed_cookie()
    client.cookies.set(name, value)
    with client.websocket_connect(_url(meeting)) as ws:
        state = _recv(ws)
    assert state["type"] == "meeting_state"
    assert state["status"] == "live"


def test_handshake_with_naive_assignment_does_not_403() -> None:
    """Regression meeting WS 403: naive `valid_from` and `valid_until` from the database.

    Before the fix, `rbac._assignment_valid` raised `TypeError` inside
    `resolve_ws_principal`. The `get_ws_principal` dependency then failed and the server
    rejected the handshake. Now the principal resolves and the socket opens.
    """
    app, meeting = _build_real_handshake(naive=True)
    client = TestClient(app)
    name, value = _signed_cookie()
    client.cookies.set(name, value)
    with client.websocket_connect(_url(meeting)) as ws:
        assert _recv(ws)["type"] == "meeting_state"


def test_handshake_without_cookie_is_rejected() -> None:
    """Without a cookie there is no principal, so the server closes before the accept."""
    app, meeting = _build_real_handshake(naive=False)
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(_url(meeting)):
        pass


def test_handshake_foreign_origin_is_rejected() -> None:
    """A foreign `Origin` closes the handshake with 4403.

    The check runs before the cookie path and before the RBAC path. The second close of
    the router passes silently.
    """
    app, meeting = _build_real_handshake(naive=False)
    client = TestClient(app)
    name, value = _signed_cookie()
    client.cookies.set(name, value)
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect(_url(meeting), headers={"origin": "https://evil.example"}),
    ):
        pass
    assert exc.value.code == 4403


@pytest.mark.parametrize("suffix", ["", "/beamer"])
def test_real_flow_dispatcher_override_reaches_the_socket(suffix: str) -> None:
    """Regression: the `get_action_dispatcher` override of `app.main` works on a socket.

    `get_voting_service_ws` depends on `get_action_dispatcher`. `create_app()` replaces
    that provider with `_flow_action_dispatcher`. FastAPI does not inject a `Request`
    into a WebSocket dependency, so an override that takes `request: Request` raised
    `TypeError` before the handshake. This test keeps the real voting service and the
    real override. Without a cookie the socket must close normally (no principal).
    """
    meeting = _meeting()
    app = create_app()
    app.dependency_overrides[get_session] = _auth_db(naive=False)
    app.dependency_overrides[get_meeting_service_ws] = lambda: _FakeMeetingService(meeting, None)
    app.dependency_overrides[get_broker_ws] = lambda: InMemoryBroker()
    app.dependency_overrides[get_locker_ws] = lambda: InMemoryLocker()
    assert get_voting_service_ws not in app.dependency_overrides
    client = TestClient(app)
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect(_url(meeting) + suffix),
    ):
        pass
    assert exc.value.code == 4401


def test_real_flow_dispatcher_override_opens_the_socket_with_a_cookie() -> None:
    """With a valid cookie the socket opens through the real dispatcher override."""
    meeting = _meeting()
    app = create_app()
    app.dependency_overrides[get_session] = _auth_db(naive=False)
    app.dependency_overrides[get_meeting_service_ws] = lambda: _FakeMeetingService(meeting, None)
    app.dependency_overrides[get_broker_ws] = lambda: InMemoryBroker()
    app.dependency_overrides[get_locker_ws] = lambda: InMemoryLocker()
    client = TestClient(app)
    name, value = _signed_cookie()
    client.cookies.set(name, value)
    with client.websocket_connect(_url(meeting)) as ws:
        assert _recv(ws)["type"] == "meeting_state"


from app.modules.livevote import router as lv_router  # noqa: E402


def test_connection_slot_acquire_release_cap() -> None:
    """Acquire and release the connection slots up to the cap.

    A full release drops the counter entry, so there is no memory leak. A release without a
    held slot is idempotent: no KeyError and no negative counter.
    """
    mid = uuid4()
    sub = "p"
    lv_router._connection_counts.clear()
    cap = lv_router._MAX_CONNECTIONS_PER_PRINCIPAL
    for _ in range(cap):
        assert lv_router._try_acquire_slot(mid, sub) is True
    assert lv_router._try_acquire_slot(mid, sub) is False
    lv_router._release_slot(mid, sub)
    assert lv_router._try_acquire_slot(mid, sub) is True
    for _ in range(cap):
        lv_router._release_slot(mid, sub)
    assert (mid, sub) not in lv_router._connection_counts
    lv_router._release_slot(mid, sub)
    assert (mid, sub) not in lv_router._connection_counts


def test_too_many_connections_rejected_over_ws() -> None:
    """Reject a connect over the cap.

    The test fills the slots up to the limit, so the server refuses the next connect.
    """
    meeting = _meeting()
    app, _, _ = _build(meeting=meeting, principal=_voter())
    lv_router._connection_counts.clear()
    key = (meeting.id, "p")
    lv_router._connection_counts[key] = lv_router._MAX_CONNECTIONS_PER_PRINCIPAL
    client = TestClient(app)
    try:
        with client.websocket_connect(_url(meeting)) as ws:
            assert _recv(ws) == {"type": "error", "code": "too_many_connections"}
    finally:
        lv_router._connection_counts.clear()
