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

    async def get(self, _meeting_id: UUID, _principal: object = None) -> MeetingOut:
        if self._meeting is None:
            from app.shared.errors import NotFoundError

            raise NotFoundError("meeting not found")
        return self._meeting

    async def open_vote(self, _meeting_id: UUID) -> object:
        return self._open_vote

    async def is_member(self, gremium_id: UUID, principal: Principal) -> bool:
        # Live-Mitlesen = aktives Gremium-Mitglied; im Fake über die Gruppe gespiegelt.
        return "admin" in principal.roles or principal.in_group(str(gremium_id))

    async def is_participant(
        self, _meeting_id: UUID, gremium_id: UUID, principal: Principal
    ) -> bool:
        # #delegation-rework: Mitglied ODER Delegations-Empfänger; der Fake kennt
        # keine Delegationen → Mitgliedschaft genügt.
        return await self.is_member(gremium_id, principal)


class _FakeVotingService:
    def __init__(self, vote_out: VoteOut, exc: Exception | None = None) -> None:
        self.session = _FakeSession()
        self._vote_out = vote_out
        self._exc = exc
        self.casts: list[tuple[UUID, str, str]] = []

    async def cast(
        self, vote_id: UUID, principal: Principal, choice: str, *, now, as_delegation: bool = False
    ) -> None:  # noqa: ANN001
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


def _recv(ws) -> dict:  # noqa: ANN001 — Starlette-Test-WS
    """Nächstes Event, Presence-Frames übersprungen (#live-viewers): der
    ``viewers``-Broadcast feuert beim Connect/Disconnect asynchron dazwischen."""
    msg = ws.receive_json()
    while isinstance(msg, dict) and msg.get("type") == "viewers":
        msg = ws.receive_json()
    return msg


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
        assert _recv(ws) == {"type": "error", "code": "not_eligible"}


# --------------------------------------------------------------------------- #
# Voter-Lifecycle
# --------------------------------------------------------------------------- #
def test_connect_sends_meeting_state() -> None:
    meeting = _meeting()
    app, _, _ = _build(meeting=meeting, principal=_voter())
    client = TestClient(app)
    with client.websocket_connect(_url(meeting)) as ws:
        state = _recv(ws)
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
    app, _, _ = _build(
        meeting=meeting, principal=_voter(), vote_out=vote_out, voting_exc=exc
    )
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
    meeting = _meeting()
    app, _, _ = _build(meeting=meeting, principal=_voter())
    client = TestClient(app)
    with client.websocket_connect(_url(meeting)) as ws:
        assert _recv(ws)["type"] == "meeting_state"
        ws.send_json({"type": "cast"})  # voteId/choice fehlen
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
    meeting = _meeting()
    app, _, _ = _build(meeting=meeting, principal=_voter())
    client = TestClient(app)
    with client.websocket_connect(_url(meeting)) as ws:
        assert _recv(ws)["type"] == "meeting_state"
        ws.send_text("not-json{")  # kaputter Frame → error statt Crash
        assert _recv(ws) == {"type": "error", "code": "invalid_message"}
        # Verbindung lebt weiter: gültige Folge-Nachricht wird normal bedient.
        ws.send_json({"type": "subscribe"})
        assert _recv(ws)["type"] == "meeting_state"


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


# --------------------------------------------------------------------------- #
# Realer Handshake-Auth-Pfad (Cookie → Session → RBAC-Principal)
#
# Anders als oben wird ``get_ws_principal`` **nicht** überschrieben: der echte
# ``resolve_ws_principal`` läuft (Cookie entsiegeln → ``auth_session`` → ``principal``
# → RBAC). Nur ``get_session`` liefert einen gequeueten Fake (kein Postgres). Deckt
# die Lücke, die den Meeting-WS-403 maskiert hat: ein eingeloggter, berechtigter
# Nutzer mit zeit-validiertem RoleAssignment.
# --------------------------------------------------------------------------- #
from tests.auth_fakes import fake_session, result  # noqa: E402

_SID = "ws-handshake-sid"


def _signed_cookie() -> tuple[str, str]:
    settings = get_settings()
    return settings.session_cookie_name, sessions._sign_sid(settings.session_secret, _SID)


def _auth_db(*, naive: bool):
    """Fake-Session für den realen Handshake: AuthSession → Principal → RBAC."""
    pid = uuid4()
    now = datetime.now(UTC)
    vf, vu = now - timedelta(days=1), now + timedelta(days=1)
    if naive:  # so, wie eine ``timestamp``-Spalte (ohne tz) aus der DB käme
        vf, vu = vf.replace(tzinfo=None), vu.replace(tzinfo=None)
    auth_session = AuthSession(
        sid=_SID, principal_id=pid, expires_at=now + timedelta(hours=1),
        refresh_token=None, id_token=None,
    )
    principal_row = PrincipalRow(
        sub="member", email=None, display_name="M", oidc_groups=[]
    )
    principal_row.id = pid  # type: ignore[assignment]
    assignment = RoleAssignment(
        principal_id=pid, role_id=uuid4(), gremium_id=_GREMIUM,
        valid_from=vf, valid_until=vu,
    )

    def factory():
        return fake_session(
            result(auth_session),     # load_principal_session → AuthSession
            result(principal_row),    # PrincipalRow
            result(assignment),       # RoleAssignment (im Sitzungs-Gremium)
            result(),                 # GroupMapping (keine)
            result("vote.cast"),      # RolePermission
            result("member"),         # Role.key
        )

    async def _override():
        yield factory()

    return _override


def _build_real_handshake(*, naive: bool):
    meeting = _meeting()
    app = create_app()
    app.dependency_overrides[get_session] = _auth_db(naive=naive)
    app.dependency_overrides[get_meeting_service_ws] = (
        lambda: _FakeMeetingService(meeting, None)
    )
    app.dependency_overrides[get_voting_service_ws] = (
        lambda: _FakeVotingService(_vote_out(meeting.id))
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
    """Regression Meeting-WS-403: naive ``valid_from``/``valid_until`` aus der DB.

    Vor dem Fix warf ``rbac._assignment_valid`` in ``resolve_ws_principal``
    ``TypeError`` → die ``get_ws_principal``-Dependency scheiterte → Handshake
    abgelehnt. Jetzt löst der Principal sauber auf und der Socket öffnet.
    """
    app, meeting = _build_real_handshake(naive=True)
    client = TestClient(app)
    name, value = _signed_cookie()
    client.cookies.set(name, value)
    with client.websocket_connect(_url(meeting)) as ws:
        assert _recv(ws)["type"] == "meeting_state"


def test_handshake_without_cookie_is_rejected() -> None:
    """Ohne Cookie kein Principal → Close vor Accept (Handshake scheitert)."""
    app, meeting = _build_real_handshake(naive=False)
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(_url(meeting)):
        pass
