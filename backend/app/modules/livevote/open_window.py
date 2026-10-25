"""The open window of a meeting and its settings.

A planned meeting opens (``planned`` to ``live``) at the earliest
``open_lead_minutes`` before its planned start. Up to ``confirm_lead_minutes``
before the start the open is early: the lead must confirm it (``confirmEarly`` on
the patch), and the frontend asks in an extra dialog. After that point, and for a
meeting that is late, the open needs nothing more. A meeting without a date has
no window, because it has no planned start.

One row (``meeting_settings``, id=1) holds both values. ``GET/PUT
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
from app.modules.livevote.models import (
    DEFAULT_CONFIRM_LEAD_MINUTES,
    DEFAULT_OPEN_LEAD_MINUTES,
    Meeting,
    MeetingSettings,
)
from app.modules.livevote.roster import planned_start_utc
from app.shared.errors import ConflictError, ValidationProblem

AUDIT_TARGET_TYPE = "meeting_settings"


@dataclass(frozen=True)
class OpenWindow:
    """The open window of one planned meeting, in UTC.

    ``opens_at`` is the earliest open. Before ``confirm_until`` the open is early and
    needs the confirmation.
    """

    opens_at: datetime
    confirm_until: datetime


def _defaults() -> MeetingSettings:
    return MeetingSettings(
        id=1,
        open_lead_minutes=DEFAULT_OPEN_LEAD_MINUTES,
        confirm_lead_minutes=DEFAULT_CONFIRM_LEAD_MINUTES,
    )


async def load_meeting_settings(session: AsyncSession) -> MeetingSettings:
    """Return the settings row, or a transient row with the defaults.

    The migration inserts the row. A schema built with ``create_all`` alone (tests)
    can lack it, and so can a test database after the truncate between tests. The
    defaults then apply: 60 minutes and 10 minutes. The function writes nothing.
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
    return OpenWindow(
        opens_at=start - timedelta(minutes=settings.open_lead_minutes),
        confirm_until=start - timedelta(minutes=settings.confirm_lead_minutes),
    )


def check_open(window: OpenWindow | None, *, now: datetime, confirmed: bool) -> None:
    """Refuse an open of a meeting outside its window.

    Raises:
        ConflictError: The open is before ``opens_at`` (``meeting_too_early``), or it
            is before ``confirm_until`` and not confirmed
            (``early_open_unconfirmed``).
    """
    if window is None:
        return
    if now < window.opens_at:
        raise ConflictError(
            "the meeting cannot open yet — it opens at "
            f"{window.opens_at.isoformat()} at the earliest",
            code="meeting_too_early",
        )
    if now < window.confirm_until and not confirmed:
        raise ConflictError(
            "the meeting opens before its planned start — confirm the early open",
            code="early_open_unconfirmed",
        )


class MeetingSettingsService:
    """Read and change the meeting settings."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the service to a session."""
        self.session = session

    async def get(self) -> MeetingSettings:
        """Return the settings row. Create it with the defaults when it is missing."""
        row = await self.session.get(MeetingSettings, 1)
        if row is None:
            row = _defaults()
            row.updated_at = datetime.now(UTC)
            self.session.add(row)
            await self.session.flush()
        return row

    async def update(
        self, *, open_lead_minutes: int, confirm_lead_minutes: int, actor: str
    ) -> MeetingSettings:
        """Replace both values and write a ``config_change`` audit entry.

        The confirmation point cannot be before the earliest open, so
        ``confirm_lead_minutes`` must not be larger than ``open_lead_minutes``. The
        method commits.

        Raises:
            ValidationProblem: ``confirmLeadMinutes`` is larger than
                ``openLeadMinutes`` (422).
        """
        if confirm_lead_minutes > open_lead_minutes:
            raise ValidationProblem(
                "confirmLeadMinutes must not be larger than openLeadMinutes",
                errors=[
                    {
                        "field": "confirmLeadMinutes",
                        "msg": "must not be larger than openLeadMinutes",
                    }
                ],
            )
        row = await self.get()
        data: dict[str, Any] = {
            "openLeadMinutes": {"from": row.open_lead_minutes, "to": open_lead_minutes},
            "confirmLeadMinutes": {
                "from": row.confirm_lead_minutes,
                "to": confirm_lead_minutes,
            },
        }
        row.open_lead_minutes = open_lead_minutes
        row.confirm_lead_minutes = confirm_lead_minutes
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
