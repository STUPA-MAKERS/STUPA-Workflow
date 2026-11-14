"""The periods of the Geschäftsordnung (§F/administration/admin/000917).

The one row of ``meeting_settings`` holds them. An admin with ``admin.deadlines``
changes them (``GET/PUT /admin/meeting-periods``). The meeting form reads the two
invitation periods with ``GET /committees/{id}/meeting-defaults``.

- ``inviteDaysOrdinary`` and ``inviteDaysExtraordinary``: the invitation period of a
  meeting, in days. Only an ``ordinary`` meeting has the first one.
- ``protocolDraftDays``: the days after a meeting until the draft of its protocol is due.
- ``lateExcuseDays``: the days after the close in which a member can still give an excuse.
- ``absenceLimit``: the number of unexcused absences in one term that ends a Mandat.
- ``circularMinDays``: the least number of days of an Umlaufverfahren.
- ``termStartMonth``: the month on whose first day a term (Amtszeit) starts.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.modules.meetings.models import MeetingSettings

#: The periods of the settings row, as (model attribute, JSON key).
PERIOD_FIELDS: tuple[tuple[str, str], ...] = (
    ("invite_days_ordinary", "inviteDaysOrdinary"),
    ("invite_days_extraordinary", "inviteDaysExtraordinary"),
    ("protocol_draft_days", "protocolDraftDays"),
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
