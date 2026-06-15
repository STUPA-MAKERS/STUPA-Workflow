"""Unit-Tests des iCal-Builders (#ics) — reine Funktion, keine DB."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from app.modules.calendar.ics import MeetingEvent, build_calendar

DOMAIN = "stupa.example.org"
STAMP = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _ev(**kw: object) -> MeetingEvent:
    base: dict[str, object] = {
        "uid": "m1",
        "title": "Sitzung",
        "date": date(2026, 7, 15),
        "start_time": time(18, 0),
        "end_time": None,
        "stamp": STAMP,
        "gremium_name": "StuPa",
    }
    base.update(kw)
    return MeetingEvent(**base)  # type: ignore[arg-type]


def _ics(events: list[MeetingEvent], **kw: object) -> str:
    return build_calendar(events, domain=DOMAIN, **kw).decode("utf-8")  # type: ignore[arg-type]


def test_calendar_wrapper_and_headers() -> None:
    out = _ics([_ev()], calendar_name="Test Cal")
    assert "BEGIN:VCALENDAR" in out
    assert "END:VCALENDAR" in out
    assert "VERSION:2.0" in out
    assert "PRODID:-//STUPA-Workflow//iCal Feed//DE" in out
    assert "X-WR-CALNAME:Test Cal" in out


def test_crlf_line_endings() -> None:
    assert b"\r\n" in build_calendar([_ev()], domain=DOMAIN)


def test_timed_event_utc_summer() -> None:
    # 18:00 Europe/Berlin am 2026-07-15 = CEST (+02:00) → 16:00Z, Default +1 h → 17:00Z.
    out = _ics([_ev(date=date(2026, 7, 15), start_time=time(18, 0))])
    assert "DTSTART:20260715T160000Z" in out
    assert "DTEND:20260715T170000Z" in out


def test_timed_event_utc_winter() -> None:
    # 18:00 am 2026-01-15 = CET (+01:00) → 17:00Z (DST-Wechsel korrekt).
    out = _ics([_ev(date=date(2026, 1, 15), start_time=time(18, 0))])
    assert "DTSTART:20260115T170000Z" in out
    assert "DTEND:20260115T180000Z" in out


def test_explicit_end_time() -> None:
    out = _ics([_ev(start_time=time(18, 0), end_time=time(20, 30))])
    assert "DTSTART:20260715T160000Z" in out
    assert "DTEND:20260715T183000Z" in out  # 20:30 CEST → 18:30Z


def test_end_before_start_falls_back_to_default() -> None:
    # End ≤ Start ist ungültig → Default-Dauer statt absurder Rückwärts-Spanne.
    out = _ics([_ev(start_time=time(18, 0), end_time=time(17, 0))])
    assert "DTEND:20260715T170000Z" in out  # = Start (16:00Z) + 1 h


def test_all_day_event_has_no_dtend() -> None:
    out = _ics([_ev(start_time=None, end_time=None)])
    assert "DTSTART;VALUE=DATE:20260715" in out
    assert "DTEND" not in out


def test_alarm_timed_one_hour_before() -> None:
    out = _ics([_ev(start_time=time(18, 0))])
    assert "BEGIN:VALARM" in out
    assert "ACTION:DISPLAY" in out
    assert "TRIGGER:-PT1H" in out


def test_alarm_allday_one_day_before() -> None:
    out = _ics([_ev(start_time=None)])
    assert "TRIGGER:-P1D" in out


def test_uid_stable_with_domain() -> None:
    out = _ics([_ev(uid="abc-123")])
    assert "UID:meeting-abc-123@stupa.example.org" in out


def test_dtstamp_from_created_at() -> None:
    assert "DTSTAMP:20260101T120000Z" in _ics([_ev()])


def test_summary_and_description() -> None:
    out = _ics([_ev(title="Haushalt", gremium_name="AStA")])
    assert "SUMMARY:Haushalt" in out
    assert "DESCRIPTION:Gremium: AStA" in out


def test_no_description_without_gremium() -> None:
    out = _ics([_ev(title="Solo", gremium_name=None)])
    assert "SUMMARY:Solo" in out
    # Kein Event-DESCRIPTION (das VALARM trägt weiterhin eine eigene Beschreibung).
    assert "DESCRIPTION:Gremium" not in out


def test_text_escaping() -> None:
    # RFC5545 escaping: comma, semicolon und backslash (icalendar).
    out = _ics([_ev(title="A, B; C\\ D")])
    assert "SUMMARY:A\\, B\\; C\\\\ D" in out


def test_naive_stamp_treated_as_utc() -> None:
    out = _ics([_ev(stamp=datetime(2026, 3, 1, 9, 30))])
    assert "DTSTAMP:20260301T093000Z" in out


def test_empty_calendar() -> None:
    out = _ics([])
    assert "BEGIN:VCALENDAR" in out
    assert "BEGIN:VEVENT" not in out


def test_multiple_events() -> None:
    out = _ics([_ev(uid="a"), _ev(uid="b")])
    assert out.count("BEGIN:VEVENT") == 2
