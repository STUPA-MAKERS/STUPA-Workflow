"""The periods of the Geschäftsordnung (§F/administration/admin/000917).

The one row of ``meeting_settings`` holds them. An admin with ``admin.deadlines``
changes them (``GET/PUT /admin/meeting-periods``). The meeting form reads the two
invitation periods with ``GET /committees/{id}/meeting-defaults``.

- ``inviteDaysOrdinary`` and ``inviteDaysExtraordinary``: the invitation period of a
  meeting, in days. Only an ``ordinary`` meeting has the first one.
- ``lateExcuseDays``: the days after the close in which a member can still give an excuse.
- ``absenceLimit``: the number of unexcused absences in one term that ends a Mandat.
- ``circularMinDays``: the least number of days of an Umlaufverfahren.
- ``termStartMonth``: the month on whose first day a term (Amtszeit) starts.

A changed period does not reach a started case (§F/administration/admin/000942). A
meeting keeps ``lateExcuseDays`` of the time it was made (``meeting.late_excuse_days``),
because this period is the only one that a stored meeting reads again: the invitation
periods give only a warning in the meeting form, and an Umlaufverfahren checks
``circularMinDays`` only at its open and takes no change of its end after that.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.modules.meetings.models import DEFAULT_LATE_EXCUSE_DAYS, MeetingSettings

#: The periods of the settings row, as (model attribute, JSON key).
PERIOD_FIELDS: tuple[tuple[str, str], ...] = (
    ("invite_days_ordinary", "inviteDaysOrdinary"),
    ("invite_days_extraordinary", "inviteDaysExtraordinary"),
    ("late_excuse_days", "lateExcuseDays"),
    ("absence_limit", "absenceLimit"),
    ("circular_min_days", "circularMinDays"),
    ("term_start_month", "termStartMonth"),
)

ORDINARY = "ordinary"


def periods(row: MeetingSettings) -> dict[str, Any]:
    """Return the periods of the settings row by their JSON keys."""
    return {key: getattr(row, attr) for attr, key in PERIOD_FIELDS}


def term_start(today: date, start_month: int) -> date:
    """Return the first day of the term that holds ``today``.

    A term starts on the first day of ``start_month`` and runs one year.
    """
    year = today.year if today.month >= start_month else today.year - 1
    return date(year, start_month, 1)


def term_end(start: date) -> date:
    """Return the first day after the term that starts on ``start``."""
    return date(start.year + 1, start.month, 1)


def kept_late_excuse_days(kept: int | None, current: int | None) -> int:
    """Return the late-excuse period of one meeting, in days.

    ``kept`` is the value that the meeting stored when it was made. A meeting from
    before the column has none and takes ``current``, the value of the settings row; a
    database without this row takes the default.
    """
    if kept is not None:
        return kept
    return DEFAULT_LATE_EXCUSE_DAYS if current is None else int(current)
