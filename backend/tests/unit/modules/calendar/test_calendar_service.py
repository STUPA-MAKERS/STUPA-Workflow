"""Unit-Tests des Kalender-Service (#ics) — DB-Branches über FakeSession (kein Docker)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time
from types import SimpleNamespace

import pytest

from app.modules.calendar import service
from tests._support.auth_fakes import fake_session, result


def test_generate_token_is_url_safe() -> None:
    tok = service.generate_calendar_token()
    assert tok
    assert "." not in tok and "/" not in tok


async def test_get_calendar_token_present() -> None:
    row = SimpleNamespace(calendar_token="TOK")
    db = fake_session(result(row))
    assert await service.get_calendar_token(db, "u1") == "TOK"


async def test_get_calendar_token_no_principal() -> None:
    assert await service.get_calendar_token(fake_session(result()), "u1") is None


async def test_rotate_sets_and_returns_token() -> None:
    row = SimpleNamespace(calendar_token=None)
    db = fake_session(result(row))
    tok = await service.rotate_calendar_token(db, "u1")
    assert tok and row.calendar_token == tok
    assert db.flushed == 1


async def test_rotate_missing_principal_returns_none() -> None:
    assert await service.rotate_calendar_token(fake_session(result()), "u1") is None


@pytest.mark.parametrize("token", ["", None])
async def test_principal_by_token_empty(token: str) -> None:
    # Leerer Token kurzschließt ohne Query.
    assert await service.principal_by_calendar_token(fake_session(), token) is None


async def test_principal_by_token_hit() -> None:
    row = SimpleNamespace(sub="u1")
    db = fake_session(result(row))
    assert await service.principal_by_calendar_token(db, "tok") is row


async def test_principal_by_token_miss() -> None:
    assert await service.principal_by_calendar_token(fake_session(result()), "tok") is None


async def test_member_meetings_no_gremien() -> None:
    # active_gremium_roles liefert nichts → keine Mitglieds-Gremien → leere Liste.
    assert await service.member_meetings(fake_session(result()), "u1") == []


async def test_member_meetings_returns_pairs() -> None:
    gid = uuid.uuid4()
    meeting = SimpleNamespace(
        id=uuid.uuid4(),
        title="GV",
        date=date(2026, 7, 1),
        start_time=time(18, 0),
        end_time=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    db = fake_session(result((gid, object())), result((meeting, "StuPa")))
    pairs = await service.member_meetings(db, "u1")
    assert pairs == [(meeting, "StuPa")]
