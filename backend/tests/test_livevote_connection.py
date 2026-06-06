"""LiveVoteConnection-Interna (T-16): Beamer-Fan-out-Filter (requirements N1a).

Der Beamer-Stream ist read-only und darf **nur** ``meeting_state|vote_opened|
vote_tally|vote_closed`` durchlassen — alles andere (z. B. interne Events) wird im
Fan-out verworfen. Der Voter-Kanal reicht alles durch.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from app.modules.auth.principal import Principal
from app.modules.livevote.broker import InMemoryBroker
from app.modules.livevote.connection import LiveVoteConnection
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


_STREAM = [
    {"type": "meeting_state", "status": "live"},
    {"type": "vote_opened", "voteId": "v"},
    {"type": "internal_secret", "voter": "alice"},
    {"type": "vote_tally", "counts": {"yes": 1}},
]


@pytest.mark.asyncio
async def test_beamer_pump_drops_non_whitelisted_events() -> None:
    conn = _conn(beamer=True)
    await conn._pump(_Sub(_STREAM))
    types_sent = [m["type"] for m in conn.ws.sent]  # type: ignore[attr-defined]
    assert types_sent == ["meeting_state", "vote_opened", "vote_tally"]
    # Niemals interne/identitätsbehaftete Events auf den Beamer (requirements N1a).
    assert all("voter" not in m for m in conn.ws.sent)  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_voter_pump_passes_everything_through() -> None:
    conn = _conn(beamer=False)
    await conn._pump(_Sub(_STREAM))
    types_sent = [m["type"] for m in conn.ws.sent]  # type: ignore[attr-defined]
    assert types_sent == [m["type"] for m in _STREAM]
