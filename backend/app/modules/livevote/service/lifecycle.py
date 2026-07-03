"""Meeting lifecycle: create, patch (planned to live to closed), broadcast, delete."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.modules.admin.gremium_roles import gremium_member_ids
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.livevote.models import Meeting
from app.modules.livevote.schemas import MeetingCreate, MeetingOut, MeetingPatch
from app.modules.livevote.service.permissions import PermissionOps
from app.modules.livevote.service.votes import VoteReadOps
from app.shared.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)


class LifecycleOps(PermissionOps, VoteReadOps):
    """Create/patch/delete meetings and broadcast state changes."""

    async def create(self, payload: MeetingCreate, principal: Principal) -> MeetingOut:
        """Create a meeting (``planned``) — session managers (``session.manage``) only."""
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
        await self.session.commit()
        return await self._emit(meeting, principal)

    async def _resolve_protokollant(
        self, gremium_id: UUID, protokollant_id: UUID | None
    ) -> UUID | None:
        """Validate the protokollant: must be an active member of the committee."""
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
        """Apply control/planning changes + broadcast ``meeting_state``.

        Field-level RBAC: status/active application requires ``canWrite``
        (protokollant or manager); date/time/protokollant assignment requires
        ``canManage`` (session manager)."""
        meeting = await self._get(meeting_id)
        wants_manage = (
            "date" in payload.model_fields_set
            or "start_time" in payload.model_fields_set
            or "end_time" in payload.model_fields_set
            or "protokollant_id" in payload.model_fields_set
        )
        wants_write = payload.status is not None or payload.active_application_id is not None
        if wants_manage and not await self.can_manage(meeting.gremium_id, principal):
            raise ForbiddenError("only a session manager may plan this meeting")
        if wants_write and not await self.can_write(meeting, principal):
            raise ForbiddenError("not allowed to control this meeting")

        # ``closed`` is terminal: a closed meeting cannot be reopened (no
        # closed->live/planned). Repeating ``closed`` is a no-op.
        if meeting.status == "closed" and payload.status is not None and payload.status != "closed":
            raise ConflictError("a closed session cannot be re-opened")

        # Closed = frozen: date/time/protokollant are immutable afterwards — the
        # protocol references these planning data.
        if meeting.status == "closed" and wants_manage:
            raise ConflictError("the session is closed — its settings can no longer be changed")

        # planned->live: the protocol is created only at meeting start (by the router
        # after this commit) — no minuting/voting before. ``meeting.status`` is set
        # only AFTER the protokollant check (atomic: no ``live`` without a
        # protokollant, not even in-memory on a rejected patch).
        going_live = payload.status == "live" and meeting.status != "live"
        if payload.active_application_id is not None:
            meeting.active_application_id = payload.active_application_id
        if "date" in payload.model_fields_set:
            meeting.date = payload.date
        if "start_time" in payload.model_fields_set:
            meeting.start_time = payload.start_time
        if "end_time" in payload.model_fields_set:
            meeting.end_time = payload.end_time
        # End time must be after start time (the schema only checks create). Enforced
        # only on time-touching patches so a pure status/protokollant patch never
        # fails on it.
        if (
            ("start_time" in payload.model_fields_set or "end_time" in payload.model_fields_set)
            and meeting.start_time is not None
            and meeting.end_time is not None
            and meeting.end_time <= meeting.start_time
        ):
            raise BadRequestError("endTime must be after startTime")
        if "protokollant_id" in payload.model_fields_set:
            # After finalization the scribe is part of the signed document — the
            # protokollant is locked.
            if await self._protocol_final(meeting.id):
                raise ConflictError("protocol is finalized — the protokollant can no longer change")
            meeting.protokollant_id = await self._resolve_protokollant(
                meeting.gremium_id, payload.protokollant_id
            )
        # A protokollant must be set before going live — they are the scribe of the
        # protocol created at start.
        if going_live and meeting.protokollant_id is None:
            raise ConflictError("assign a protokollant before starting the meeting")
        if payload.status is not None:
            # Close timestamp: set once on the transition to ``closed`` — the "end"
            # line of the protocol title page.
            if payload.status == "closed" and meeting.status != "closed":
                meeting.closed_at = datetime.now(UTC)
            meeting.status = payload.status
        await self.session.flush()
        await self.session.commit()
        votes = (await self._votes_for([meeting.id])).get(meeting.id, [])
        out = await self._emit(meeting, principal, votes=votes)
        if self.publisher is not None:
            await self.publisher.meeting_state(out)
        return out

    async def broadcast_state(self, meeting_id: UUID, principal: Principal) -> None:
        """Re-send ``meeting_state`` without a state change — e.g. after a
        protocol/TOP edit so live followers reload the new state."""
        meeting = await self._get(meeting_id)
        votes = (await self._votes_for([meeting.id])).get(meeting.id, [])
        out = await self._emit(meeting, principal, votes=votes)
        if self.publisher is not None:
            await self.publisher.meeting_state(out)

    async def _protocol_final(self, meeting_id: UUID) -> bool:
        """Whether the meeting has a FINALIZED protocol."""
        # Local import: protocol depends on livevote — module level would cycle.
        from app.modules.protocol.models import Protocol

        status = await self.session.scalar(
            select(Protocol.status).where(Protocol.meeting_id == meeting_id)
        )
        return status == "final"

    async def delete(self, meeting_id: UUID, principal: Principal) -> None:
        """Delete a meeting — session managers (``session.manage``)/admin only.

        A meeting with a FINALIZED protocol additionally requires the global
        ``meeting.delete_finalized`` permission — the protocol is a signed, mailed
        document. Every delete is audited.

        Cascade removes protocol/agenda/attendance; bound votes are detached via
        ``SET NULL`` (results survive)."""
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
