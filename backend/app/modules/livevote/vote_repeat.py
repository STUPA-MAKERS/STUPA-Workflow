"""The repeat of a closed meeting vote ("erneut abstimmen").

A meeting can vote again on the same agenda item after a vote closed, for example
after a mistake in the room. The new vote names the closed vote in ``repeat_of_id``
and counts on in ``attempt``. The closed vote keeps its result, so the protocol shows
both votes and marks the first one as repeated.

A vote on an application fired the pass or fail branch at its close. Before the repeat
opens, ``reopen_application`` moves the application back into the vote state that the
closed vote decided, through the same path as an audit-log revert: a status event with
the note ``vote:repeat``, a ``status_change`` audit entry, and the decision of the
closed vote gives way to the decision before it. The close of the repeat fires the
branch again. The move back works only while the application still sits in the state
that the closed vote put it in, because a later change (for example a payment) is not
undone by a repeat.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Application, StatusEvent
from app.modules.audit.actions import AuditAction
from app.modules.audit.models import AuditEntry
from app.modules.flow.models import State
from app.modules.flow.service import FlowService
from app.modules.voting.models import Vote
from app.shared.errors import ConflictError, NotFoundError

#: The note of the status event that moves an application back for a repeat.
REPEAT_NOTE = "vote:repeat"


async def repeat_source(
    session: AsyncSession, meeting_id: UUID, item_id: UUID, repeat_of: UUID
) -> Vote:
    """Load the closed vote that a new vote repeats, and check that it can repeat.

    The vote must be a closed vote of this meeting on this agenda item. Only one repeat
    of a vote exists at a time (a cancelled repeat does not count), and no other vote
    of the item may be prepared or open, so the room never runs two votes on one
    question.

    Raises:
        NotFoundError: The meeting has no such vote on this agenda item.
        ConflictError: The vote is not closed (``vote_not_closed``), it already has a
            repeat (``repeat_exists``), or the item has a prepared or open vote
            (``vote_pending``).
    """
    source = (
        await session.execute(
            select(Vote).where(
                Vote.id == repeat_of,
                Vote.meeting_id == meeting_id,
                Vote.agenda_item_id == item_id,
            )
        )
    ).scalar_one_or_none()
    if source is None:
        raise NotFoundError(f"vote {repeat_of} not found on this agenda item")
    if source.status != "closed":
        raise ConflictError(
            "Only a closed vote can be repeated.", code="vote_not_closed"
        )
    others = (
        await session.execute(
            select(Vote.status, Vote.repeat_of_id).where(
                Vote.agenda_item_id == item_id,
                Vote.id != source.id,
                Vote.status != "cancelled",
            )
        )
    ).all()
    if any(row.repeat_of_id == source.id for row in others):
        raise ConflictError("This vote already has a repeat.", code="repeat_exists")
    if any(row.status in ("draft", "open") for row in others):
        raise ConflictError(
            "The agenda item has a prepared or open vote; finish it first.",
            code="vote_pending",
        )
    return source


async def _branch_event(session: AsyncSession, vote_id: UUID) -> StatusEvent | None:
    """Return the newest status event that the close of the vote fired, or None."""
    return (
        await session.execute(
            select(StatusEvent)
            .where(StatusEvent.vote_id == vote_id)
            .order_by(StatusEvent.at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _state_kind(session: AsyncSession, application_id: UUID) -> str | None:
    """Return the kind of the current state of the application."""
    return await session.scalar(
        select(State.kind)
        .join(Application, Application.current_state_id == State.id)
        .where(Application.id == application_id)
    )


async def assert_reopenable(session: AsyncSession, source: Vote) -> StatusEvent | None:
    """Check that the application of a repeated vote can go back to its vote state.

    Returns:
        The status event to undo, or None when the application is still in a vote
        state (the branch of the closed vote was blocked, or an earlier repeat moved
        it back already).

    Raises:
        ConflictError: The application moved on after the close of the vote
            (``application_moved_on``).
    """
    if source.application_id is None:
        return None
    if await _state_kind(session, source.application_id) == "vote":
        return None
    current = await session.scalar(
        select(Application.current_state_id).where(Application.id == source.application_id)
    )
    event = await _branch_event(session, source.id)
    if event is None or event.to_state_id != current or event.from_state_id is None:
        raise ConflictError(
            "The application changed its status after the vote; a repeat cannot "
            "take it back.",
            code="application_moved_on",
        )
    return event


async def reopen_application(session: AsyncSession, source: Vote, *, actor: str) -> None:
    """Move the application of a repeated vote back into its vote state (commits).

    Nothing happens for a vote without an application or an application that is still
    in a vote state.

    Raises:
        ConflictError: The application moved on after the close of the vote
            (``application_moved_on``), or a concurrent change won (``stale_revert``).
    """
    event = await assert_reopenable(session, source)
    if event is None or source.application_id is None or event.from_state_id is None:
        return
    audit_id = await session.scalar(
        select(AuditEntry.id)
        .where(
            AuditEntry.action == AuditAction.STATUS_CHANGE.value,
            AuditEntry.target_type == "application",
            AuditEntry.target_id == str(source.application_id),
            AuditEntry.data["statusEventId"].astext == str(event.id),
        )
        .order_by(AuditEntry.id.desc())
        .limit(1)
    )
    if audit_id is None:
        raise ConflictError(
            "The status change of the vote has no audit entry; a repeat cannot take it back.",
            code="application_moved_on",
        )
    await FlowService(session).revert_status(
        source.application_id,
        from_state_id=event.from_state_id,
        to_state_id=event.to_state_id,
        actor=actor,
        reverted_audit_id=audit_id,
        reverted_status_event_id=event.id,
        note=REPEAT_NOTE,
    )
