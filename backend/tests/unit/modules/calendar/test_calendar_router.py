"""Unit-Tests der Kalender-Endpunkte (#ics) — TestClient + dependency_overrides."""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db import get_session
from app.deps import Principal, get_current_principal
from app.main import create_app
from app.settings import get_settings, load_settings
from tests._support.auth_fakes import fake_session, result

SETTINGS = load_settings(
    database_url="postgresql+asyncpg://x/y",
    session_secret="session-secret-0123",
    magic_link_secret="magic-link-secret-0",
    public_base_url="https://stupa.example",
    cookie_secure=False,
)


def _client(db: object, principal: Principal | None = None) -> TestClient:
    app = create_app(SETTINGS)

    async def _fake_db() -> AsyncIterator[object]:
        yield db

    app.dependency_overrides[get_settings] = lambda: SETTINGS
    app.dependency_overrides[get_session] = _fake_db
    if principal is not None:
        app.dependency_overrides[get_current_principal] = lambda: principal
    return TestClient(app, follow_redirects=False)


def test_me_without_token_returns_null_url() -> None:
    db = fake_session(result(SimpleNamespace(calendar_token=None)))
    resp = _client(db, Principal(sub="u1")).get("/api/calendar/me")
    assert resp.status_code == 200
    assert resp.json() == {"url": None}


def test_me_with_token_returns_feed_url() -> None:
    db = fake_session(result(SimpleNamespace(calendar_token="TOK123")))
    resp = _client(db, Principal(sub="u1")).get("/api/calendar/me")
    assert resp.json() == {"url": "https://stupa.example/api/calendar/TOK123.ics"}


def test_me_requires_authentication() -> None:
    # Kein Principal-Override → realer Resolver, kein Cookie → 401 (kein DB-Zugriff).
    resp = _client(fake_session()).get("/api/calendar/me")
    assert resp.status_code == 401


def test_rotate_generates_feed_url() -> None:
    row = SimpleNamespace(calendar_token=None)
    client = _client(fake_session(result(row)), Principal(sub="u1"))
    resp = client.post("/api/calendar/me/rotate")
    assert resp.status_code == 200
    url = resp.json()["url"]
    assert re.fullmatch(r"https://stupa\.example/api/calendar/[\w-]+\.ics", url)
    assert row.calendar_token is not None  # Token wurde rotiert


def test_feed_unknown_token_is_404() -> None:
    resp = _client(fake_session(result())).get("/api/calendar/nope.ics")
    assert resp.status_code == 404


def test_feed_returns_ics_with_meeting() -> None:
    principal_row = SimpleNamespace(sub="u1")
    gid = uuid.uuid4()
    meeting = SimpleNamespace(
        id=uuid.uuid4(),
        title="Vollversammlung",
        date=date(2026, 7, 1),
        start_time=time(18, 0),
        end_time=time(20, 0),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    db = fake_session(
        result(principal_row),
        result((gid, object())),
        result((meeting, "StuPa")),
    )
    resp = _client(db).get("/api/calendar/abctoken.ics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/calendar")
    assert 'filename="stupa-sitzungen.ics"' in resp.headers["content-disposition"]
    body = resp.text
    assert "BEGIN:VCALENDAR" in body
    assert "SUMMARY:Vollversammlung" in body
    assert "DTSTART:20260701T160000Z" in body  # 18:00 CEST → 16:00Z
    assert "DTEND:20260701T180000Z" in body  # 20:00 CEST → 18:00Z
