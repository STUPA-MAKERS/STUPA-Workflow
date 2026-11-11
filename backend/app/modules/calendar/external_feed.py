"""Read an ICS feed of another system into plain entries.

`parse_feed` keeps of each event only the title, the start, the end, the place and the
description, as plain text. It never reads an organiser, an attendee or an attachment,
because a foreign feed can hold mail addresses of third persons.

Every time becomes a local ``Europe/Berlin`` value without a zone, like the times of a
meeting and a Termin. A recurring event is one entry per date inside a window of 12
months back and 24 months ahead. The rule runs on the local values, so a weekly event at
18:00 stays at 18:00 across a change of the clock. A rule with a frequency below a day
gives only the first date, because such a rule can hold millions of dates. A rule that
the reader cannot understand gives the first date too. A changed
date of a series (``RECURRENCE-ID``) replaces the date of the rule.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any, cast
from zoneinfo import ZoneInfo

if TYPE_CHECKING:  # pragma: no cover - types only (icalendar imported lazily)
    from icalendar import Component

BERLIN = ZoneInfo("Europe/Berlin")

#: The window of a recurring event around today.
WINDOW_BACK = timedelta(days=366)
WINDOW_AHEAD = timedelta(days=731)
#: The most dates of one series and the most entries of one calendar.
MAX_SERIES = 1000
MAX_ENTRIES = 5000

_TITLE_MAX = 200
_PLACE_MAX = 200
_DESCRIPTION_MAX = 5000
_TAG = re.compile(r"<[^>]*>")
_BLANKS = re.compile(r"[ \t\r\f\v]+")
_LINES = re.compile(r"\n{3,}")
_FAST = ("SECONDLY", "MINUTELY", "HOURLY")
_DAY = timedelta(days=1)


class FeedError(Exception):
    """The bytes are not a calendar that the reader understands."""


@dataclass(frozen=True, slots=True)
class FeedEntry:
    """One dated entry of a feed. Both times are None for an all-day entry."""

    title: str
    starts_on: date
    ends_on: date
    start_time: time | None = None
    end_time: time | None = None
    place: str | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class _Event:
    """One VEVENT with local values: its start, its length and its texts."""

    uid: str
    start: datetime
    all_day: bool
    length: timedelta
    title: str
    place: str | None
    description: str | None
    rule: Mapping[str, Any] | None
    excluded: frozenset[datetime]
    replaces: datetime | None


def plain(value: object, limit: int) -> str | None:
    """Reduce a text of a feed to plain text: no markup, no entities, at most ``limit``."""
    if value is None:
        return None
    text = html.unescape(_TAG.sub("", str(value))).replace("\r\n", "\n")
    lines = "\n".join(_BLANKS.sub(" ", line).strip() for line in text.split("\n"))
    return _LINES.sub("\n\n", lines).strip()[:limit] or None


def _naive(value: date | datetime, *, end_of_day: bool = False) -> datetime:
    """Return the local Berlin value without a zone. A date becomes its first moment."""
    if not isinstance(value, datetime):
        return datetime.combine(value, time(23, 59, 59) if end_of_day else time.min)
    return (
        value.astimezone(BERLIN).replace(tzinfo=None) if value.tzinfo is not None else value
    ).replace(microsecond=0)


def _decoded(component: Component, name: str) -> object:
    """Return the decoded value of a property, None when it is missing.

    icalendar gives a line that it cannot read as its text, which is no date.
    """
    return component.decoded(name) if name in component else None


def _dates(value: object) -> tuple[date | datetime, ...]:
    """Flatten an EXDATE value, which is one list or several lists of dates.

    icalendar keeps a line that it cannot read as a text value, which is skipped here.
    """
    if value is None:
        return ()
    return tuple(
        cast("date | datetime", item.dt)
        for group in (value if isinstance(value, list) else [value])
        if not isinstance(group, str)
        for item in getattr(group, "dts", ())
    )


def _length(start: object, end: object, duration: object, *, all_day: bool) -> timedelta:
    """Return the length of an event from DTEND or DURATION, never below zero."""
    fallback = _DAY if all_day else timedelta(0)
    if isinstance(duration, timedelta):
        return max(duration, timedelta(0))
    if isinstance(start, date) and isinstance(end, date):
        return max(_naive(end) - _naive(start), timedelta(0)) or fallback
    return fallback


def _event(component: Component) -> _Event | None:
    """Read one VEVENT. An event without a start or a title is skipped."""
    start = _decoded(component, "dtstart")
    title = plain(component.get("summary"), _TITLE_MAX)
    if not isinstance(start, date) or title is None:
        return None
    all_day = not isinstance(start, datetime)
    replaces = _decoded(component, "recurrence-id")
    rule = component.get("rrule")
    return _Event(
        uid=str(component.get("uid", "")),
        start=_naive(start),
        all_day=all_day,
        length=_length(
            start, _decoded(component, "dtend"), _decoded(component, "duration"), all_day=all_day
        ),
        title=title,
        place=plain(component.get("location"), _PLACE_MAX),
        description=plain(component.get("description"), _DESCRIPTION_MAX),
        rule=rule if isinstance(rule, Mapping) else None,
        excluded=frozenset(_naive(day) for day in _dates(component.get("exdate"))),
        replaces=_naive(replaces) if isinstance(replaces, date) else None,
    )


def _rule_text(rule: Mapping[str, Any]) -> str:
    """Render the rule with a local UNTIL, so it compares with the local start."""
    from icalendar import vRecur

    local = {
        key: (
            [_naive(until, end_of_day=True) for until in values]
            if key.upper() == "UNTIL"
            else values
        )
        for key, values in rule.items()
    }
    return vRecur(local).to_ical().decode()


def _starts(event: _Event, taken: frozenset[datetime], today: date) -> tuple[datetime, ...]:
    """Return the starts of an event: its one start, or the dates of its rule in the window.

    ``taken`` holds the dates that a changed event of the same series replaces.
    """
    from dateutil.rrule import rrulestr

    rule = event.rule
    if rule is None or any(str(freq).upper() in _FAST for freq in rule.get("FREQ", ())):
        return (event.start,)
    try:
        series = rrulestr(_rule_text(rule), dtstart=event.start)
        found = tuple(
            dict.fromkeys(
                series.xafter(_naive(today - WINDOW_BACK) - event.length, MAX_SERIES, inc=True)
            )
        )
    except (ValueError, TypeError, OverflowError):
        return (event.start,)
    last = _naive(today + WINDOW_AHEAD, end_of_day=True)
    return tuple(
        start
        for start in found
        if start <= last and start not in event.excluded and start not in taken
    )


def _entry(event: _Event, start: datetime) -> FeedEntry:
    """Build the entry of one start. The end of an all-day entry is its last day."""
    end = start + event.length
    last_day = (end - _DAY).date() if event.all_day else end.date()
    return FeedEntry(
        title=event.title,
        starts_on=start.date(),
        ends_on=max(last_day, start.date()),
        start_time=None if event.all_day else start.time(),
        end_time=None if event.all_day else end.time(),
        place=event.place,
        description=event.description,
    )


def _nearest(entries: Iterable[FeedEntry], today: date) -> tuple[FeedEntry, ...]:
    """Keep at most `MAX_ENTRIES`, the nearest to today, sorted by day and time."""
    kept = sorted(entries, key=lambda e: abs((e.starts_on - today).days))[:MAX_ENTRIES]
    return tuple(sorted(kept, key=lambda e: (e.starts_on, e.start_time or time.min, e.title)))


def _entries(calendar: Component, today: date) -> tuple[FeedEntry, ...]:
    events = tuple(
        event for event in (_event(c) for c in calendar.walk("VEVENT")) if event is not None
    )
    taken = {
        uid: frozenset(e.replaces for e in events if e.uid == uid and e.replaces is not None)
        for uid in {e.uid for e in events if e.replaces is not None}
    }
    return _nearest(
        (
            _entry(event, start)
            for event in events
            for start in _starts(
                event,
                taken.get(event.uid, frozenset()) if event.replaces is None else frozenset(),
                today,
            )
        ),
        today,
    )


def parse_feed(data: bytes, today: date) -> tuple[FeedEntry, ...]:
    """Read the entries of an ICS feed.

    Raises:
        FeedError: The bytes are not a calendar, or a value in it breaks the reader.
    """
    from icalendar import Calendar

    try:
        return _entries(Calendar.from_ical(data), today)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError) as exc:
        raise FeedError("not a calendar") from exc
