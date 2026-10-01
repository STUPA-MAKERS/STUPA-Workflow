"""Meeting lifecycle: create, patch (planned to live to closed), broadcast, delete.

The status runs only forward: ``planned`` to ``live`` to ``closed`` (F9, O13). A
repeat of the current status is a no-op. Every other change gives 409
``invalid_status_transition``. A meeting that does not take place is deleted, not
closed.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.modules.admin.gremium_roles import gremium_member_ids
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.livevote.models import Meeting, MeetingAgendaItem
from app.modules.livevote.schemas import MeetingCreate, MeetingOut, MeetingPatch
from app.modules.livevote.service.permissions import PermissionOps
from app.modules.livevote.service.votes import VoteReadOps
from app.modules.voting.models import Vote
from app.shared.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)

logger = logging.getLogger(__name__)

# The only status changes of a meeting (F9, O13). A repeat of the current status is a
# no-op and not in this set.
_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {("planned", "live"), ("live", "closed")}
)

# The planning fields that MEETING_UPDATE records, as (model attribute, JSON key).
_AUDITED_FIELDS: tuple[tuple[str, str], ...] = (
    ("status", "status"),
    ("date", "date"),
    ("start_time", "startTime"),
    ("end_time", "endTime"),
    ("protokollant_id", "protokollantId"),
)


def _snapshot(meeting: Meeting) -> dict[str, str | None]:
    """Return the audited planning values of a meeting as JSON-safe strings."""
    out: dict[str, str | None] = {}
    for attr, key in _AUDITED_FIELDS:
        value: Any = getattr(meeting, attr)
        out[key] = None if value is None else str(value)
    return out


class LifecycleOps(PermissionOps, VoteReadOps):
    """Create/patch/delete meetings and broadcast state changes."""

    async def create(self, payload: MeetingCreate, principal: Principal) -> MeetingOut:
        """Create a meeting in status ``planned``.

        Only a meeting manager (``session.manage``) may create a meeting.
        """
        if not await self.can_manage(payload.gremium_id, principal):
            raise ForbiddenError("not allowed to create meetings for this committee")
        protokollant_id = await self._resolve_protokollant(
            payload.gremium_id, payload.protokollant_id
        )
        meeting = Meeting(
            gremium_id=payload.gremium_id,
            title=payload.title,
            date=payload.date,
            start_time=payload.start_time,
            end_time=payload.end_time,
            status="planned",
            created_by=principal.sub,
            protokollant_id=protokollant_id,
        )
        self.session.add(meeting)
        await self.session.flush()
        await audit_record(
            self.session,
            actor=principal.sub,
            action=AuditAction.MEETING_CREATE,
            target_type="meeting",
            target_id=str(meeting.id),
            data={"gremiumId": str(meeting.gremium_id), **_snapshot(meeting)},
        )
        await self.session.commit()
        return await self._emit(meeting, principal)

    async def _resolve_protokollant(
        self, gremium_id: UUID, protokollant_id: UUID | None
    ) -> UUID | None:
        """Validate the protokollant as an active member of the Gremium."""
        if protokollant_id is None:
            return None
        row = await self.session.get(PrincipalRow, protokollant_id)
        if row is None:
            raise NotFoundError(f"principal {protokollant_id} not found")
        if gremium_id not in await gremium_member_ids(self.session, row.sub):
            raise ForbiddenError("protokollant must be an active member of the committee")
        return protokollant_id

    async def patch(
        self, meeting_id: UUID, payload: MeetingPatch, principal: Principal
    ) -> MeetingOut:
        """Apply control and planning changes, then broadcast ``meeting_state``.

        RBAC works per field. Status and active application need ``canWrite``
        (protokollant or manager). Date, time and the protokollant assignment need
        ``canManage`` (meeting manager).

        The start (``planned`` to ``live``) sets ``started_at`` once. The close (``live``
        to ``closed``) sets ``closed_at`` and cancels the draft votes of the meeting in
        the same transaction, then sends ``vote_cancelled`` after the commit. A status
        change or a planning change writes ``meeting_update`` (F12).

        Raises:
            ConflictError: The status change is not ``planned`` to ``live`` or ``live``
                to ``closed`` (``invalid_status_transition``), the meeting still has an
                open vote on close (``open_vote``), the start has no protokollant, or
                the meeting is closed and the patch changes its planning.
        """
        meeting = await self._get(meeting_id)
        wants_manage = (
            "date" in payload.model_fields_set
            or "start_time" in payload.model_fields_set
            or "end_time" in payload.model_fields_set
            or "protokollant_id" in payload.model_fields_set
        )
        wants_write = payload.status is not None or payload.active_application_id is not None
        wants_now = "current_agenda_item_id" in payload.model_fields_set
        if wants_manage and not await self.can_manage(meeting.gremium_id, principal):
            raise ForbiddenError("only a session manager may plan this meeting")
        if wants_write and not await self.can_write(meeting, principal):
            raise ForbiddenError("not allowed to control this meeting")
        # The protokollant leads the room. The session lead may take over or override.
        if wants_now and not await self.can_manage_votes(meeting, principal):
            raise ForbiddenError("not allowed to set the current agenda item")
        if wants_now and meeting.status == "closed":
            raise ConflictError("the session is closed — it has no current agenda item")
        if wants_now and payload.current_agenda_item_id is not None:
            owner = await self.session.scalar(
                select(MeetingAgendaItem.meeting_id).where(
                    MeetingAgendaItem.id == payload.current_agenda_item_id
                )
            )
            if owner != meeting.id:
                raise NotFoundError(
                    f"agenda item {payload.current_agenda_item_id} not found in this meeting"
                )

        # The status runs only forward (F9, O13): planned to live, live to closed. A
        # repeat of the current status is a no-op. ``closed`` is terminal, and a
        # meeting that does not take place is deleted, not closed.
        status_change = payload.status is not None and payload.status != meeting.status
        if status_change and (meeting.status, payload.status) not in _TRANSITIONS:
            raise ConflictError(
                f"a meeting cannot change from {meeting.status} to {payload.status}; "
                "the status runs planned, live, closed",
                code="invalid_status_transition",
            )
        closing = status_change and payload.status == "closed"
        # O12: a meeting with an open vote does not close. The lead closes or cancels
        # the vote first.
        if closing and await self.open_vote(meeting.id) is not None:
            raise ConflictError(
                "a vote of this meeting is still open — close or cancel it first",
                code="open_vote",
            )

        # A closed meeting is frozen: date, time and protokollant stay immutable,
        # because the protocol refers to this planning data.
        if meeting.status == "closed" and wants_manage:
            raise ConflictError("the session is closed — its settings can no longer be changed")

        before = _snapshot(meeting)
        # planned to live: the router creates the protocol at meeting start, after this
        # commit, and nobody takes minutes or votes before that. ``meeting.status`` is
        # set only AFTER the protokollant check, which keeps the change atomic: no
        # ``live`` without a protokollant, not even in memory on a rejected patch.
        going_live = status_change and payload.status == "live"
        if payload.active_application_id is not None:
            meeting.active_application_id = payload.active_application_id
        if wants_now:
            meeting.current_agenda_item_id = payload.current_agenda_item_id
        if "date" in payload.model_fields_set:
            meeting.date = payload.date
        if "start_time" in payload.model_fields_set:
            meeting.start_time = payload.start_time
        if "end_time" in payload.model_fields_set:
            meeting.end_time = payload.end_time
        # The end time must be after the start time. The schema checks this only on
        # create. The service checks it only on a patch that touches a time, so a
        # pure status or protokollant patch never fails here.
        if (
            ("start_time" in payload.model_fields_set or "end_time" in payload.model_fields_set)
            and meeting.start_time is not None
            and meeting.end_time is not None
            and meeting.end_time <= meeting.start_time
        ):
            raise BadRequestError("endTime must be after startTime")
        if "protokollant_id" in payload.model_fields_set:
            # After the finalization the protokollant is part of the signed
            # document, so the assignment is locked.
            if await self._protocol_final(meeting.id):
                raise ConflictError("protocol is finalized — the protokollant can no longer change")
            meeting.protokollant_id = await self._resolve_protokollant(
                meeting.gremium_id, payload.protokollant_id
            )
        # A meeting needs a protokollant before it goes live. The protokollant
        # writes the protocol that the start creates.
        if going_live and meeting.protokollant_id is None:
            raise ConflictError("assign a protokollant before starting the meeting")
        now = datetime.now(UTC)
        cancelled: list[Vote] = []
        if going_live and meeting.started_at is None:
            # Z7: the real start, set once. The protocol header and the UI read it.
            meeting.started_at = now
        if closing:
            # Set the close timestamp once, on the transition to ``closed``. It
            # fills the "end" line of the protocol title page.
            meeting.closed_at = now
            # A draft of a closed meeting can never open (O12). Local import: the
            # voting service imports the flow engine, which reaches back into this
            # module.
            from app.modules.voting.service import VotingService

            cancelled = await VotingService(self.session).cancel_drafts_for_meeting(
                meeting.id, now=now, actor=principal.sub
            )
        if payload.status is not None:
            meeting.status = payload.status
        after = _snapshot(meeting)
        changes = {
            key: {"from": before[key], "to": after[key]}
            for key in after
            if before[key] != after[key]
        }
        if changes:
            await audit_record(
                self.session,
                actor=principal.sub,
                action=AuditAction.MEETING_UPDATE,
                target_type="meeting",
                target_id=str(meeting.id),
                data={"gremiumId": str(meeting.gremium_id), "changes": changes},
            )
        await self.session.flush()
        await self.session.commit()
        await self._publish_cancelled(cancelled)
        votes = (await self._votes_for([meeting.id], principal)).get(meeting.id, [])
        out = await self._emit(meeting, principal, votes=votes)
        if self.publisher is not None:
            await self.publisher.meeting_state(out)
        return out

    async def _publish_cancelled(self, votes: list[Vote]) -> None:
        """Send ``vote_cancelled`` for the drafts that the close cancelled.

        The method runs after the commit. A broker fault must not fail the committed
        close, so the method only logs it.
        """
        if self.publisher is None or not votes:
            return
        from app.modules.voting.service import VotingService

        voting = VotingService(self.session)
        for vote in votes:
            try:
                await self.publisher.vote_cancelled(await voting.get(vote.id))
            except Exception:  # noqa: BLE001 - the broadcast is best effort
                logger.warning("vote_cancelled broadcast failed (vote=%s)", vote.id)

    async def broadcast_state(self, meeting_id: UUID, principal: Principal) -> None:
        """Re-send ``meeting_state`` without a state change.

        A protocol edit or an agenda-item edit calls this, so live followers reload
        the new state.
        """
        meeting = await self._get(meeting_id)
        votes = (await self._votes_for([meeting.id])).get(meeting.id, [])
        out = await self._emit(meeting, principal, votes=votes)
        if self.publisher is not None:
            await self.publisher.meeting_state(out)

    async def _protocol_final(self, meeting_id: UUID) -> bool:
        """Report whether the protocol of the meeting is final."""
        # Local import: ``protocol`` depends on ``livevote``. A module-level import
        # would cycle.
        from app.modules.protocol.models import Protocol

        status = await self.session.scalar(
            select(Protocol.status).where(Protocol.meeting_id == meeting_id)
        )
        return status == "final"

    async def delete(self, meeting_id: UUID, principal: Principal) -> None:
        """Delete a meeting.

        Only a meeting manager (``session.manage``) or an admin may delete a
        meeting. A meeting with a final protocol also needs the global
        ``meeting.delete_finalized`` permission, because the protocol is a signed
        and mailed document. The service audits every delete.

        The cascade removes the protocol, the agenda and the attendance. The
        database detaches bound votes with ``SET NULL`` on ``meeting_id`` and on
        ``agenda_item_id`` (F21), so the votes, their ballots and their results
        survive.
        """
        meeting = await self._get(meeting_id)
        if not await self.can_manage(meeting.gremium_id, principal):
            raise ForbiddenError("not allowed to delete this meeting")
        finalized = await self._protocol_final(meeting_id)
        if finalized and not principal.has("meeting.delete_finalized"):
            raise ForbiddenError(
                "this meeting has a finalized protocol — deleting it requires "
                "the meeting.delete_finalized permission"
            )
        await audit_record(
            self.session,
            actor=principal.sub,
            action=AuditAction.MEETING_DELETE,
            target_type="meeting",
            target_id=str(meeting.id),
            data={
                "title": meeting.title,
                "gremiumId": str(meeting.gremium_id),
                "finalizedProtocol": finalized,
            },
        )
        await self.session.delete(meeting)
        await self.session.commit()
