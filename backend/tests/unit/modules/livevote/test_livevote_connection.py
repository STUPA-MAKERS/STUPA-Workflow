"""LiveVoteConnection-Interna (T-16): Beamer-Fan-out-Filter (requirements N1a).

Der Beamer-Stream ist read-only und darf **nur** ``meeting_state|vote_opened|
vote_tally|vote_closed`` durchlassen — alles andere (z. B. interne Events) wird im
Fan-out verworfen. Der Voter-Kanal reicht alles durch.
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


# Whitelisted Aggregat-Events + zwei NICHT-whitelisted, identitätstragende Events,
# wie sie z. B. ein Audit-/Cast-Kanal führen könnte — die dürfen den Beamer nie sehen.
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
    # Nur die vier Aggregat-Event-Typen erreichen den Beamer (api.md §4).
    assert types_sent == ["meeting_state", "vote_opened", "vote_tally", "vote_closed"]
    # N1a-Stimmgeheimnis: kein identitätstragendes Event wird durchgereicht …
    assert all(ev not in sent for ev in _IDENTITY_EVENTS)
    # … und keine voter/voters-Felder leaken über den Beamer-Feed.
    assert all("voter" not in m and "voters" not in m for m in sent)


@pytest.mark.asyncio
async def test_voter_pump_passes_everything_through() -> None:
    conn = _conn(beamer=False)
    await conn._pump(_Sub(_STREAM))
    types_sent = [m["type"] for m in conn.ws.sent]  # type: ignore[attr-defined]
    assert types_sent == [m["type"] for m in _STREAM]


# --------------------------------------------------------------------------- #
# FIX 4 — Origin-Allowlist am WS-Handshake (CSWSH/CSRF)
# --------------------------------------------------------------------------- #
def _settings(origins: list[str], base: str = "http://localhost") -> Any:
    return SimpleNamespace(
        cors_allow_origins=origins,
        public_base_url=base,
        session_cookie_name="ap_session",
    )


def test_origin_allowed_missing_header_passes() -> None:
    # Nicht-Browser-Clients (native/MCP/CLI) senden keinen Origin → Cookie-Gate genügt.
    assert origin_allowed(None, _settings([], base="https://app.example")) is True


def test_origin_allowed_no_configured_origins_passes() -> None:
    # Ohne konfigurierte Origins UND ohne Basis-URL bleibt das Verhalten offen.
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
    """Minimaler WS-Double für ``resolve_ws_principal`` (Origin-Pfad)."""

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
    # ``close`` ist danach ein No-op (Doppel-Close des Routers verpufft geräuschlos).
    ws.closed_code = None
    await ws.close(code=4401)
    assert ws.closed_code is None


@pytest.mark.asyncio
async def test_resolve_ws_principal_no_cookie_after_origin_ok() -> None:
    # Origin ok (kein Header) → Cookie fehlt → None (kein 4403, regulärer 4401-Pfad).
    ws = _HandshakeWS(None)
    s = _settings([], base="https://app.example")
    principal = await resolve_ws_principal(ws, object(), s)  # type: ignore[arg-type]
    assert principal is None
    assert ws.closed_code is None


# --------------------------------------------------------------------------- #
# FIX 5 — Inbound-Throttle (Token-Bucket)
# --------------------------------------------------------------------------- #
def test_allow_frame_burst_then_throttles() -> None:
    conn = _conn(beamer=False)
    conn._tokens = 3.0
    conn._last_refill = time.monotonic()
    # 3 Tokens da → 3 Frames erlaubt, der 4. (ohne Nachfüllung) blockiert.
    assert conn._allow_frame() is True
    assert conn._allow_frame() is True
    assert conn._allow_frame() is True
    # Refill in derselben Zeitscheibe ist vernachlässigbar → unter 1 Token.
    conn._last_refill = time.monotonic()
    conn._tokens = 0.0
    assert conn._allow_frame() is False


def test_allow_frame_refills_over_time() -> None:
    conn = _conn(beamer=False)
    conn._tokens = 0.0
    # Letztes Refill »weit« in der Vergangenheit → Bucket füllt auf den Burst.
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
    # ``subscribe`` ruft ``_send_state`` → ``meetings.get``; hier nur Throttle messen,
    # daher Handler durch einen No-op ersetzen (wir zählen nur ``rate_limited``).
    handled: list[dict[str, object]] = []

    async def _noop_handle(raw: dict[str, object]) -> None:
        handled.append(raw)

    conn._handle_message = _noop_handle  # type: ignore[assignment]
    with pytest.raises(asyncio.CancelledError):
        await conn._receive()
    # Burst (10) verarbeitet, der Rest als rate_limited verworfen.
    assert len(handled) == 10
    assert all(s == {"type": "error", "code": "rate_limited"} for s in ws.sent)
    assert len(ws.sent) == 20


# --------------------------------------------------------------------------- #
# FIX 6 — run(): toter Pump reißt die Verbindung ab (nicht still hängen)
# --------------------------------------------------------------------------- #
class _RunWS:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send_json(self, data: dict[str, object]) -> None:
        self.sent.append(data)

    async def receive_json(self) -> dict[str, object]:
        # Empfang blockiert »ewig« — nur ein sterbender Pump darf run() beenden.
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class _BoomBroker:
    """Broker, dessen Subscription beim ersten Iterieren explodiert (Pump-Crash)."""

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
        beamer=True,  # Beamer: keine Presence-/State-DB-Aufrufe nötig
        principal=Principal(sub="p"),
        meetings=_StateMeetings(),  # type: ignore[arg-type]
        voting=object(),  # type: ignore[arg-type]
        broker=_BoomBroker(),  # type: ignore[arg-type]
        locker=InMemoryLocker(),
    )
    # run() darf NICHT hängen: der gecrashte Pump beendet das Rennen.
    await asyncio.wait_for(conn.run(), timeout=2.0)


class _StateMeetings:
    async def get(self, _meeting_id: UUID, _principal: object = None) -> Any:  # noqa: ANN001, F821
        return SimpleNamespace(active_application_id=None, status="live")

    async def open_vote(self, _meeting_id: UUID) -> object:  # noqa: F821
        return None


# --------------------------------------------------------------------------- #
# AUD-065 — cast bindet vote_id an die autorisierte Sitzung der Verbindung
# --------------------------------------------------------------------------- #
class _MeetingBoundVoting:
    """Fake-VotingService: ``get`` liefert einen Vote mit fester meeting_id,
    ``cast`` zählt Aufrufe (darf bei Cross-Meeting-Frames NICHT erreicht werden)."""

    def __init__(self, vote_meeting_id: UUID) -> None:
        self._vote_meeting_id = vote_meeting_id
        self.cast_calls = 0

    async def get(self, vote_id: UUID) -> Any:
        return SimpleNamespace(id=vote_id, meeting_id=self._vote_meeting_id)

    async def cast(self, *args: object, **kwargs: object) -> None:
        self.cast_calls += 1


@pytest.mark.asyncio
async def test_cast_rejects_vote_from_other_meeting() -> None:
    other_meeting = uuid4()
    voting = _MeetingBoundVoting(other_meeting)
    conn = _conn(beamer=False)
    # conn.meeting_id ist eine eigene uuid4 ≠ other_meeting → Mismatch.
    conn.voting = voting  # type: ignore[assignment]
    await conn._handle_cast(
        {"type": "cast", "voteId": str(uuid4()), "choice": "yes"}
    )
    # Frame wird abgewiesen, ohne den DB-Cast/Lock zu erreichen.
    assert voting.cast_calls == 0
    assert conn.ws.sent == [{"type": "error", "code": "not_eligible"}]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_cast_allows_vote_from_own_meeting() -> None:
    conn = _conn(beamer=False)
    voting = _MeetingBoundVoting(conn.meeting_id)  # Vote gehört zur eigenen Sitzung
    conn.voting = voting  # type: ignore[assignment]

    published: list[object] = []

    async def _stub_tally(vote: object) -> None:
        published.append(vote)

    conn.publisher.vote_tally = _stub_tally  # type: ignore[method-assign]
    await conn._handle_cast(
        {"type": "cast", "voteId": str(uuid4()), "choice": "yes"}
    )
    # Meeting-Bindung ok → cast wird genau einmal aufgerufen, kein Fehler-Frame.
    assert voting.cast_calls == 1
    assert published  # Tally wurde broadcastet
    assert all(s.get("code") != "not_eligible" for s in conn.ws.sent)  # type: ignore[attr-defined]
