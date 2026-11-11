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

A Termin is timed or all-day and can span several days. Its feed entry carries the
answer of the feed owner as `PARTSTAT` of an `ATTENDEE` line with the owner's own
address. `build_appointment_file` renders one Termin as the `.ics` attachment of a
mail: `SEQUENCE` counts its changes, so a calendar app replaces the older copy, and a
deleted Termin has `METHOD:CANCEL` and `STATUS:CANCELLED`.

An entry of an external calendar is timed or all-day, with the name of its calendar as
`CATEGORIES`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from datetime import date as _date
from datetime import time as _time
from typing import TYPE_CHECKING, cast
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
#: The length of a timed Event without an end time.
_EVENT_DURATION = timedelta(hours=1)


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
    """An Event card as a calendar event (spec 000486).

    `uid` is the card id. `end` is the last day, or `None` for one day. The times are
    local naive values. An Event without a start time is an all-day event.
    """

    uid: str
    title: str
    start: _date
    end: _date | None
    stamp: datetime
    place: str | None = None
    board_name: str | None = None
    start_time: _time | None = None
    end_time: _time | None = None


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


#: The participation status of an answer, and of an invited person without an answer.
PARTSTAT: dict[str | None, str] = {
    "accept": "ACCEPTED",
    "tentative": "TENTATIVE",
    "decline": "DECLINED",
    None: "NEEDS-ACTION",
}


@dataclass(frozen=True, slots=True)
class AppointmentEvent:
    """A Termin as a calendar event.

    `uid` is the id of the Termin. The times are local naive values, and both are
    `None` for an all-day Termin. `attendee` is the address of the person whose feed
    or mail this is, with `answer` as that person's answer; without an address the
    event has no `ATTENDEE` line.
    """

    uid: str
    title: str
    starts_on: _date
    ends_on: _date
    start_time: _time | None
    end_time: _time | None
    stamp: datetime
    place: str | None = None
    description: str | None = None
    sequence: int = 0
    attendee: str | None = None
    answer: str | None = None
    cancelled: bool = False


@dataclass(frozen=True, slots=True)
class ExternalEvent:
    """An entry of an external calendar as a calendar event.

    `uid` is the id of the stored entry. The times are local naive values, and both are
    `None` for an all-day entry. `calendar` is the name of the external calendar.
    """

    uid: str
    title: str
    starts_on: _date
    ends_on: _date
    start_time: _time | None
    end_time: _time | None
    stamp: datetime
    calendar: str
    place: str | None = None
    description: str | None = None


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
    """Build one VEVENT for an Event card: timed with a start time, else all-day.

    A timed Event without an end time takes `_EVENT_DURATION`.
    """
    from icalendar import Event

    last = event.end if event.end is not None and event.end > event.start else event.start
    begin = None if event.start_time is None else _local_to_utc(event.start, event.start_time)
    finish = (
        None
        if begin is None
        else begin + _EVENT_DURATION
        if event.end_time is None
        else max(_local_to_utc(last, event.end_time), begin)
    )
    properties = (
        ("uid", f"event-{event.uid}@{domain}"),
        ("dtstamp", _as_utc(event.stamp)),
        ("summary", event.title),
        *_when(event.place, ("location", event.place)),
        *_when(event.board_name, ("description", f"Board: {event.board_name}")),
        ("dtstart", event.start if begin is None else begin),
        ("dtend", last + timedelta(days=1) if finish is None else finish),
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


def _attendee(address: str, answer: str | None) -> object:
    """Build the ATTENDEE value of the feed owner with the answer as PARTSTAT."""
    from icalendar import vCalAddress

    value = vCalAddress(f"mailto:{address}")
    value.params.update({"PARTSTAT": PARTSTAT.get(answer, PARTSTAT[None])})
    return value


def _appointment_span(event: AppointmentEvent) -> tuple[Property, ...]:
    """Return DTSTART and DTEND of a Termin: UTC instants, or dates with an exclusive end."""
    return (
        (("dtstart", event.starts_on), ("dtend", event.ends_on + timedelta(days=1)))
        if event.start_time is None or event.end_time is None
        else (
            ("dtstart", _local_to_utc(event.starts_on, event.start_time)),
            ("dtend", _local_to_utc(event.ends_on, event.end_time)),
        )
    )


def _build_appointment(event: AppointmentEvent, *, domain: str) -> Event:
    """Build one VEVENT for a Termin."""
    from icalendar import Event

    properties = (
        ("uid", f"appointment-{event.uid}@{domain}"),
        ("dtstamp", _as_utc(event.stamp)),
        ("sequence", event.sequence),
        ("summary", event.title),
        *_when(event.place, ("location", event.place)),
        *_when(event.description, ("description", event.description)),
        *_when(event.cancelled, ("status", "CANCELLED")),
        *((("attendee", _attendee(event.attendee, event.answer)),) if event.attendee else ()),
        *_appointment_span(event),
    )
    return _filled(Event(), properties)


def _build_external(event: ExternalEvent, *, domain: str) -> Event:
    """Build one VEVENT for an entry of an external calendar."""
    from icalendar import Event

    timed = event.start_time is not None and event.end_time is not None
    properties = (
        ("uid", f"external-{event.uid}@{domain}"),
        ("dtstamp", _as_utc(event.stamp)),
        ("summary", event.title),
        ("categories", [event.calendar]),
        *_when(event.place, ("location", event.place)),
        *_when(event.description, ("description", event.description)),
        *(
            (
                ("dtstart", _local_to_utc(event.starts_on, cast(_time, event.start_time))),
                ("dtend", _local_to_utc(event.ends_on, cast(_time, event.end_time))),
            )
            if timed
            else (("dtstart", event.starts_on), ("dtend", event.ends_on + timedelta(days=1)))
        ),
    )
    return _filled(Event(), properties)


def build_appointment_file(event: AppointmentEvent, *, domain: str) -> bytes:
    """Render one Termin as the `.ics` attachment of a mail."""
    from icalendar import Calendar

    properties = (
        ("prodid", "-//STUPA-Workflow//iCal Feed//DE"),
        ("version", "2.0"),
        ("calscale", "GREGORIAN"),
        ("method", "CANCEL" if event.cancelled else "PUBLISH"),
    )
    return _filled(Calendar(), properties, (_build_appointment(event, domain=domain),)).to_ical()


def build_calendar(
    events: Sequence[MeetingEvent],
    *,
    domain: str,
    card_events: Sequence[CardEvent] | None = None,
    due_cards: Sequence[DueCard] | None = None,
    appointments: Sequence[AppointmentEvent] | None = None,
    external: Sequence[ExternalEvent] | None = None,
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
        *(_build_appointment(a, domain=domain) for a in appointments or ()),
        *(_build_external(x, domain=domain) for x in external or ()),
    )
    return _filled(Calendar(), properties, parts).to_ical()
