"""iCal feed builder — meetings to RFC5545 ``VCALENDAR`` (pure function, no DB).

``icalendar`` is imported lazily (feed path only) to keep module import cheap.

Timezones: meetings carry local times (Europe/Berlin). Timed events are
converted to UTC and emitted with ``Z``, avoiding the error-prone ``VTIMEZONE``
block; DST is resolved per date via :mod:`zoneinfo`. Meetings without a time
become all-day events (``VALUE=DATE``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from datetime import date as _date
from datetime import time as _time
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:  # pragma: no cover - types only (icalendar imported lazily)
    from icalendar import Event

# Local timezone of meetings (display/input time).
_LOCAL_TZ = ZoneInfo("Europe/Berlin")

# Default duration of timed meetings without a (valid) end time.
DEFAULT_DURATION = timedelta(hours=1)

# Reminder lead (VALARM): timed 1 h before, all-day 1 day before.
_ALARM_LEAD_TIMED = timedelta(hours=-1)
_ALARM_LEAD_ALLDAY = timedelta(days=-1)


@dataclass(frozen=True, slots=True)
class MeetingEvent:
    """A meeting as a calendar event (mapped from :class:`Meeting` by the service).

    ``uid`` is the stable meeting id (constant across re-renders), ``stamp`` the
    ``created_at`` timestamp (deterministic ``DTSTAMP``). Times are local naive
    ``time`` values; ``date`` is required (undated events are filtered upstream).
    """

    uid: str
    title: str
    date: _date
    start_time: _time | None
    end_time: _time | None
    stamp: datetime
    gremium_name: str | None = None


def _as_utc(value: datetime) -> datetime:
    """Convert to UTC; naive values are treated as UTC (defensive)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _local_to_utc(day: _date, clock: _time) -> datetime:
    """Combine local (Europe/Berlin) date+time into an aware UTC datetime (DST-correct)."""
    return datetime.combine(day, clock, tzinfo=_LOCAL_TZ).astimezone(UTC)


def _build_event(
    event: MeetingEvent, *, domain: str, default_duration: timedelta
) -> Event:
    from icalendar import Alarm, Event

    ical = Event()
    ical.add("uid", f"meeting-{event.uid}@{domain}")
    ical.add("dtstamp", _as_utc(event.stamp))
    ical.add("summary", event.title)
    if event.gremium_name:
        ical.add("description", f"Gremium: {event.gremium_name}")

    if event.start_time is None:
        # All-day: DTSTART as plain DATE (no DTEND -> exactly one day).
        ical.add("dtstart", event.date)
        lead = _ALARM_LEAD_ALLDAY
    else:
        start = _local_to_utc(event.date, event.start_time)
        # Use the end time only if it is after the start time; otherwise default duration.
        if event.end_time is not None and event.end_time > event.start_time:
            end = _local_to_utc(event.date, event.end_time)
        else:
            end = start + default_duration
        ical.add("dtstart", start)
        ical.add("dtend", end)
        lead = _ALARM_LEAD_TIMED

    alarm = Alarm()
    alarm.add("action", "DISPLAY")
    alarm.add("description", f"Erinnerung: {event.title}")
    alarm.add("trigger", lead)
    ical.add_component(alarm)
    return ical


def build_calendar(
    events: list[MeetingEvent],
    *,
    domain: str,
    calendar_name: str = "STUPA — Sitzungen",
    default_duration: timedelta = DEFAULT_DURATION,
) -> bytes:
    """Render meetings to ``VCALENDAR`` bytes (RFC5545, CRLF-folded via icalendar).

    ``domain`` makes event UIDs globally unique and stable; ``events`` arrive
    pre-filtered and sorted.
    """
    from icalendar import Calendar

    cal = Calendar()
    cal.add("prodid", "-//STUPA-Workflow//iCal Feed//DE")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", calendar_name)
    cal.add("x-wr-timezone", "Europe/Berlin")
    for event in events:
        cal.add_component(
            _build_event(event, domain=domain, default_duration=default_duration)
        )
    return cal.to_ical()
