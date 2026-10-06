"""LiveVoteConnection internals (T-16): the beamer fan-out filter (requirements N1a).

The beamer stream is read-only. It passes **only** ``meeting_state``, ``vote_opened``,
``vote_tally`` and ``vote_closed``. The fan-out drops everything else, for example an
internal event. The voter channel passes everything through.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.auth.principal import Principal
from app.modules.livevote.broker import InMemoryBroker
from app.modules.livevote.connection import (
    WS_FORBIDDEN,
    LiveVoteConnection,
    origin_allowed,
    resolve_ws_principal,
)
from app.modules.livevote.locks import InMemoryLocker
from app.modules.voting.schemas import TallyOut, VoteOut
from app.shared.config_schemas import VoteConfig


class _FakeWS:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send_json(self, data: dict[str, object]) -> None:
        self.sent.append(data)


class _Sub:
    def __init__(self, items: list[dict[str, object]]) -> None:
        self._items = items

    async def __aiter__(self) -> AsyncIterator[dict[str, object]]:
        for item in self._items:
            yield item


def _conn(*, beamer: bool) -> LiveVoteConnection:
    return LiveVoteConnection(
        _FakeWS(),  # type: ignore[arg-type]
        uuid4(),
        beamer=beamer,
        principal=Principal(sub="p"),
        meetings=object(),  # type: ignore[arg-type]
        voting=object(),  # type: ignore[arg-type]
        broker=InMemoryBroker(),
        locker=InMemoryLocker(),
    )


# Whitelisted aggregate events plus two events that carry a voter identity. An audit
# channel or a cast channel can carry such events. The beamer must never receive them.
_IDENTITY_EVENTS = [
    {"type": "ballot_cast", "voter": "alice", "choice": "yes"},
    {"type": "internal_secret", "voters": ["alice", "bob"]},
]
_STREAM = [
    {"type": "meeting_state", "status": "live"},
    {"type": "vote_opened", "voteId": "v"},
    _IDENTITY_EVENTS[0],
    {"type": "vote_tally", "counts": {"yes": 1}},
    _IDENTITY_EVENTS[1],
    {"type": "vote_closed", "result": "passed", "counts": {"yes": 1}},
]


@pytest.mark.asyncio
async def test_beamer_pump_drops_non_whitelisted_events() -> None:
    conn = _conn(beamer=True)
    await conn._pump(_Sub(_STREAM))
    sent = conn.ws.sent  # type: ignore[attr-defined]
    types_sent = [m["type"] for m in sent]
    # Only the four aggregate event types reach the beamer (api.md §4).
    assert types_sent == ["meeting_state", "vote_opened", "vote_tally", "vote_closed"]
    # N1a ballot secrecy: the fan-out passes no event that carries an identity.
    assert all(ev not in sent for ev in _IDENTITY_EVENTS)
    # No voter field and no voters field leaks over the beamer feed.
    assert all("voter" not in m and "voters" not in m for m in sent)


@pytest.mark.asyncio
async def test_voter_pump_passes_everything_through() -> None:
    conn = _conn(beamer=False)
    await conn._pump(_Sub(_STREAM))
    types_sent = [m["type"] for m in conn.ws.sent]  # type: ignore[attr-defined]
    assert types_sent == [m["type"] for m in _STREAM]


# FIX 4: the origin allowlist at the WS handshake (CSWSH and CSRF).
def _settings(origins: list[str], base: str = "http://localhost") -> Any:
    return SimpleNamespace(
        cors_allow_origins=origins,
        public_base_url=base,
        session_cookie_name="ap_session",
    )


def test_origin_allowed_missing_header_passes() -> None:
    # Non-browser clients (native, MCP, CLI) send no Origin. The cookie gate is enough.
    assert origin_allowed(None, _settings([], base="https://app.example")) is True


def test_origin_allowed_no_configured_origins_passes() -> None:
    # Without configured origins AND without a base URL, the check stays open.
    assert origin_allowed("https://evil.example", _settings([], base="")) is True


def test_origin_allowed_matches_public_base_url() -> None:
    s = _settings([], base="https://app.example/")
    assert origin_allowed("https://app.example", s) is True


def test_origin_allowed_matches_configured_origin() -> None:
    s = _settings(["https://beamer.example"], base="https://app.example")
    assert origin_allowed("https://beamer.example/", s) is True


def test_origin_disallowed_foreign_origin() -> None:
    s = _settings(["https://app.example"], base="https://app.example")
    assert origin_allowed("https://evil.example", s) is False


class _HandshakeWS:
    """Minimal WS double for ``resolve_ws_principal`` on the origin path."""

    def __init__(self, origin: str | None) -> None:
        self.headers = {} if origin is None else {"origin": origin}
        self.cookies: dict[str, str] = {}
        self.closed_code: int | None = None

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.closed_code = code


@pytest.mark.asyncio
async def test_resolve_ws_principal_rejects_foreign_origin() -> None:
    ws = _HandshakeWS("https://evil.example")
    s = _settings(["https://app.example"], base="https://app.example")
    principal = await resolve_ws_principal(ws, object(), s)  # type: ignore[arg-type]
    assert principal is None
    assert ws.closed_code == WS_FORBIDDEN
    # After that, ``close`` is a no-op. A second close from the router stays silent.
    ws.closed_code = None
    await ws.close(code=4401)
    assert ws.closed_code is None


@pytest.mark.asyncio
async def test_resolve_ws_principal_no_cookie_after_origin_ok() -> None:
    # No Origin header, so the origin check passes. The cookie is missing. The call
    # gives None on the regular 4401 path and not on the 4403 path.
    ws = _HandshakeWS(None)
    s = _settings([], base="https://app.example")
    principal = await resolve_ws_principal(ws, object(), s)  # type: ignore[arg-type]
    assert principal is None
    assert ws.closed_code is None


# FIX 5: the inbound throttle (token bucket).
def test_allow_frame_burst_then_throttles() -> None:
    conn = _conn(beamer=False)
    conn._tokens = 3.0
    conn._last_refill = time.monotonic()
    # Three tokens allow three frames. The fourth frame blocks without a refill.
    assert conn._allow_frame() is True
    assert conn._allow_frame() is True
    assert conn._allow_frame() is True
    # A refill in the same time slice stays far below one token.
    conn._last_refill = time.monotonic()
    conn._tokens = 0.0
    assert conn._allow_frame() is False


def test_allow_frame_refills_over_time() -> None:
    conn = _conn(beamer=False)
    conn._tokens = 0.0
    # The last refill lies far in the past, so the bucket fills up to the burst size.
    conn._last_refill = time.monotonic() - 100.0
    assert conn._allow_frame() is True


@pytest.mark.asyncio
async def test_receive_drops_rate_limited_frames() -> None:
    conn = _conn(beamer=False)
    frames: list[dict[str, object]] = [{"type": "subscribe"} for _ in range(30)]

    class _FloodWS:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []
            self._frames = list(frames)

        async def send_json(self, data: dict[str, object]) -> None:
            self.sent.append(data)

        async def receive_json(self) -> dict[str, object]:
            if self._frames:
                return self._frames.pop(0)
            raise asyncio.CancelledError

    ws = _FloodWS()
    conn.ws = ws  # type: ignore[assignment]
    # ``subscribe`` calls ``_send_state``, which calls ``meetings.get``. This test
    # measures only the throttle. A no-op replaces the handler and counts
    # ``rate_limited``.
    handled: list[dict[str, object]] = []

    async def _noop_handle(raw: dict[str, object]) -> None:
        handled.append(raw)

    conn._handle_message = _noop_handle  # type: ignore[assignment]
    with pytest.raises(asyncio.CancelledError):
        await conn._receive()
    # The burst of 10 frames passes. The connection drops the rest as rate_limited.
    assert len(handled) == 10
    assert all(s == {"type": "error", "code": "rate_limited"} for s in ws.sent)
    assert len(ws.sent) == 20


# FIX 6: run() tears the connection down when the pump dies. It must not hang.
class _RunWS:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send_json(self, data: dict[str, object]) -> None:
        self.sent.append(data)

    async def receive_json(self) -> dict[str, object]:
        # The receive blocks forever. Only a dying pump may end run().
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class _BoomBroker:
    """Broker whose subscription raises on the first iteration to crash the pump."""

    def subscribe(self, _channel: str) -> Any:
        broker = self

        class _Ctx:
            async def __aenter__(self) -> Any:
                return broker._iter()

            async def __aexit__(self, *exc: object) -> bool:
                return False

        return _Ctx()

    async def _iter(self) -> AsyncIterator[dict[str, object]]:
        raise RuntimeError("pump exploded")
        yield  # pragma: no cover

    async def publish(self, _channel: str, _payload: dict[str, object]) -> None:
        return None


@pytest.mark.asyncio
async def test_run_dead_pump_tears_down_connection() -> None:
    conn = LiveVoteConnection(
        _RunWS(),  # type: ignore[arg-type]
        uuid4(),
        beamer=True,  # a beamer needs no presence call and no state DB call
        principal=Principal(sub="p"),
        meetings=_StateMeetings(),  # type: ignore[arg-type]
        voting=object(),  # type: ignore[arg-type]
        broker=_BoomBroker(),  # type: ignore[arg-type]
        locker=InMemoryLocker(),
    )
    # The call run() must NOT hang. The crashed pump ends the race.
    await asyncio.wait_for(conn.run(), timeout=2.0)


class _StateMeetings:
    async def get(self, _meeting_id: UUID, _principal: object = None) -> Any:  # noqa: ANN001, F821
        return SimpleNamespace(
            active_application_id=None, current_agenda_item_id=None, status="live"
        )

    async def open_vote(self, _meeting_id: UUID) -> object:  # noqa: F821
        return None


# AUD-065: cast binds the vote id to the authorized meeting of the connection.
class _MeetingBoundVoting:
    """Fake VotingService for the meeting binding of a cast.

    ``get`` returns a vote with a fixed meeting_id. ``cast`` counts the calls. A
    cross-meeting frame must NEVER reach ``cast``.
    """

    def __init__(self, vote_meeting_id: UUID, *, account_ok: bool = True) -> None:
        self._vote_meeting_id = vote_meeting_id
        self.cast_calls = 0
        self.account_ok = account_ok
        # The connection re-reads the account through the session of the service.
        self.session = self
        self.statements: list[object] = []

    async def scalar(self, stmt: object) -> int:
        self.statements.append(stmt)
        return 1 if self.account_ok else 0

    async def get(self, vote_id: UUID) -> Any:
        return SimpleNamespace(id=vote_id, meeting_id=self._vote_meeting_id)

    async def cast(self, *args: object, **kwargs: object) -> None:
        self.cast_calls += 1


@pytest.mark.asyncio
async def test_cast_rejects_vote_from_other_meeting() -> None:
    other_meeting = uuid4()
    voting = _MeetingBoundVoting(other_meeting)
    conn = _conn(beamer=False)
    # conn.meeting_id is its own uuid4 and differs from other_meeting.
    conn.voting = voting  # type: ignore[assignment]
    await conn._handle_cast(
        {"type": "cast", "voteId": str(uuid4()), "choice": "yes"}
    )
    # The connection rejects the frame before it reaches the DB cast or the lock.
    assert voting.cast_calls == 0
    assert conn.ws.sent == [{"type": "error", "code": "not_eligible"}]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_cast_allows_vote_from_own_meeting() -> None:
    conn = _conn(beamer=False)
    voting = _MeetingBoundVoting(conn.meeting_id)  # the vote belongs to the own meeting
    conn.voting = voting  # type: ignore[assignment]

    published: list[object] = []

    async def _stub_tally(vote: object) -> None:
        published.append(vote)

    conn.publisher.vote_tally = _stub_tally  # type: ignore[method-assign]
    await conn._handle_cast(
        {"type": "cast", "voteId": str(uuid4()), "choice": "yes"}
    )
    # The meeting binding holds, so cast runs exactly once and no error frame goes out.
    assert voting.cast_calls == 1
    assert published  # the publisher sent the tally
    assert all(s.get("code") != "not_eligible" for s in conn.ws.sent)  # type: ignore[attr-defined]


# The state on a connect marks its `vote_opened` as a replay, so that a client does
# not take a vote that is already open for a vote that opens now.
class _OpenVoteMeetings(_StateMeetings):
    def __init__(self, vote_id: UUID) -> None:
        self._vote_id = vote_id

    async def open_vote(self, _meeting_id: UUID) -> object:  # noqa: F821
        return SimpleNamespace(id=self._vote_id)


class _OpenVoteVoting:
    async def get(self, vote_id: UUID) -> VoteOut:
        return VoteOut(
            id=vote_id,
            applicationId=uuid4(),
            meetingId=uuid4(),
            eligibleGroup="stupa",
            config=VoteConfig.model_validate(
                {"options": ["yes", "no"], "majorityRule": "simple", "secret": False}
            ),
            status="open",
            secret=False,
            tally=TallyOut(
                counts={"yes": 1},
                eligible=5,
                voted=1,
                present=5,
                revealed=True,
                quorumMet=False,
                leading="yes",
            ),
        )


@pytest.mark.asyncio
async def test_send_state_marks_the_open_vote_as_replay() -> None:
    vote_id = uuid4()
    conn = _conn(beamer=False)
    conn.meetings = _OpenVoteMeetings(vote_id)  # type: ignore[assignment]
    conn.voting = _OpenVoteVoting()  # type: ignore[assignment]
    await conn._send_state()
    sent = conn.ws.sent  # type: ignore[attr-defined]
    assert [m["type"] for m in sent] == ["meeting_state", "vote_opened", "vote_tally"]
    assert sent[1]["voteId"] == str(vote_id)
    assert sent[1]["replay"] is True


# An open socket must not cast for an account that an admin deactivated or merged
# after the handshake: the connection re-reads the account before each cast.
@pytest.mark.asyncio
async def test_cast_refused_when_the_account_is_no_longer_active() -> None:
    conn = _conn(beamer=False)
    voting = _MeetingBoundVoting(conn.meeting_id, account_ok=False)
    conn.voting = voting  # type: ignore[assignment]
    await conn._handle_cast({"type": "cast", "voteId": str(uuid4()), "choice": "yes"})
    assert voting.cast_calls == 0
    assert conn.ws.sent == [{"type": "error", "code": "account_inactive"}]  # type: ignore[attr-defined]
    stmt = str(voting.statements[0])
    assert "principal.active" in stmt and "principal.merged_into IS NULL" in stmt
