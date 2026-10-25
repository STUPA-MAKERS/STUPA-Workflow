"""The live body draft (`body_draft`) of the protokollant on the voter channel.

The protokollant of a live meeting sends the text of the open agenda item while
typing. The connection checks the sender (the current protokollant, read on every
frame), the agenda item, the size and its own rate cap, then publishes the frame on
the meeting channel. The beamer and the guest channel never pass a draft on.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.modules.auth.principal import Principal
from app.modules.livevote.broker import InMemoryBroker
from app.modules.livevote.connection import _DRAFT_MAX_PER_SECOND, LiveVoteConnection
from app.modules.livevote.guest_connection import GuestConnection
from app.modules.livevote.locks import InMemoryLocker
from app.modules.livevote.schemas import AGENDA_BODY_MAX
from app.modules.livevote.service import meeting_channel


class _FakeWS:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send_json(self, data: dict[str, object]) -> None:
        self.sent.append(data)


class _Session:
    """Session double: ``scalar`` answers from a queue and records each statement."""

    def __init__(self, *answers: int) -> None:
        self.answers = list(answers)
        self.statements: list[str] = []
        self.in_tx = False
        self.rollbacks = 0

    async def scalar(self, stmt: object) -> int:
        self.in_tx = True
        self.statements.append(str(stmt))
        return self.answers.pop(0)

    async def rollback(self) -> None:
        self.in_tx = False
        self.rollbacks += 1


class _Broker:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, object]]] = []

    async def publish(self, channel: str, message: dict[str, object]) -> None:
        self.published.append((channel, message))


def _conn(
    *answers: int, beamer: bool = False, principal: Principal | None = None
) -> tuple[LiveVoteConnection, _Session, _Broker]:
    session = _Session(*answers)
    broker = _Broker()
    conn = LiveVoteConnection(
        _FakeWS(),  # type: ignore[arg-type]
        uuid4(),
        beamer=beamer,
        principal=principal or Principal(sub="keeper"),
        meetings=object(),  # type: ignore[arg-type]
        voting=SimpleNamespace(session=session),  # type: ignore[arg-type]
        broker=broker,  # type: ignore[arg-type]
        locker=InMemoryLocker(),
    )
    return conn, session, broker


def _frame(**overrides: object) -> dict[str, object]:
    frame: dict[str, object] = {
        "type": "body_draft",
        "agendaItemId": str(uuid4()),
        "body": "Die Sitzung beginnt.",
        "seq": 3,
    }
    frame.update(overrides)
    return frame


def _sent(conn: LiveVoteConnection) -> list[dict[str, object]]:
    return conn.ws.sent  # type: ignore[attr-defined, no-any-return]


@pytest.mark.asyncio
async def test_draft_of_the_protokollant_is_published() -> None:
    conn, session, broker = _conn(1, 1)
    frame = _frame()
    await conn._handle_body_draft(frame)
    assert _sent(conn) == []
    assert broker.published == [
        (
            meeting_channel(conn.meeting_id),
            {
                "type": "body_draft",
                "agendaItemId": frame["agendaItemId"],
                "body": "Die Sitzung beginnt.",
                "seq": 3,
            },
        )
    ]
    # The check reads the current protokollant of the live meeting, with an active
    # account, and then the agenda item of this meeting. The cycle ends its read.
    keeper, item = session.statements
    assert "meeting.status" in keeper and "meeting.protokollant_id" in keeper
    assert "principal.sub" in keeper and "principal.merged_into IS NULL" in keeper
    assert "meeting_agenda_item.meeting_id" in item
    assert session.in_tx is False
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_draft_of_another_member_gets_not_protokollant() -> None:
    # Also the old protokollant after a handover: the row names the new keeper now.
    conn, session, broker = _conn(0)
    await conn._handle_body_draft(_frame())
    assert _sent(conn) == [{"type": "error", "code": "not_protokollant"}]
    assert broker.published == []
    assert len(session.statements) == 1
    assert session.in_tx is False


@pytest.mark.asyncio
async def test_handover_takes_effect_on_the_next_frame() -> None:
    # The first frame finds the sender as keeper, the second after the handover not.
    conn, _session, broker = _conn(1, 1, 0)
    await conn._handle_body_draft(_frame(seq=1))
    await conn._handle_body_draft(_frame(seq=2))
    assert len(broker.published) == 1
    assert _sent(conn) == [{"type": "error", "code": "not_protokollant"}]


@pytest.mark.asyncio
async def test_scoped_token_without_protocol_write_gets_not_protokollant() -> None:
    principal = Principal(sub="keeper", scope_permissions=frozenset({"meeting.view_all"}))
    conn, session, broker = _conn(principal=principal)
    await conn._handle_body_draft(_frame())
    assert _sent(conn) == [{"type": "error", "code": "not_protokollant"}]
    # The scope cap refuses before any read.
    assert session.statements == []
    assert broker.published == []


@pytest.mark.asyncio
async def test_draft_for_an_item_of_another_meeting_is_refused() -> None:
    conn, session, broker = _conn(1, 0)
    await conn._handle_body_draft(_frame())
    assert _sent(conn) == [{"type": "error", "code": "unknown_agenda_item"}]
    assert broker.published == []
    assert session.in_tx is False


@pytest.mark.asyncio
async def test_draft_over_the_size_limit_gets_too_large() -> None:
    conn, session, broker = _conn()
    await conn._handle_body_draft(_frame(body="x" * (AGENDA_BODY_MAX + 1)))
    assert _sent(conn) == [{"type": "error", "code": "too_large"}]
    assert session.statements == []
    assert broker.published == []


@pytest.mark.asyncio
async def test_draft_size_counts_utf8_bytes_not_characters() -> None:
    """A multi-byte text under the limit in characters but over it in bytes is refused."""
    body = "€" * (AGENDA_BODY_MAX // 3 + 1)  # 3 bytes each
    assert len(body) <= AGENDA_BODY_MAX
    conn, session, broker = _conn()
    await conn._handle_body_draft(_frame(body=body))
    assert _sent(conn) == [{"type": "error", "code": "too_large"}]
    assert session.statements == []
    assert broker.published == []


@pytest.mark.asyncio
async def test_draft_of_multibyte_text_at_the_byte_limit_passes() -> None:
    conn, _session, broker = _conn(1, 1)
    await conn._handle_body_draft(_frame(body="ä" * (AGENDA_BODY_MAX // 2)))
    assert len(broker.published) == 1


@pytest.mark.asyncio
async def test_draft_at_the_size_limit_passes() -> None:
    conn, _session, broker = _conn(1, 1)
    await conn._handle_body_draft(_frame(body="x" * AGENDA_BODY_MAX))
    assert len(broker.published) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"agendaItemId": "not-a-uuid"},
        {"body": None},
        {"seq": -1},
        {"seq": "eins"},
    ],
)
async def test_malformed_draft_gets_invalid_message(overrides: dict[str, object]) -> None:
    conn, session, broker = _conn()
    await conn._handle_body_draft(_frame(**overrides))
    assert _sent(conn) == [{"type": "error", "code": "invalid_message"}]
    assert session.statements == []
    assert broker.published == []


@pytest.mark.asyncio
async def test_beamer_draft_gets_read_only() -> None:
    conn, session, broker = _conn(beamer=True)
    await conn._handle_body_draft(_frame())
    assert _sent(conn) == [{"type": "error", "code": "read_only"}]
    assert session.statements == []
    assert broker.published == []


@pytest.mark.asyncio
async def test_drafts_over_the_cap_are_dropped_without_an_answer() -> None:
    answers = [1] * (2 * _DRAFT_MAX_PER_SECOND)
    conn, _session, broker = _conn(*answers)
    conn._draft_window = time.monotonic()
    for seq in range(_DRAFT_MAX_PER_SECOND + 5):
        await conn._handle_body_draft(_frame(seq=seq))
    assert len(broker.published) == _DRAFT_MAX_PER_SECOND
    assert _sent(conn) == []


def test_draft_cap_opens_a_new_window_after_one_second() -> None:
    conn, _session, _broker = _conn()
    conn._draft_window = time.monotonic()
    conn._draft_count = _DRAFT_MAX_PER_SECOND
    assert conn._allow_draft() is False
    conn._draft_window = time.monotonic() - 1.5
    assert conn._allow_draft() is True
    assert conn._draft_count == 1


@pytest.mark.asyncio
async def test_receive_routes_drafts_past_the_general_throttle() -> None:
    conn, _session, _broker = _conn()
    # The general bucket is empty: a cast or subscribe would get `rate_limited`.
    conn._tokens = 0.0
    conn._last_refill = time.monotonic()
    frames: list[object] = [_frame(), {"type": "subscribe"}]
    handled: list[dict[str, object]] = []

    class _Stop(Exception):
        pass

    async def _receive_json() -> object:
        if frames:
            return frames.pop(0)
        raise _Stop

    async def _draft(raw: dict[str, object]) -> None:
        handled.append(raw)

    conn.ws.receive_json = _receive_json  # type: ignore[attr-defined]
    conn._handle_body_draft = _draft
    with pytest.raises(_Stop):
        await conn._receive()
    assert [h["type"] for h in handled] == ["body_draft"]
    assert _sent(conn) == [{"type": "error", "code": "rate_limited"}]


class _Sub:
    def __init__(self, items: list[dict[str, object]]) -> None:
        self._items = items

    async def __aiter__(self) -> AsyncIterator[dict[str, object]]:
        for item in self._items:
            yield item


_DRAFT_EVENT: dict[str, object] = {
    "type": "body_draft",
    "agendaItemId": str(uuid4()),
    "body": "Text",
    "seq": 1,
}


@pytest.mark.asyncio
async def test_voter_pump_passes_the_draft_and_the_beamer_drops_it() -> None:
    voter, _s, _b = _conn()
    await voter._pump(_Sub([_DRAFT_EVENT]))
    assert _sent(voter) == [_DRAFT_EVENT]
    beamer, _s, _b = _conn(beamer=True)
    await beamer._pump(_Sub([_DRAFT_EVENT]))
    assert _sent(beamer) == []


@pytest.mark.asyncio
async def test_guest_connection_never_gets_a_draft() -> None:
    sent: list[dict[str, Any]] = []

    class _Ws:
        async def send_json(self, data: dict[str, Any]) -> None:
            sent.append(data)

    guest = SimpleNamespace(id=uuid4(), seq=1, display_name="Gast", status="admitted")
    conn = GuestConnection(
        _Ws(),  # type: ignore[arg-type]
        session=object(),  # type: ignore[arg-type]
        broker=InMemoryBroker(),
        meeting_id=uuid4(),
        guest=guest,  # type: ignore[arg-type]
    )
    await conn.handle(dict(_DRAFT_EVENT))
    assert sent == []
