"""The approval mark of a final protocol (§F/meetings/protocols/000924).

The Gremium approves each protocol in its next meeting. A person with
``protocol.finalize`` sets the mark on a final protocol and names the meeting that
approved it. The mark is three columns of ``protocol``: ``approved_at``,
``approved_meeting_id`` and ``approved_by``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.meetings.models import Meeting
from app.modules.meetings.protocol_models import Protocol
from app.shared.errors import ConflictError, ValidationProblem

PROTOCOL_NOT_FINAL = "protocol_not_final"
INVALID_APPROVAL_MEETING = "invalid_approval_meeting"


async def approval_fields(session: AsyncSession, protocol: Protocol) -> dict[str, Any]:
    """Return the approval fields of ``ProtocolOut`` (empty without a mark)."""
    approved_at = getattr(protocol, "approved_at", None)
    if approved_at is None:
        return {}
    meeting_id = getattr(protocol, "approved_meeting_id", None)
    meeting = await session.get(Meeting, meeting_id) if meeting_id is not None else None
    return {
        "approvedAt": approved_at,
        "approvedMeetingId": meeting_id,
        "approvedMeetingTitle": meeting.title if meeting is not None else None,
        "approvedMeetingDate": meeting.date if meeting is not None else None,
    }


async def _audit(session: AsyncSession, protocol: Protocol, actor: str) -> None:
    await audit_record(
        session,
        actor=actor,
        action=AuditAction.PROTOCOL_APPROVAL,
        target_type="protocol",
        target_id=str(protocol.id),
        data={
            "meetingId": str(protocol.meeting_id),
            "gremiumId": str(protocol.gremium_id),
            "approvedMeetingId": str(protocol.approved_meeting_id)
            if protocol.approved_meeting_id
            else None,
        },
    )


def _require_final(protocol: Protocol) -> None:
    if protocol.status != "final":
        raise ConflictError(
            "Only a final protocol can be marked as approved.", code=PROTOCOL_NOT_FINAL
        )


def _write(
    protocol: Protocol, *, at: datetime | None, meeting_id: UUID | None, by: str | None
) -> None:
    """Write the three columns of the mark."""
    for attr, value in (
        ("approved_at", at),
        ("approved_meeting_id", meeting_id),
        ("approved_by", by),
    ):
        setattr(protocol, attr, value)


async def approve(
    session: AsyncSession,
    protocol: Protocol,
    meeting_id: UUID,
    *,
    now: datetime,
    actor: str,
) -> None:
    """Mark a final protocol as approved by ``meeting_id``. The caller commits.

    Raises:
        ConflictError: The protocol is not final (409 ``protocol_not_final``).
        ValidationProblem: The meeting does not exist, belongs to another Gremium or
            is the meeting of the protocol itself (422 ``invalid_approval_meeting``).
    """
    _require_final(protocol)
    meeting = await session.get(Meeting, meeting_id)
    if (
        meeting is None
        or meeting.gremium_id != protocol.gremium_id
        or meeting.id == protocol.meeting_id
    ):
        raise ValidationProblem(
            "The approving meeting is another meeting of the same Gremium.",
            code=INVALID_APPROVAL_MEETING,
            errors=[{"field": "meetingId", "msg": "another meeting of the same gremium"}],
        )
    _write(protocol, at=now, meeting_id=meeting.id, by=actor)
    await session.flush()
    await _audit(session, protocol, actor)


async def unapprove(session: AsyncSession, protocol: Protocol, *, actor: str) -> None:
    """Remove the approval mark. Without a mark the call changes nothing."""
    if protocol.approved_at is None:
        return
    _write(protocol, at=None, meeting_id=None, by=None)
    await session.flush()
    await _audit(session, protocol, actor)
