"""Unit: the pure rules, the number and the body checks of an Event (003022-003028)."""

from __future__ import annotations

from datetime import date, time
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.events.models import Event, format_event_number
from app.modules.events.rules import dates_problem, segment_of, shop_valid
from app.modules.events.schemas import EventCreate, EventUpdate

TODAY = date(2026, 11, 25)


def test_a_new_event_gets_a_number_with_v() -> None:
    """003022: the number is V- and eight random characters, like a Bestellung."""
    number = Event.__table__.c.number.default.arg(None)  # type: ignore[union-attr]
    assert len(number) == 8
    assert format_event_number(number) == f"V-{number}"


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://shop.example.org/t", True),
        ("http://x.org", True),
        ("ftp://x.org", False),
        ("javascript:alert(1)", False),
    ],
)
def test_the_shop_is_an_http_address(url: str, ok: bool) -> None:
    assert shop_valid(url) is ok


@pytest.mark.parametrize(
    ("phase", "starts", "ends", "segment"),
    [
        ("done", None, None, "done"),
        ("void", date(2027, 1, 1), None, "void"),
        ("open", None, None, "upcoming"),
        ("open", TODAY, None, "upcoming"),
        ("open", date(2026, 11, 20), TODAY, "upcoming"),
        ("open", date(2026, 11, 20), date(2026, 11, 24), "past"),
        ("open", date(2026, 11, 24), None, "past"),
    ],
)
def test_the_segment_follows_the_phase_and_the_last_day(
    phase: str, starts: date | None, ends: date | None, segment: str
) -> None:
    """003028: open Events split at today by their end, else their start."""
    assert segment_of(phase, starts, ends, TODAY) == segment


@pytest.mark.parametrize(
    ("args", "problem"),
    [
        ((TODAY, None, TODAY, None), None),
        ((TODAY, time(18), TODAY, time(23)), None),
        ((TODAY, time(22), date(2026, 11, 26), time(2)), None),
        ((None, None, TODAY, None), ("event_dates_invalid", "endsOn")),
        ((TODAY, None, date(2026, 11, 24), None), ("event_dates_invalid", "endsOn")),
        ((None, time(18), None, None), ("event_time_without_date", "startTime")),
        ((TODAY, None, None, time(18)), ("event_time_without_date", "endTime")),
        ((TODAY, time(18), TODAY, time(17)), ("event_dates_invalid", "endTime")),
    ],
)
def test_the_dates_must_fit(
    args: tuple[date | None, time | None, date | None, time | None],
    problem: tuple[str, str] | None,
) -> None:
    """000736: the end is not before the start, and a time needs its day."""
    assert dates_problem(*args) == problem


def test_the_body_checks_the_dates_and_the_lengths() -> None:
    team = str(uuid4())
    body = EventCreate.model_validate(
        {"teamId": team, "title": "Erstiparty", "startsOn": "2026-11-20", "endsOn": "2026-11-21"}
    )
    assert body.ends_on == date(2026, 11, 21)
    with pytest.raises(ValidationError, match="event_dates_invalid"):
        EventCreate.model_validate(
            {"teamId": team, "title": "X", "startsOn": "2026-11-21", "endsOn": "2026-11-20"}
        )
    with pytest.raises(ValidationError):
        EventCreate.model_validate({"teamId": team, "title": "x" * 301})
    with pytest.raises(ValidationError):
        EventCreate.model_validate({"teamId": team, "title": "X", "boardId": team})
    patch = EventUpdate.model_validate({"version": 2, "place": "Mensa"})
    assert patch.model_dump(exclude_unset=True) == {"version": 2, "place": "Mensa"}
