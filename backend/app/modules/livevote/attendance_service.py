"""Attendance service for a meeting.

The roster of a meeting holds the members whose membership overlaps the meeting
window, plus each principal with an attendance record for the meeting (see
`app.modules.livevote.roster`). A closed meeting thus keeps its attendance, also
when a membership ended later or the OIDC sync removed it. A change of the
attendance needs a membership that is valid now. Each pair of meeting and member
has exactly one record. The unique constraint drives the upsert.

The rules (Z2, O15, O23, F12):

- A member reports the own attendance (`source='self'`) as `present` or
  `excused` only, while the meeting is `planned` or `live`.
- The meeting lead (`canWrite`) sets the attendance of any member
  (`source='lead'`), `absent` included. A record that the lead set wins: the
  member cannot change it any more (409 `attendance_set_by_lead`) until the lead
  resets it to "open" with a delete of the record.
- Nobody can set a member `present` while a delegation of that member for the
  meeting exists (409 `delegation_active`): not the lead, and not the member
  with the own report. The delegation must be revoked first. The delegator can
  revoke it only before the meeting start. During the live meeting, the meeting
  lead (`can_manage`) can revoke it, for example a substitution that the lead
  entered for a missing member (O6). An admin can revoke it at any time.
- `note` is the reason of an excuse and is personal data. Only the member and
  the lead see it. The lead's set and reset write `attendance_set` and
  `attendance_reset` to the audit log, never with the note.
- A closed meeting freezes the attendance (409), because the protocol carries it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import GremiumMembership
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.delegations.models import MeetingDelegation
from app.modules.delegations.pool import group_names_for
from app.modules.livevote.keepers import keeper_principal_ids
from app.modules.livevote.models import Meeting, MeetingAttendance
from app.modules.livevote.roster import meeting_roster_filter
from app.modules.livevote.schemas import (
    AttendanceOut,
    AttendanceStatus,
    MeetingMemberOut,
    SelfAttendanceStatus,
)
from app.settings import get_settings
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError

_DELEGATION_ACTIVE = (
    "The member delegated for this meeting. Revoke the delegation first. After the"
    " meeting start, the meeting lead can revoke it while the meeting is live, and"
    " an admin at any time."
)


def _resolve_note(
    status: str,
    *,
    existing: MeetingAttendance | None,
    note: str | None,
    replace_note: bool,
) -> str | None:
    """Return the note to store with `status`.

    Only an excuse has a reason. Any other status drops it. An excuse keeps the
    stored reason unless the caller gives a new one (`replace_note`).
    """
    if status != "excused":
        return None
    if replace_note:
        return note
    return existing.note if existing is not None else None


class AttendanceService:
    """Read the roster of a meeting and change the attendance records."""

    def __init__(self, session: AsyncSession, *, tz_name: str | None = None) -> None:
        self.session = session
        self._tz_name = tz_name

    @property
    def tz_name(self) -> str:
        """Return the local time zone of the planned meeting start."""
        return self._tz_name or get_settings().local_timezone

    async def _meeting(self, meeting_id: UUID, *, for_write: bool = False) -> Meeting:
        """Load a meeting by id.

        `for_write` takes a share lock on the meeting row and reads the current
        values again. A status change locks the row for update, so a close and an
        attendance change run one after the other, and a change cannot slip in
        after the close.

        Raises:
            NotFoundError: No meeting has this id.
        """
        stmt = select(Meeting).where(Meeting.id == meeting_id)
        if for_write:
            stmt = stmt.with_for_update(read=True).execution_options(populate_existing=True)
        meeting = (await self.session.execute(stmt)).scalar_one_or_none()
        if meeting is None:
            raise NotFoundError(f"meeting {meeting_id} not found")
        return meeting

    async def _current_members(self, gremium_id: UUID) -> list[PrincipalRow]:
        """Return each current member of the Gremium once.

        A membership counts when its term window is valid now.
        """
        now = datetime.now(UTC)
        rows = (
            (
                await self.session.execute(
                    select(PrincipalRow)
                    .join(
                        GremiumMembership,
                        GremiumMembership.principal_id == PrincipalRow.id,
                    )
                    .where(
                        GremiumMembership.gremium_id == gremium_id,
                        (GremiumMembership.valid_from.is_(None))
                        | (GremiumMembership.valid_from <= now),
                        (GremiumMembership.valid_until.is_(None))
                        | (GremiumMembership.valid_until > now),
                    )
                    .order_by(PrincipalRow.display_name)
                    .distinct()
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    async def members(self, gremium_id: UUID) -> list[MeetingMemberOut]:
        """Return the current Gremium members as Protokollant candidates.

        `canKeepProtocol` marks the members with `protocol.write` (O20). Only they
        can keep the minutes. `substituteGroupName` names the faculty group of the
        member (A8).
        """
        members = await self._current_members(gremium_id)
        keepers = await keeper_principal_ids(self.session, gremium_id)
        groups = await group_names_for(self.session, gremium_id, (m.id for m in members))
        return [
            MeetingMemberOut(
                principalId=m.id,
                displayName=m.display_name,
                email=m.email,
                canKeepProtocol=m.id in keepers,
                substituteGroupName=groups.get(m.id),
            )
            for m in members
        ]

    async def roster(
        self, meeting_id: UUID, requester_sub: str, *, can_write: bool = False
    ) -> list[AttendanceOut]:
        """Return the members with the attendance they have for this meeting.

        The list holds the members whose membership overlaps the meeting window,
        plus each principal with a record for the meeting. A closed meeting thus
        does not depend on the memberships that are valid now. A member without
        a record gets `status` and `source` as `None`. The `note` goes only to
        the member and to the meeting lead (`can_write`). `canKeepProtocol` marks
        the members who can keep the minutes now (O20), for the keeper picker and
        the handover. `substituteGroupName` names the faculty group of the member
        (A8).
        """
        meeting = await self._meeting(meeting_id)
        members = list(
            (
                await self.session.execute(
                    select(PrincipalRow)
                    .where(meeting_roster_filter(meeting, self.tz_name))
                    .order_by(PrincipalRow.display_name, PrincipalRow.id)
                )
            )
            .scalars()
            .all()
        )
        records = (
            (
                await self.session.execute(
                    select(MeetingAttendance).where(MeetingAttendance.meeting_id == meeting_id)
                )
            )
            .scalars()
            .all()
        )
        by_principal = {r.principal_id: r for r in records}
        keepers = await keeper_principal_ids(self.session, meeting.gremium_id)
        groups = await group_names_for(
            self.session, meeting.gremium_id, (m.id for m in members)
        )
        out: list[AttendanceOut] = []
        for m in members:
            rec = by_principal.get(m.id)
            is_self = m.sub == requester_sub
            out.append(
                AttendanceOut(
                    principalId=m.id,
                    displayName=m.display_name,
                    email=m.email,
                    status=rec.status if rec else None,  # type: ignore[arg-type]
                    source=rec.source if rec else None,  # type: ignore[arg-type]
                    note=rec.note if rec and (is_self or can_write) else None,
                    isSelf=is_self,
                    canKeepProtocol=m.id in keepers,
                    substituteGroupName=groups.get(m.id),
                )
            )
        return out

    async def _record(self, meeting_id: UUID, principal_id: UUID) -> MeetingAttendance | None:
        """Load the record of one member with a row lock.

        The lock orders a self report and a lead change of the same record, so
        the O15 check and the write see the same row.
        """
        return (
            await self.session.execute(
                select(MeetingAttendance)
                .where(
                    MeetingAttendance.meeting_id == meeting_id,
                    MeetingAttendance.principal_id == principal_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()

    def _write(
        self,
        existing: MeetingAttendance | None,
        *,
        meeting_id: UUID,
        principal_id: UUID,
        status: str,
        source: str,
        note: str | None,
    ) -> None:
        if existing is None:
            self.session.add(
                MeetingAttendance(
                    meeting_id=meeting_id,
                    principal_id=principal_id,
                    status=status,
                    source=source,
                    note=note,
                )
            )
        else:
            existing.status = status
            existing.source = source
            existing.note = note

    async def _flush_write(self) -> None:
        """Flush an attendance write. A parallel first write gives 409, not 500.

        `_record` locks an existing row only. When no row exists, a self report and
        a lead set of the same member can both insert one, and the unique constraint
        refuses the second insert. The caller then loads the roster again.

        Raises:
            ConflictError: A parallel change wrote the record first (409).
        """
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(
                "Another change of this attendance ran at the same time. Try again.",
                code="conflict",
            ) from exc

    @staticmethod
    def _ensure_not_closed(meeting: Meeting) -> None:
        """Refuse a change when the meeting is closed.

        The finalized protocol carries the attendance list. A later change would
        make the PDF and the system disagree.

        Raises:
            ConflictError: The meeting is closed. The API answers 409.
        """
        if meeting.status == "closed":
            raise ConflictError(
                "Attendance is read-only once the meeting is closed.", code="conflict"
            )

    async def _audit(
        self,
        action: AuditAction,
        *,
        actor: str,
        meeting_id: UUID,
        principal_id: UUID,
        **extra: Any,
    ) -> None:
        """Write one attendance audit entry, never with the note."""
        await audit_record(
            self.session,
            actor=actor,
            action=action,
            target_type="meeting",
            target_id=str(meeting_id),
            data={"principalId": str(principal_id), **extra},
        )

    async def set_self(
        self,
        meeting_id: UUID,
        status: SelfAttendanceStatus,
        requester_sub: str,
        *,
        note: str | None = None,
        replace_note: bool = False,
        can_write: bool = False,
    ) -> list[AttendanceOut]:
        """Report the own attendance of the requester (Z2).

        `present` is refused while the member has a delegation for the meeting
        (O23), as for the lead. Else the member counts as present but stays
        blocked from the vote.

        Raises:
            ForbiddenError: The requester is not a current member of the Gremium.
            ConflictError: The meeting is closed, the meeting lead set the record
                (O15, code `attendance_set_by_lead`), the status is `present` while
                a delegation of the member exists (O23, code `delegation_active`),
                or a parallel change wrote the record first (code `conflict`).
        """
        meeting = await self._meeting(meeting_id, for_write=True)
        self._ensure_not_closed(meeting)
        member = next(
            (m for m in await self._current_members(meeting.gremium_id) if m.sub == requester_sub),
            None,
        )
        if member is None:
            raise ForbiddenError("only committee members can mark their attendance")
        existing = await self._record(meeting_id, member.id)
        if existing is not None and existing.source == "lead":
            raise ConflictError(
                "The meeting lead set this attendance. Only the lead can change it.",
                code="attendance_set_by_lead",
            )
        if status == "present" and await self._has_delegation(meeting_id, member.id):
            raise ConflictError(_DELEGATION_ACTIVE, code="delegation_active")
        self._write(
            existing,
            meeting_id=meeting_id,
            principal_id=member.id,
            status=status,
            source="self",
            note=_resolve_note(status, existing=existing, note=note, replace_note=replace_note),
        )
        await self._flush_write()
        await self.session.commit()
        return await self.roster(meeting_id, requester_sub, can_write=can_write)

    async def _has_delegation(self, meeting_id: UUID, principal_id: UUID) -> bool:
        """Return True when the member delegated for this meeting (O23)."""
        found = (
            await self.session.execute(
                select(MeetingDelegation.id).where(
                    MeetingDelegation.meeting_id == meeting_id,
                    MeetingDelegation.delegator_principal_id == principal_id,
                )
            )
        ).first()
        return found is not None

    async def set_for(
        self,
        meeting_id: UUID,
        principal_id: UUID,
        status: AttendanceStatus,
        requester_sub: str,
        *,
        note: str | None = None,
        replace_note: bool = False,
    ) -> list[AttendanceOut]:
        """Set the attendance of a member as the meeting lead.

        The router checks `canWrite` before the call. The change writes
        `attendance_set` with the status before and after it.

        Raises:
            NotFoundError: The principal is not a current member of the Gremium.
            ConflictError: The meeting is closed, the status is `present` while a
                delegation of the member exists (O23, code `delegation_active`), or
                a parallel change wrote the record first (code `conflict`).
        """
        meeting = await self._meeting(meeting_id, for_write=True)
        self._ensure_not_closed(meeting)
        members = await self._current_members(meeting.gremium_id)
        if not any(m.id == principal_id for m in members):
            raise NotFoundError("principal is not a current member of this committee")
        if status == "present" and await self._has_delegation(meeting_id, principal_id):
            raise ConflictError(_DELEGATION_ACTIVE, code="delegation_active")
        existing = await self._record(meeting_id, principal_id)
        before = existing.status if existing is not None else None
        before_source = existing.source if existing is not None else None
        self._write(
            existing,
            meeting_id=meeting_id,
            principal_id=principal_id,
            status=status,
            source="lead",
            note=_resolve_note(status, existing=existing, note=note, replace_note=replace_note),
        )
        await self._flush_write()
        await self._audit(
            AuditAction.ATTENDANCE_SET,
            actor=requester_sub,
            meeting_id=meeting_id,
            principal_id=principal_id,
            status={"from": before, "to": status},
            source={"from": before_source, "to": "lead"},
        )
        await self.session.commit()
        return await self.roster(meeting_id, requester_sub, can_write=True)

    async def reset(
        self, meeting_id: UUID, principal_id: UUID, requester_sub: str
    ) -> list[AttendanceOut]:
        """Reset the attendance of a member to "open" as the meeting lead.

        The call deletes the record, so the member can report again. It writes
        `attendance_reset`. Without a record the call changes nothing and writes
        no audit entry. The router checks `canWrite` before the call.

        Raises:
            ConflictError: The meeting is closed.
        """
        meeting = await self._meeting(meeting_id, for_write=True)
        self._ensure_not_closed(meeting)
        existing = await self._record(meeting_id, principal_id)
        if existing is not None:
            await self._audit(
                AuditAction.ATTENDANCE_RESET,
                actor=requester_sub,
                meeting_id=meeting_id,
                principal_id=principal_id,
                status={"from": existing.status, "to": None},
                source={"from": existing.source, "to": None},
            )
            await self.session.delete(existing)
            await self.session.flush()
            await self.session.commit()
        return await self.roster(meeting_id, requester_sub, can_write=True)
