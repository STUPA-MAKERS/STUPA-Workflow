"""Pure rules of the Veranstaltungen: the shop link and the segment of the page.

Every function here takes plain values and returns a plain value. The service and the
listing read the database, call these functions or their SQL twins and write the result.
"""

from __future__ import annotations

from datetime import date, time
from typing import Literal

from app.modules.orders.rules import url_valid

#: The segments of the page "Veranstaltungen" (F/collaboration/events/003028).
Segment = Literal["upcoming", "past", "done", "void"]

__all__ = ["Segment", "dates_problem", "segment_of", "shop_valid"]


def shop_valid(url: str) -> bool:
    """Tell whether the shop is an http or https address (F/collaboration/events/003024)."""
    return url_valid(url)


def segment_of(phase: str, starts_on: date | None, ends_on: date | None, today: date) -> Segment:
    """Return the segment of an Event (F/collaboration/events/003028).

    An Event of the phase ``open`` is ``upcoming`` while its end, else its start, is today
    or later, or while it has no start. After that day it is ``past`` until a person
    settles it. `EventListing` holds the same rule as SQL.
    """
    match phase:
        case "done":
            return "done"
        case "void":
            return "void"
        case _:
            day = ends_on or starts_on
            return "upcoming" if day is None or day >= today else "past"


def dates_problem(
    starts_on: date | None,
    start_time: time | None,
    ends_on: date | None,
    end_time: time | None,
) -> tuple[str, str] | None:
    """Return the code and the field of a wrong set of dates, else None (000736, 003023).

    The end must not be before the start, and a time needs its day. An Event without a
    time is an all-day entry.
    """
    if ends_on is not None and (starts_on is None or ends_on < starts_on):
        return ("event_dates_invalid", "endsOn")
    if start_time is not None and starts_on is None:
        return ("event_time_without_date", "startTime")
    if end_time is not None and ends_on is None:
        return ("event_time_without_date", "endTime")
    if (
        start_time is not None
        and end_time is not None
        and ends_on == starts_on
        and end_time < start_time
    ):
        return ("event_dates_invalid", "endTime")
    return None
