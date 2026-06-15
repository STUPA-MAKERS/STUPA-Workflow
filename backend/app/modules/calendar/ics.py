"""iCal-Feed-Builder (#ics) — Sitzungen → RFC5545 ``VCALENDAR`` (reine Funktion).

Kennt **keine** DB: nimmt fertige :class:`MeetingEvent`-Werte und liefert die
``.ics``-Bytes. ``icalendar`` wird **lazy** importiert (nur auf dem Feed-Pfad, wie
openpyxl/minio) — der Import dieses Moduls bleibt billig.

**Zeitzonen.** Sitzungen tragen lokale Uhrzeiten (Europe/Berlin). Terminierte Events
werden nach UTC konvertiert und mit ``Z`` ausgegeben (``DTSTART:…T…Z``) — das spart
den fehleranfälligen ``VTIMEZONE``-Block und ist über alle Clients eindeutig. Die
DST-Wahl (CET/CEST) ergibt sich pro Datum aus :mod:`zoneinfo` (stdlib). Sitzungen ohne
Uhrzeit werden als ganztägige Events (``VALUE=DATE``) ausgegeben.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from datetime import date as _date
from datetime import time as _time
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:  # pragma: no cover - nur Typen (icalendar lazy importiert)
    from icalendar import Event

# Lokale Zeitzone der Sitzungen (Anzeige-/Eingabezeit).
_LOCAL_TZ = ZoneInfo("Europe/Berlin")

# Default-Dauer terminierter Sitzungen ohne (gültige) End-Uhrzeit (Entscheidung #ics).
DEFAULT_DURATION = timedelta(hours=1)

# Erinnerungs-Vorlauf (VALARM): terminiert 1 h vorher, ganztägig 1 Tag vorher.
_ALARM_LEAD_TIMED = timedelta(hours=-1)
_ALARM_LEAD_ALLDAY = timedelta(days=-1)


@dataclass(frozen=True, slots=True)
class MeetingEvent:
    """Eine Sitzung als Kalender-Event (vom Service aus :class:`Meeting` gemappt).

    ``uid`` ist die stabile Meeting-ID (UID bleibt über Re-Renders gleich), ``stamp``
    der ``created_at``-Zeitpunkt (deterministischer ``DTSTAMP``). Zeiten sind lokale
    naive ``time``-Werte; ``date`` ist Pflicht (Events ohne Datum filtert der Service).
    """

    uid: str
    title: str
    date: _date
    start_time: _time | None
    end_time: _time | None
    stamp: datetime
    gremium_name: str | None = None


def _as_utc(value: datetime) -> datetime:
    """Aware-Datetime → UTC; naive Werte werden als UTC interpretiert (Defensive)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _local_to_utc(day: _date, clock: _time) -> datetime:
    """Lokale (Europe/Berlin) Datum+Uhrzeit → aware UTC-Datetime (DST-korrekt)."""
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
        # Ganztägig: DTSTART als reines DATE (kein DTEND → genau ein Tag).
        ical.add("dtstart", event.date)
        lead = _ALARM_LEAD_ALLDAY
    else:
        start = _local_to_utc(event.date, event.start_time)
        # End-Uhrzeit nur, wenn sie nach der Start-Uhrzeit liegt; sonst Default-Dauer.
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
    """Sitzungen → ``VCALENDAR``-Bytes (RFC5545, CRLF-gefaltet, escaped via icalendar).

    ``domain`` macht die Event-UIDs global eindeutig + stabil (aus der öffentlichen
    Basis-URL abgeleitet). ``events`` ist bereits gefiltert/​sortiert (Service).
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
