"""The open window of a meeting and its settings.

A planned meeting opens (``planned`` to ``live``) at the earliest
``open_lead_minutes`` before its planned start. From that point on, and for a
meeting that is late, the open needs nothing more. A meeting without a date has
no window, because it has no planned start.

One row (``meeting_settings``, id=1) holds the value. ``GET/PUT
/admin/meeting-settings`` (``admin.deadlines``) reads and writes it. The PUT writes a
``config_change`` audit entry without a revision, so the audit log cannot revert it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.meetings.models import (
    DEFAULT_ABSENCE_LIMIT,
    DEFAULT_CIRCULAR_MIN_DAYS,
    DEFAULT_GREMIUM_DELEGATION_LEAD_MINUTES,
    DEFAULT_GREMIUM_DELEGATION_MAX_PER_DELEGATE,
    DEFAULT_GREMIUM_QUORUM_PERCENT,
    DEFAULT_GREMIUM_REPEAT_QUORUM_PERCENT,
    DEFAULT_INVITE_DAYS_EXTRAORDINARY,
    DEFAULT_INVITE_DAYS_ORDINARY,
    DEFAULT_LATE_EXCUSE_DAYS,
    DEFAULT_OPEN_LEAD_MINUTES,
    DEFAULT_TERM_START_MONTH,
    Meeting,
    MeetingSettings,
)
from app.modules.meetings.periods import PERIOD_FIELDS, periods
from app.modules.meetings.roster import planned_start_utc
from app.shared.errors import ConflictError

AUDIT_TARGET_TYPE = "meeting_settings"

#: The Gremium defaults of the settings row, as (model attribute, JSON key).
GREMIUM_DEFAULT_FIELDS: tuple[tuple[str, str], ...] = (
    ("default_quorum_percent", "quorumPercent"),
    ("default_repeat_quorum_percent", "repeatQuorumPercent"),
    ("default_guests_may_vote", "guestsMayVote"),
    ("default_allow_vote_delegation", "allowVoteDelegation"),
    ("default_delegation_lead_minutes", "delegationLeadMinutes"),
    ("default_delegation_max_per_delegate", "delegationMaxPerDelegate"),
)


def gremium_defaults(row: MeetingSettings) -> dict[str, Any]:
    """Return the Gremium defaults of the settings row by their JSON keys."""
    return {key: getattr(row, attr) for attr, key in GREMIUM_DEFAULT_FIELDS}


@dataclass(frozen=True)
class OpenWindow:
    """The open window of one planned meeting, in UTC.

    ``opens_at`` is the earliest open.
    """

    opens_at: datetime


def _defaults() -> MeetingSettings:
    return MeetingSettings(
        id=1,
        open_lead_minutes=DEFAULT_OPEN_LEAD_MINUTES,
        default_quorum_percent=DEFAULT_GREMIUM_QUORUM_PERCENT,
        default_repeat_quorum_percent=DEFAULT_GREMIUM_REPEAT_QUORUM_PERCENT,
        default_guests_may_vote=False,
        default_allow_vote_delegation=False,
        default_delegation_lead_minutes=DEFAULT_GREMIUM_DELEGATION_LEAD_MINUTES,
        default_delegation_max_per_delegate=DEFAULT_GREMIUM_DELEGATION_MAX_PER_DELEGATE,
        invite_days_ordinary=DEFAULT_INVITE_DAYS_ORDINARY,
        invite_days_extraordinary=DEFAULT_INVITE_DAYS_EXTRAORDINARY,
        late_excuse_days=DEFAULT_LATE_EXCUSE_DAYS,
        absence_limit=DEFAULT_ABSENCE_LIMIT,
        circular_min_days=DEFAULT_CIRCULAR_MIN_DAYS,
        term_start_month=DEFAULT_TERM_START_MONTH,
    )


async def load_meeting_settings(session: AsyncSession) -> MeetingSettings:
    """Return the settings row, or a transient row with the defaults.

    The migration inserts the row. A schema built with ``create_all`` alone (tests)
    can lack it, and so can a test database after the truncate between tests. The
    default then applies: 60 minutes. The function writes nothing.
    """
    row = await session.get(MeetingSettings, 1)
    return row if row is not None else _defaults()


def open_window(meeting: Meeting, settings: MeetingSettings, tz_name: str) -> OpenWindow | None:
    """Return the open window of a planned meeting, or None.

    None for a meeting that is not ``planned`` and for a meeting without a date. A
    meeting without a start time starts at 00:00 local time, as the delegation
    deadlines count it.
    """
    if meeting.status != "planned":
        return None
    start = planned_start_utc(meeting, tz_name)
    if start is None:
        return None
    return OpenWindow(opens_at=start - timedelta(minutes=settings.open_lead_minutes))


def check_open(window: OpenWindow | None, *, now: datetime) -> None:
    """Refuse an open of a meeting before its window.

    Raises:
        ConflictError: The open is before ``opens_at`` (``meeting_too_early``).
    """
    if window is None:
        return
    if now < window.opens_at:
        raise ConflictError(
            "the meeting cannot open yet — it opens at "
            f"{window.opens_at.isoformat()} at the earliest",
            code="meeting_too_early",
        )


def _write_fields(
    row: MeetingSettings,
    fields: tuple[tuple[str, str], ...],
    values: dict[str, Any],
    actor: str,
) -> None:
    """Write the values of ``fields`` and the change stamp to the settings row."""
    writes: dict[str, Any] = {
        **{attr: values[key] for attr, key in fields},
        "updated_at": datetime.now(UTC),
        "updated_by": actor,
    }
    for attr, value in writes.items():
        setattr(row, attr, value)


class MeetingSettingsService:
    """Read and change the meeting settings."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the service to a session."""
        self.session = session

    async def get(self) -> MeetingSettings:
        """Return the settings row. Create it with the defaults when it is missing."""
        stored = await self.session.get(MeetingSettings, 1)
        if stored is not None:
            return stored
        row = _defaults()
        row.updated_at = datetime.now(UTC)
        self.session.add(row)
        await self.session.flush()
        return row

    async def update(self, *, open_lead_minutes: int, actor: str) -> MeetingSettings:
        """Replace the value and write a ``config_change`` audit entry.

        The method commits.
        """
        row = await self.get()
        data: dict[str, Any] = {
            "openLeadMinutes": {"from": row.open_lead_minutes, "to": open_lead_minutes},
        }
        row.open_lead_minutes = open_lead_minutes
        row.updated_at = datetime.now(UTC)
        row.updated_by = actor
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.CONFIG_CHANGE,
            target_type=AUDIT_TARGET_TYPE,
            target_id="1",
            data=data,
        )
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def update_gremium_defaults(
        self, values: dict[str, Any], *, actor: str
    ) -> MeetingSettings:
        """Replace the Gremium defaults and write a ``config_change`` audit entry.

        ``values`` holds every default by its JSON key. The method touches no Gremium:
        only the form of a new Gremium reads the defaults. The caller commits.
        """
        row = await self.get()
        before = gremium_defaults(row)
        _write_fields(row, GREMIUM_DEFAULT_FIELDS, values, actor)
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.CONFIG_CHANGE,
            target_type=AUDIT_TARGET_TYPE,
            target_id="1",
            data={
                "gremiumDefaults": {
                    key: {"from": before[key], "to": values[key]}
                    for key in before
                    if before[key] != values[key]
                }
            },
        )
        return row

    async def update_periods(self, values: dict[str, Any], *, actor: str) -> MeetingSettings:
        """Replace the periods and write a ``config_change`` audit entry.

        ``values`` holds every period by its JSON key (see ``meetings.periods``). The
        caller commits.
        """
        row = await self.get()
        before = periods(row)
        _write_fields(row, PERIOD_FIELDS, values, actor)
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.CONFIG_CHANGE,
            target_type=AUDIT_TARGET_TYPE,
            target_id="1",
            data={
                "periods": {
                    key: {"from": before[key], "to": values[key]}
                    for key in before
                    if before[key] != values[key]
                }
            },
        )
        return row
