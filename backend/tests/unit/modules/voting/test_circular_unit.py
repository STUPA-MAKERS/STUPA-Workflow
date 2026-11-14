"""The Umlaufverfahren without a database: the pure rules, the body and the routes.

The integration suite (``test_circular_vote.py``) covers the create, the close and the
objection against Postgres.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from app.deps import get_current_applicant, get_current_principal
from app.main import create_app
from app.modules.auth.principal import Principal
from app.modules.voting import circular as circular_mod
from app.modules.voting import router as voting_router
from app.modules.voting.circular import CircularService, check_manual_close, circular_config
from app.modules.voting.schemas import (
    CircularCreate,
    GremiumVoteCreate,
    PollCreate,
    TallyOut,
    VoteOut,
)
from app.shared.errors import ConflictError

GID = UUID("00000000-0000-0000-0000-00000000c1c1")
NOW = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


def _row(**over: Any) -> Any:
    base: dict[str, Any] = {"kind": "circular", "closes_at": NOW + timedelta(days=3)}
    base.update(over)
    return SimpleNamespace(**base)


def test_kind_helpers() -> None:
    assert circular_mod.is_circular(_row()) is True
    assert circular_mod.is_circular(_row(kind="motion")) is False
    assert circular_mod.is_circular(SimpleNamespace()) is False
    assert circular_mod.circular_fields(_row()) == {"kind": "circular"}
    assert circular_mod.circular_fields(_row(kind="poll")) == {}


def test_config_is_fixed() -> None:
    config = circular_config()
    assert config.options == ["yes", "no", "abstain"]
    assert config.majority_rule == "members_majority"
    assert config.secret is True
    assert config.guests_vote is False
    assert config.quorum is None


def test_manual_close_waits_for_the_end() -> None:
    check_manual_close(_row(kind="motion"), None, NOW)
    check_manual_close(_row(), NOW, NOW)
    check_manual_close(_row(closes_at=NOW), None, NOW)
    for row in (_row(), _row(closes_at=None)):
        with pytest.raises(ConflictError) as err:
            check_manual_close(row, None, NOW)
        assert err.value.code == "circular_window_open"


def _settings(stored: int | None) -> Any:
    """Stand in for the read of the one settings row: it answers ``stored``."""

    async def scalar(_query: object) -> int | None:
        return stored

    return SimpleNamespace(scalar=scalar)


@pytest.mark.parametrize(("stored", "days"), [(None, 3), (7, 7)])
async def test_min_days_reads_the_meeting_settings(stored: int | None, days: int) -> None:
    voting: Any = SimpleNamespace(session=_settings(stored))
    assert await CircularService(voting).min_days() == days


async def test_check_open_skips_another_kind() -> None:
    voting: Any = SimpleNamespace(session=_settings(None))
    await CircularService(voting).check_open(_row(kind="poll", closes_at=None), NOW)


def _body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": "circular",
        "eligibleGroup": str(GID),
        "question": "Soll der AStA einen Lastenanhänger beschaffen?",
        "closesAt": "2026-12-01T12:00:00+01:00",
    }
    body.update(over)
    return body


_POLL_BODY: dict[str, Any] = {
    "eligibleGroup": str(GID),
    "question": "Wohin?",
    "mode": "single",
    "options": [{"label": "A"}, {"label": "B"}],
    "closesAt": "2026-12-01T12:00:00+01:00",
}


def test_create_body_is_told_apart_by_kind() -> None:
    adapter: TypeAdapter[Any] = TypeAdapter(GremiumVoteCreate)
    assert isinstance(adapter.validate_python(_body()), CircularCreate)
    assert isinstance(adapter.validate_python(_POLL_BODY), PollCreate)
    assert isinstance(adapter.validate_python({**_POLL_BODY, "kind": "poll"}), PollCreate)
    built = CircularCreate.model_validate(_body())
    assert adapter.validate_python(built) is built
    with pytest.raises(ValidationError):
        adapter.validate_python({**_POLL_BODY, "kind": "motion"})
    with pytest.raises(ValidationError):
        adapter.validate_python(_body(question="   "))
    with pytest.raises(ValidationError):
        adapter.validate_python(_body(mode="single"))


def _out(status: str = "open", **over: Any) -> VoteOut:
    data: dict[str, Any] = {
        "id": uuid4(),
        "eligibleGroup": str(GID),
        "config": circular_config(),
        "status": status,
        "secret": True,
        "tally": TallyOut(counts={}, eligible=3, quorumMet=True),
        "kind": "circular",
    }
    data.update(over)
    return VoteOut.model_validate(data)


class _Circulars:
    calls: list[tuple[str, Any]] = []

    def __init__(self, voting: object) -> None:
        self.voting = voting

    async def create(self, payload: CircularCreate, principal: Principal, *, now: Any) -> VoteOut:
        _Circulars.calls.append(("create", payload.draft))
        return _out("draft" if payload.draft else "open")

    async def object(self, vote_id: UUID, principal: Principal, *, now: Any) -> VoteOut:
        _Circulars.calls.append(("object", principal.sub))
        return _out("cancelled", id=vote_id, cancelReason="objection")

    async def min_days(self) -> int:
        return 5


class _Pub:
    def __init__(self) -> None:
        self.cancelled: list[UUID] = []

    async def vote_cancelled(self, vote: VoteOut) -> None:
        self.cancelled.append(vote.id)


@pytest.fixture
def routes(monkeypatch: pytest.MonkeyPatch) -> tuple[FastAPI, _Pub]:
    from app.modules.meetings.publisher import get_meeting_publisher

    _Circulars.calls = []
    monkeypatch.setattr(voting_router, "CircularService", _Circulars)
    app = create_app()
    pub = _Pub()

    async def commit() -> None:
        _Circulars.calls.append(("commit", None))

    voting = SimpleNamespace(session=SimpleNamespace(commit=commit))
    app.dependency_overrides[voting_router.get_voting_service] = lambda: voting
    app.dependency_overrides[get_meeting_publisher] = lambda: pub
    app.dependency_overrides[get_current_applicant] = lambda: None
    app.dependency_overrides[get_current_principal] = lambda: Principal(sub="p")
    return app, pub


def test_create_route_takes_a_circular_vote(routes: tuple[FastAPI, _Pub]) -> None:
    app, _pub = routes
    resp = TestClient(app).post("/api/votes", json=_body(draft=True))
    assert resp.status_code == 200, resp.text
    assert resp.json()["kind"] == "circular"
    assert resp.json()["status"] == "draft"
    assert _Circulars.calls == [("create", True)]


def test_objection_route_cancels_and_tells_the_channel(routes: tuple[FastAPI, _Pub]) -> None:
    app, pub = routes
    vote_id = uuid4()
    resp = TestClient(app).post(f"/api/votes/{vote_id}/objection")
    assert resp.status_code == 200, resp.text
    assert resp.json()["cancelReason"] == "objection"
    assert _Circulars.calls == [("object", "p"), ("commit", None)]
    assert pub.cancelled == [vote_id]


def test_rules_route_gives_the_min_days(routes: tuple[FastAPI, _Pub]) -> None:
    app, _pub = routes
    resp = TestClient(app).get("/api/votes/circular-rules")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"minDays": 5}


def test_routes_need_a_session(routes: tuple[FastAPI, _Pub]) -> None:
    app, _pub = routes
    del app.dependency_overrides[get_current_principal]
    client = TestClient(app)
    assert client.get("/api/votes/circular-rules").status_code == 401
    assert client.post(f"/api/votes/{uuid4()}/objection").status_code == 401
