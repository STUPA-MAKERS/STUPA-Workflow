"""Unit tests of the public decisions (spec 000926, no database).

They cover the list over a fake session: the fields of a motion and of an election,
the decisions that stay out (internal TOP; the visibility of a protocol is the
rule of `visible_rows`, tested with the protocol list), the search, the page cut, and the route
without a session.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from datetime import date as _date
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.protocol.public import (
    PublicDecision,
    PublicFilter,
    PublicSnapshot,
    PublicTop,
)
from app.modules.protocol.public_decisions import last_results, list_public_decisions
from app.modules.protocol.public_router import get_public_protocol_service
from app.settings import get_settings
from app.shared import antiabuse
from app.shared.ratelimit import InMemoryRateLimiter

PID = uuid.uuid4()
GID = uuid.uuid4()


def _snapshot() -> PublicSnapshot:
    return PublicSnapshot(
        tops=[
            PublicTop(
                number=1,
                title="Sommerfest",
                decisions=[
                    PublicDecision(
                        question="Zuschuss Sommerfest", counts={"ja": 5, "nein": 1}, result="passed"
                    ),
                    PublicDecision(
                        question="Wahl Vorsitz",
                        kind="election",
                        result="elected",
                        elected=["Erika Musterfrau"],
                        otherCandidates=1,
                    ),
                ],
            ),
            PublicTop(
                number=2,
                title="Personal",
                nonPublic=True,
                decisions=[PublicDecision(question="Intern", result="passed")],
            ),
        ],
    )


def _row() -> tuple[Any, Any, Any]:
    protocol = SimpleNamespace(
        id=PID, public_content=_snapshot().model_dump(mode="json", by_alias=True)
    )
    meeting = SimpleNamespace(
        title="6. Sitzung", date=_date(2026, 11, 3), created_at=datetime(2026, 10, 1, tzinfo=UTC)
    )
    gremium = SimpleNamespace(id=GID, name="StuPa", slug="stupa")
    return protocol, meeting, gremium


class _Rows:
    """Stand-in for `PublicProtocolService`: answers `visible_rows` and keeps the filter."""

    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows
        self.filters: list[PublicFilter] = []

    async def visible_rows(self, flt: PublicFilter) -> list[Any]:
        self.filters.append(flt)
        return list(self.rows)


def _service(rows: list[Any]) -> Any:
    return _Rows(rows)


async def test_list_holds_the_public_decisions_only() -> None:
    svc = _service([_row()])
    page = await list_public_decisions(svc, PublicFilter(), limit=20, offset=0)
    assert page.total == 2
    motion, election = page.items
    assert motion.question == "Zuschuss Sommerfest"
    assert motion.date == _date(2026, 11, 3)
    assert motion.semester == "ws-2026"
    assert motion.meeting_title == "6. Sitzung"
    assert motion.result == "passed"
    assert motion.counts == {"ja": 5, "nein": 1}
    assert motion.protocol_id == PID
    assert election.kind == "election"
    assert election.question == "Wahl Vorsitz"
    assert election.date == _date(2026, 11, 3)
    assert election.meeting_title is None
    assert election.result is None
    assert election.counts == {}
    dumped = page.model_dump_json(by_alias=True)
    assert "Musterfrau" not in dumped
    assert "Intern" not in dumped


async def test_list_holds_the_circular_votes_of_a_public_protocol() -> None:
    """§F/meetings/protocols/000934: a circular decision is public with its protocol."""
    snapshot = _snapshot()
    snapshot.circular = [
        PublicDecision(
            kind="circular",
            question="Lastenanhänger beschaffen",
            counts={"yes": 5, "no": 1},
            result="passed",
            closedOn=_date(2026, 10, 20),
        ),
        PublicDecision(kind="circular", question="Ohne Tag", result="rejected"),
    ]
    protocol, meeting, gremium = _row()
    protocol.public_content = snapshot.model_dump(mode="json", by_alias=True)
    page = await list_public_decisions(
        _service([(protocol, meeting, gremium)]), PublicFilter(), limit=20, offset=0
    )
    assert page.total == 4
    first, undated = page.items[:2]
    assert first.kind == "circular"
    assert first.question == "Lastenanhänger beschaffen"
    assert first.date == _date(2026, 10, 20)
    assert first.meeting_title is None
    assert first.result == "passed"
    assert first.counts == {"yes": 5, "no": 1}
    assert undated.date == _date(2026, 11, 3)
    assert "Lastenanhänger" in snapshot.search_text()


async def test_list_searches_the_question_and_cuts_the_page() -> None:
    svc = _service([_row(), _row()])
    hits = await list_public_decisions(svc, PublicFilter(q="SOMMERFEST"), limit=20, offset=0)
    assert [d.question for d in hits.items] == ["Zuschuss Sommerfest"] * 2
    page = await list_public_decisions(svc, PublicFilter(), limit=1, offset=3)
    assert page.total == 4
    assert [d.question for d in page.items] == ["Wahl Vorsitz"]
    assert (page.limit, page.offset) == (1, 3)


def test_a_repeated_vote_shows_its_last_result_only() -> None:
    """§F/public/public-pages/000945: one question on one TOP gives one row."""
    first = PublicDecision(question="Zuschuss", counts={"ja": 2, "nein": 3}, result="rejected")
    again = PublicDecision(question="Zuschuss", counts={"ja": 4, "nein": 1}, result="passed")
    other = PublicDecision(question="Vertagung", counts={"ja": 5}, result="passed")
    round_one = PublicDecision(question="Wahl Vorsitz", kind="election", round=1)
    round_two = PublicDecision(question="Wahl Vorsitz", kind="election", round=2)
    unnamed = PublicDecision(counts={"ja": 1}, result="passed")
    kept = last_results([first, round_one, other, again, unnamed, round_two, unnamed])
    assert kept == [other, again, unnamed, round_two, unnamed]


async def test_list_without_a_public_protocol_is_empty() -> None:
    svc = _service([])
    page = await list_public_decisions(svc, PublicFilter(), limit=20, offset=0)
    assert page.items == [] and page.total == 0


@pytest.fixture
def client() -> Iterator[TestClient]:
    app: FastAPI = create_app(get_settings())
    app.dependency_overrides[get_public_protocol_service] = lambda: _service([_row()])
    app.dependency_overrides[antiabuse.get_rate_limiter] = InMemoryRateLimiter
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_route_needs_no_session(client: TestClient) -> None:
    res = client.get("/api/public/decisions", params={"gremium": [str(GID)], "q": " wahl "})
    assert res.status_code == 200
    assert res.headers["X-Robots-Tag"] == "noindex"
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0] == {
        "protocolId": str(PID),
        "gremium": {"id": str(GID), "name": "StuPa", "slug": "stupa"},
        "date": "2026-11-03",
        "semester": "ws-2026",
        "kind": "election",
        "question": "Wahl Vorsitz",
        "meetingTitle": None,
        "result": None,
        "counts": {},
    }
    assert client.get("/api/public/decisions", params={"semester": "x"}).status_code == 422
    assert client.get("/api/public/decisions", params={"limit": 51}).status_code == 422
    assert client.get("/api/public/decisions?q=%00").status_code == 422
