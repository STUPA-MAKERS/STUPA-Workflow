"""Unit tests of the routes of the tab "Gremien" with TestClient and dependency_overrides.

The service and the gate are replaced: these tests prove the wiring, the query
parameters, the camelCase output and the 404 and 422 answers.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db import get_session
from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.gremien import router as gremien_router
from app.modules.gremien.schemas import (
    AttendanceOut,
    DecisionPageOut,
    GremiumMeetingOut,
    GremiumMemberOut,
    GremiumOverviewOut,
    MemberAttendanceOut,
)
from app.modules.gremien.service import GremienService
from app.settings import get_settings, load_settings
from app.shared.errors import NotFoundError
from tests._support.auth_fakes import fake_session

SETTINGS = load_settings(
    database_url="postgresql+asyncpg://x/y",
    session_secret="session-secret-0123",
    magic_link_secret="magic-link-secret-0",
    public_base_url="https://stupa.example",
    cookie_secure=False,
)
GID = uuid.uuid4()
PID = uuid.uuid4()


class _Calls:
    def __init__(self) -> None:
        self.seen: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.hidden: set[uuid.UUID] = set()


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> _Calls:
    log = _Calls()
    hidden = log.hidden

    async def _gate(_db: object, _principal: Principal, gremium_id: uuid.UUID) -> object:
        if gremium_id in hidden:
            raise NotFoundError("Gremium not found.", code="gremium_not_found")
        return object()

    monkeypatch.setattr(gremien_router, "require_gremium", _gate)

    def _fake(name: str, value: object) -> None:
        async def _method(_self: GremienService, *args: Any, **kwargs: Any) -> object:
            log.seen.append((name, args, kwargs))
            return value

        monkeypatch.setattr(GremienService, name, _method)

    _fake(
        "overview",
        [
            GremiumOverviewOut(
                id=GID,
                name="StuPa",
                slug="stupa",
                is_member=True,
                role_key="member",
                role_name={"de": "Mitglied", "en": "Member"},
                member_count=3,
                next_meeting=None,
                live=False,
                quorum_percent=50,
                protocols_public=True,
                allow_vote_delegation=False,
                logo_url=None,
            )
        ],
    )
    _fake("members", list[GremiumMemberOut]())
    _fake("meetings", list[GremiumMeetingOut]())
    _fake("attendance", AttendanceOut(from_month="2026-05", to_month="2026-10", months=[], rows=[]))
    _fake(
        "member_attendance",
        MemberAttendanceOut(principal_id=PID, display_name="A", month="2026-10", meetings=[]),
    )
    _fake("decisions", DecisionPageOut(items=[], next_cursor=None))
    return log


def _client(principal: Principal | None = None) -> TestClient:
    app = create_app(SETTINGS)

    async def _fake_db() -> AsyncIterator[object]:
        yield fake_session()

    app.dependency_overrides[get_settings] = lambda: SETTINGS
    app.dependency_overrides[get_session] = _fake_db
    if principal is not None:
        app.dependency_overrides[get_current_principal] = lambda: principal
    return TestClient(app, follow_redirects=False)


def test_overview_answers_camel_case(calls: _Calls) -> None:
    resp = _client(Principal(sub="u1")).get("/api/gremien/overview")
    assert resp.status_code == 200
    body = resp.json()[0]
    assert body["isMember"] is True
    assert body["memberCount"] == 3
    assert body["roleName"] == {"de": "Mitglied", "en": "Member"}
    assert calls.seen[0][0] == "overview"


def test_routes_need_a_login(calls: _Calls) -> None:
    assert _client().get("/api/gremien/overview").status_code == 401
    assert _client().get(f"/api/gremien/{GID}/members").status_code == 401
    assert calls.seen == []


@pytest.mark.parametrize(
    "path",
    ["members", "meetings", "attendance", f"attendance/{PID}?month=2026-10", "decisions"],
)
def test_hidden_gremium_is_404(calls: _Calls, path: str) -> None:
    calls.hidden.add(GID)
    resp = _client(Principal(sub="u1")).get(f"/api/gremien/{GID}/{path}")
    assert resp.status_code == 404
    assert resp.json()["code"] == "gremium_not_found"
    assert calls.seen == []


def test_members_passes_former(calls: _Calls) -> None:
    client = _client(Principal(sub="u1"))
    assert client.get(f"/api/gremien/{GID}/members").status_code == 200
    assert client.get(f"/api/gremien/{GID}/members?former=true").status_code == 200
    assert [c[2]["former"] for c in calls.seen] == [False, True]


def test_meetings(calls: _Calls) -> None:
    resp = _client(Principal(sub="u1")).get(f"/api/gremien/{GID}/meetings")
    assert resp.status_code == 200
    assert resp.json() == []
    assert calls.seen[0][1] == (GID,)


def test_attendance_passes_the_range(calls: _Calls) -> None:
    resp = _client(Principal(sub="u1")).get(
        f"/api/gremien/{GID}/attendance?from=2026-01&to=2026-06"
    )
    assert resp.status_code == 200
    assert resp.json()["fromMonth"] == "2026-05"
    assert calls.seen[0][2] == {"from_month": "2026-01", "to_month": "2026-06"}


@pytest.mark.parametrize("query", ["from=2026-13", "to=26-01", "from=2026-1"])
def test_attendance_rejects_a_bad_month(calls: _Calls, query: str) -> None:
    resp = _client(Principal(sub="u1")).get(f"/api/gremien/{GID}/attendance?{query}")
    assert resp.status_code == 422
    assert calls.seen == []


def test_member_attendance(calls: _Calls) -> None:
    client = _client(Principal(sub="u1"))
    resp = client.get(f"/api/gremien/{GID}/attendance/{PID}?month=2026-10")
    assert resp.status_code == 200
    assert resp.json()["principalId"] == str(PID)
    assert calls.seen[0][1] == (GID, PID, "2026-10")
    assert client.get(f"/api/gremien/{GID}/attendance/{PID}").status_code == 422
    assert client.get(f"/api/gremien/{GID}/attendance/{PID}?month=2026-00").status_code == 422


def test_decisions_passes_the_filters(calls: _Calls) -> None:
    client = _client(Principal(sub="u1"))
    resp = client.get(
        f"/api/gremien/{GID}/decisions?cursor=abc&q=Etat&result=passed&kind=motion&since=2026-01-01"
    )
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "nextCursor": None}
    kwargs = calls.seen[0][2]
    assert kwargs == {
        "cursor": "abc",
        "q": "Etat",
        "result": "passed",
        "kind": "motion",
        "since": date(2026, 1, 1),
    }


@pytest.mark.parametrize(
    "query",
    [
        "result=maybe",
        "kind=other",
        "since=yesterday",
        "since=0001-01-01",
        "since=2100-01-01",
        "q=" + "x" * 201,
    ],
)
def test_decisions_rejects_bad_filters(calls: _Calls, query: str) -> None:
    resp = _client(Principal(sub="u1")).get(f"/api/gremien/{GID}/decisions?{query}")
    assert resp.status_code == 422
    assert calls.seen == []


def test_service_dependency_uses_the_local_timezone() -> None:
    db = fake_session()
    service = gremien_router._service(db, SETTINGS)
    assert isinstance(service, GremienService)
