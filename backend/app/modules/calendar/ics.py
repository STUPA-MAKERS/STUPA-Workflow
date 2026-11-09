"""iCal feed builder: meetings and Events to an RFC5545 `VCALENDAR` (pure functions, no DB).

The module imports `icalendar` lazily, on the feed path only. This keeps the
module import cheap.

Time zones: meetings carry local times (Europe/Berlin). The builder converts a
timed event to UTC and writes it with `Z`. This avoids the error-prone
`VTIMEZONE` block. `zoneinfo` resolves DST per date. A meeting without a time
becomes an all-day event (`VALUE=DATE`). An Event (a to-do card with event data) is
always all-day: `DTEND` is the day after its end, because RFC5545 makes the end of
a `VALUE=DATE` event exclusive. An Event without an end lasts one day. A due card
(spec 000549) is an all-day event on its due date with the url of the card.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from datetime import date as _date
from datetime import time as _time
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:  # pragma: no cover - types only (icalendar imported lazily)
    from icalendar import Component, Event

#: One iCal property as a name and the value that icalendar encodes.
type Property = tuple[str, object]

_LOCAL_TZ = ZoneInfo("Europe/Berlin")

#: Duration of a timed meeting that has no valid end time.
DEFAULT_DURATION = timedelta(hours=1)

#: VALARM reminder lead, relative to the start of the event.
_ALARM_LEAD_TIMED = timedelta(hours=-1)
_ALARM_LEAD_ALLDAY = timedelta(days=-1)


@dataclass(frozen=True, slots=True)
class MeetingEvent:
    """A meeting as a calendar event, mapped from a `Meeting` row by the service.

    `uid` is the stable meeting id and stays constant across re-renders. `stamp`
    is the `created_at` timestamp, which makes `DTSTAMP` deterministic. The times
    are local naive `time` values. `date` is required, because the service drops
    meetings without a date.
    """

    uid: str
    title: str
    date: _date
    start_time: _time | None
    end_time: _time | None
    stamp: datetime
    gremium_name: str | None = None


@dataclass(frozen=True, slots=True)
class CardEvent:
    """An Event card as an all-day calendar event (spec 000486).

    `uid` is the card id. `end` is the last day, or `None` for one day.
    """

    uid: str
    title: str
    start: _date
    end: _date | None
    stamp: datetime
    place: str | None = None
    board_name: str | None = None


@dataclass(frozen=True, slots=True)
class DueCard:
    """A card with a due date as an all-day calendar event (spec 000549).

    `uid` is the card id. `url` opens the card in the app.
    """

    uid: str
    title: str
    due: _date
    stamp: datetime
    board_name: str
    url: str


def _as_utc(value: datetime) -> datetime:
    """Convert a datetime to UTC and treat a naive value as UTC (defensive)."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _local_to_utc(day: _date, clock: _time) -> datetime:
    """Combine a local (Europe/Berlin) date and time into an aware UTC datetime.

    The conversion applies the DST offset of that date.
    """
    return datetime.combine(day, clock, tzinfo=_LOCAL_TZ).astimezone(UTC)


def _filled[C: Component](
    component: C, properties: Iterable[Property], parts: Iterable[Component] = ()
) -> C:
    """Add the properties, then the subcomponents, to a new component and return it.

    icalendar builds a component only through `add`, so this is the one place that writes into
    one. The order of the properties is the order of the lines in the feed.
    """
    for name, value in properties:
        component.add(name, value)
    for part in parts:
        component.add_component(part)
    return component


def _when(condition: object, *properties: Property) -> tuple[Property, ...]:
    """Return the properties when the condition is truthy, else no property."""
    return properties if condition else ()


def _timed_span(
    day: _date, start_time: _time, end_time: _time | None, default_duration: timedelta
) -> tuple[Property, ...]:
    """Return DTSTART and DTEND of a timed meeting in UTC.

    The end time counts only when it is after the start time, else the meeting lasts
    `default_duration`.
    """
    start = _local_to_utc(day, start_time)
    end = (
        _local_to_utc(day, end_time)
        if end_time is not None and end_time > start_time
        else start + default_duration
    )
    return (("dtstart", start), ("dtend", end))


def _build_event(event: MeetingEvent, *, domain: str, default_duration: timedelta) -> Event:
    """Build one VEVENT for a meeting.

    An all-day event has DTSTART as a plain DATE and no DTEND, so it lasts one day. A timed event
    uses the end time only when it is after the start time.
    """
    from icalendar import Alarm, Event

    span = (
        (("dtstart", event.date),)
        if event.start_time is None
        else _timed_span(event.date, event.start_time, event.end_time, default_duration)
    )
    lead = _ALARM_LEAD_ALLDAY if event.start_time is None else _ALARM_LEAD_TIMED
    alarm = _filled(
        Alarm(),
        (
            ("action", "DISPLAY"),
            ("description", f"Erinnerung: {event.title}"),
            ("trigger", lead),
        ),
    )
    properties = (
        ("uid", f"meeting-{event.uid}@{domain}"),
        ("dtstamp", _as_utc(event.stamp)),
        ("summary", event.title),
        *_when(event.gremium_name, ("description", f"Gremium: {event.gremium_name}")),
        *span,
    )
    return _filled(Event(), properties, (alarm,))


def _build_card_event(event: CardEvent, *, domain: str) -> Event:
    """Build one all-day VEVENT for an Event card."""
    from icalendar import Event

    last = event.end if event.end is not None and event.end > event.start else event.start
    properties = (
        ("uid", f"event-{event.uid}@{domain}"),
        ("dtstamp", _as_utc(event.stamp)),
        ("summary", event.title),
        *_when(event.place, ("location", event.place)),
        *_when(event.board_name, ("description", f"Board: {event.board_name}")),
        ("dtstart", event.start),
        ("dtend", last + timedelta(days=1)),
    )
    return _filled(Event(), properties)


def _build_due_card(card: DueCard, *, domain: str) -> Event:
    """Build one all-day VEVENT for a due card."""
    from icalendar import Event

    properties = (
        ("uid", f"due-{card.uid}@{domain}"),
        ("dtstamp", _as_utc(card.stamp)),
        ("summary", card.title),
        ("description", f"Board: {card.board_name}"),
        ("url", card.url),
        ("dtstart", card.due),
        ("dtend", card.due + timedelta(days=1)),
    )
    return _filled(Event(), properties)


def build_calendar(
    events: Sequence[MeetingEvent],
    *,
    domain: str,
    card_events: Sequence[CardEvent] | None = None,
    due_cards: Sequence[DueCard] | None = None,
    calendar_name: str = "STUPA — Sitzungen",
    default_duration: timedelta = DEFAULT_DURATION,
) -> bytes:
    """Render meetings to `VCALENDAR` bytes (RFC5545, CRLF-folded by icalendar).

    The caller filters and sorts the meetings first. `domain` is the host name
    that makes the event UIDs globally unique and stable.
    """
    from icalendar import Calendar

    properties = (
        ("prodid", "-//STUPA-Workflow//iCal Feed//DE"),
        ("version", "2.0"),
        ("calscale", "GREGORIAN"),
        ("method", "PUBLISH"),
        ("x-wr-calname", calendar_name),
        ("x-wr-timezone", "Europe/Berlin"),
    )
    parts = (
        *(_build_event(e, domain=domain, default_duration=default_duration) for e in events),
        *(_build_card_event(c, domain=domain) for c in card_events or ()),
        *(_build_due_card(d, domain=domain) for d in due_cards or ()),
    )
    return _filled(Calendar(), properties, parts).to_ical()
