"""The way back of a repeated application vote that does not take place.

A meeting that votes again on an application first moves the application back into its
vote state (`livevote.vote_repeat.reopen_application`). The decision of the first vote
then gives way. When the open repeat is cancelled, no vote decides the application
again. This module then brings the application back to the state that
the first vote decided, with the decision of that vote, so the application and the
first vote say the same.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.decision import DecisionSwap
from app.modules.applications.models import Application, StatusEvent
from app.modules.audit.actions import AuditAction
from app.modules.audit.models import AuditEntry
from app.modules.flow.service import FlowService
from app.modules.voting.models import Vote

#: The note of the status event that moves an application back for a repeat.
REPEAT_NOTE = "vote:repeat"
#: The note of the status event that restores the decision of the repeated vote.
REPEAT_CANCELLED_NOTE = "vote:repeat-cancelled"


def _uuid_or_none(raw: object) -> UUID | None:
    """Read an id of an audit entry, or None."""
    return UUID(raw) if isinstance(raw, str) and raw else None


async def restore_repeated_decision(
    session: AsyncSession,
    application_id: UUID | None,
    repeat_of_id: UUID | None,
    *,
    actor: str,
) -> bool:
    """Bring an application back to the decision of its repeated vote (commits).

    The caller cancelled the open repeat of the vote `repeat_of_id` on this
    application. The method undoes the move back of the repeat: the application returns to
    the state that the first vote decided, and the decision of that vote is valid
    again. It does so only while the application still sits in the vote state that
    the repeat put it in, and only for a move back that came after the close of the
    repeated vote. An older move back belongs to that vote, which is itself a repeat
    and was not cancelled.

    Returns:
        True after the restore. False when the vote is no repeat, when the repeat
        never moved the application back, or when the application left that vote
        state by another way.
    """
    source = None if repeat_of_id is None else await session.get(Vote, repeat_of_id)
    if application_id is None or source is None or source.closed_at is None:
        return False
    event = (
        await session.execute(
            select(StatusEvent)
            .where(StatusEvent.application_id == application_id)
            .order_by(StatusEvent.at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    current = await session.scalar(
        select(Application.current_state_id).where(Application.id == application_id)
    )
    if (
        event is None
        or event.note != REPEAT_NOTE
        or event.to_state_id != current
        or event.from_state_id is None
        or event.at < source.closed_at
    ):
        return False
    entry = (
        await session.execute(
            select(AuditEntry)
            .where(
                AuditEntry.action == AuditAction.STATUS_CHANGE.value,
                AuditEntry.target_type == "application",
                AuditEntry.target_id == str(application_id),
                AuditEntry.data["statusEventId"].astext == str(event.id),
            )
            .order_by(AuditEntry.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if entry is None:
        return False
    data = entry.data or {}
    swap = (
        DecisionSwap(
            undone_id=_uuid_or_none(data.get("decisionRestoredId")),
            restored_id=_uuid_or_none(data.get("decisionUndoneId")),
        )
        if "decisionUndoneId" in data or "decisionRestoredId" in data
        else None
    )
    await FlowService(session).revert_status(
        application_id,
        from_state_id=event.from_state_id,
        to_state_id=event.to_state_id,
        actor=actor,
        reverted_audit_id=entry.id,
        reverted_status_event_id=event.id,
        decision_swap=swap,
        note=REPEAT_CANCELLED_NOTE,
    )
    return True
