"""Attendance service for a meeting.

The roster of a meeting holds the members of the Gremium, plus each principal
with an attendance record for the meeting, plus each delegate with the voting right
in the meeting (see `app.modules.meetings.roster`). A closed meeting thus keeps its
attendance, also when the OIDC sync removed a membership later. A change of the
attendance needs a membership or a delegation with the voting right in the meeting
(§F/meetings/delegations/003150). Each pair of meeting and person has exactly one
record. The unique constraint drives the upsert.

The rules:

- A member or a delegate reports the own attendance (`source='self'`) as `present`
  or `excused` only, while the meeting is `planned` or `live`.
- The meeting lead (`canWrite`) sets the attendance of any member and of any
  delegate (`source='lead'`), `absent` included. A record that the lead set wins: the
  member cannot change it any more (409 `attendance_set_by_lead`) until the lead
  resets it to "open" with a delete of the record.
- A check-in (`present`) of a member frees a seat that a pool substitute took
  for the member (`delegations.pool_seat`).
- A pool substitute on a seat without a record reads `present`, because a seat
  needs the live meeting. A ballot of a delegate marks the delegate present
  (§F/meetings/delegations/003152).
- Nobody can set a member `present` while another delegation of that member for
  the meeting exists (409 `delegation_active`): not the lead, and not the member
  with the own report. The delegation must be revoked first. The delegator can
  revoke it only before the meeting start. During the live meeting, the meeting
  lead (`can_manage`) can revoke it, for example a substitution that the lead
  entered for a missing member. An admin can revoke it at any time.
- `note` is the reason of an excuse and is personal data. Only the member and
  the lead see it. The lead's set and reset write `attendance_set` and
  `attendance_reset` to the audit log, never with the note.
- A closed meeting freezes the own report (409), because the protocol carries the
  attendance. The lead still sets and resets a record until the protocol is final or
  in its render (§F/meetings/meetings/000951), then 409 `protocol_final`. Such a
  change counts the present members of the meeting again. The other exception is
  the late excuse (§F/meetings/meetings/000922): until
  `lateExcuseDays` days after the close, a member changes the own `absent` to
  `excused` and must give the reason. The change writes `attendance_set` with
  `late: true`, never with the note.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.delegations.models import MeetingDelegation
from app.modules.delegations.pool_seat import release_pool_seat
from app.modules.gremien.models import GremiumMembership
from app.modules.meetings.keepers import (
    KEEPER_PERMISSION,
    VOTE_PERMISSION,
    keeper_principal_ids,
    member_permissions,
)
from app.modules.meetings.models import (
    Meeting,
    MeetingAttendance,
    MeetingSettings,
)
from app.modules.meetings.periods import kept_late_excuse_days
from app.modules.meetings.present import (
    Delegates,
    delegate_status,
    meeting_delegates,
    present_count,
)
from app.modules.meetings.protocol_models import Protocol
from app.modules.meetings.roster import meeting_roster_filter
from app.modules.meetings.schemas import (
    AttendanceOut,
    AttendanceStatus,
    MeetingMemberOut,
    RepresentedOut,
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


def late_excuse_until(meeting: Meeting, days: int) -> datetime | None:
    """Return the end of the late-excuse window of a closed meeting, else None.

    The window ends with the local day that is ``days`` days after the close, not at
    the clock time of the close: a period in days ends with its last day.
    """
    if meeting.status != "closed" or meeting.closed_at is None:
        return None
    zone = ZoneInfo(get_settings().local_timezone)
    last_day = (meeting.closed_at.astimezone(zone) + timedelta(days=days)).date()
    return datetime.combine(last_day, time(23, 59, 59), tzinfo=zone).astimezone(UTC)


def _open_window(
    rec: MeetingAttendance | None, until: datetime | None, now: datetime, *, is_self: bool
) -> datetime | None:
    """Return ``until`` for the own ``absent`` record while the window is open."""
    if not is_self or rec is None or rec.status != "absent" or until is None:
        return None
    return until if now <= until else None


_NO_DELEGATES = Delegates(represents={}, seat_holders=frozenset())


def _attendance_out(
    member: PrincipalRow,
    rec: MeetingAttendance | None,
    held: frozenset[str],
    *,
    is_self: bool,
    can_write: bool,
    late_until: datetime | None = None,
    represents: list[RepresentedOut] | None = None,
    status: str | None = None,
    is_member: bool = True,
) -> AttendanceOut:
    """Build one roster row; the note goes only to the member and to the lead.

    ``status`` is the status of the row: the record, or ``present`` for a pool seat
    without a record.
    """
    return AttendanceOut(
        lateExcuseUntil=late_until,
        principalId=member.id,
        displayName=member.display_name,
        email=member.email,
        status=status,  # type: ignore[arg-type]
        source=rec.source if rec else None,  # type: ignore[arg-type]
        note=rec.note if rec and (is_self or can_write) else None,
        isSelf=is_self,
        canKeepProtocol=KEEPER_PERMISSION in held,
        canVote=VOTE_PERMISSION in held,
        represents=represents or [],
        isMember=is_member,
    )


class AttendanceService:
    """Read the roster of a meeting and change the attendance records."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the service to a session."""
        self.session = session

    async def _meeting(self, meeting_id: UUID, *, for_write: bool = False) -> Meeting:
        """Load a meeting by id.

        `for_write` takes a share lock on the meeting row and reads the current
        values again. A status change locks the row for update, so a close and an
        attendance change run one after the other, and a change cannot slip in
        after the close.

        Raises:
            NotFoundError: No meeting has this id.
        """
        query = select(Meeting).where(Meeting.id == meeting_id)
        stmt = (
            query.with_for_update(read=True).execution_options(populate_existing=True)
            if for_write
            else query
        )
        meeting = (await self.session.execute(stmt)).scalar_one_or_none()
        if meeting is None:
            raise NotFoundError(f"meeting {meeting_id} not found")
        return meeting

    async def _current_members(self, gremium_id: UUID) -> list[PrincipalRow]:
        """Return each member of the Gremium once."""
        rows = (
            (
                await self.session.execute(
                    select(PrincipalRow)
                    .join(
                        GremiumMembership,
                        GremiumMembership.principal_id == PrincipalRow.id,
                    )
                    .where(GremiumMembership.gremium_id == gremium_id)
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

        `canKeepProtocol` marks the members with `protocol.write`. Only they
        can keep the minutes.
        """
        members = await self._current_members(gremium_id)
        keepers = await keeper_principal_ids(self.session, gremium_id)
        return [
            MeetingMemberOut(
                principalId=m.id,
                displayName=m.display_name,
                email=m.email,
                canKeepProtocol=m.id in keepers,
            )
            for m in members
        ]

    async def roster(
        self, meeting_id: UUID, requester_sub: str, *, can_write: bool = False
    ) -> list[AttendanceOut]:
        """Return the members with the attendance they have for this meeting.

        The list holds the members of the Gremium, plus each principal with a
        record for the meeting, so a former member who attended stays in the
        list, plus each delegate with the voting right in the meeting. A delegate
        names the members it represents (`represents`), and a pool substitute on
        a seat without a record reads `present`. A member without
        a record gets `status` and `source` as `None`. The `note` goes only to
        the member and to the meeting lead (`can_write`). `canKeepProtocol` marks
        the members who can keep the minutes now, for the keeper picker and
        the handover. `canVote` marks the members with an own vote now (gremium
        permission `vote.cast`): only they can be substituted. A former member
        with a record has neither flag.
        """
        meeting = await self._meeting(meeting_id)
        members = list(
            (
                await self.session.execute(
                    select(PrincipalRow)
                    .where(meeting_roster_filter(meeting))
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
        statuses = {r.principal_id: r.status for r in records}
        perms = await member_permissions(self.session, meeting.gremium_id)
        member_ids = await self._member_ids(meeting.gremium_id)
        delegates = (await meeting_delegates(self.session, [meeting_id])).get(
            meeting_id, _NO_DELEGATES
        )
        names = await self._names(delegates, members)
        until = late_excuse_until(meeting, await self._late_excuse_days(meeting))
        now = datetime.now(UTC)
        return [
            _attendance_out(
                m,
                by_principal.get(m.id),
                perms.get(m.id, frozenset()),
                is_self=m.sub == requester_sub,
                can_write=can_write,
                late_until=_open_window(
                    by_principal.get(m.id), until, now, is_self=m.sub == requester_sub
                ),
                represents=sorted(
                    (
                        RepresentedOut(principalId=pid, displayName=names.get(pid))
                        for pid in delegates.represents.get(m.id, ())
                    ),
                    key=lambda r: (r.display_name or "").casefold(),
                ),
                status=delegate_status(delegates, statuses, m.id),
                is_member=m.id in member_ids,
            )
            for m in members
        ]

    async def _member_ids(self, gremium_id: UUID) -> set[UUID]:
        """Return the ids of the current members of the Gremium."""
        return set(
            (
                await self.session.execute(
                    select(GremiumMembership.principal_id).where(
                        GremiumMembership.gremium_id == gremium_id
                    )
                )
            )
            .scalars()
            .all()
        )

    async def _names(
        self, delegates: Delegates, roster: list[PrincipalRow]
    ) -> dict[UUID, str | None]:
        """Return the display name of each represented member.

        A represented member is in the roster as a rule; a former member is read.
        """
        wanted = {pid for ids in delegates.represents.values() for pid in ids}
        known = {m.id: m.display_name for m in roster if m.id in wanted}
        missing = wanted - known.keys()
        if not missing:
            return known
        rows = await self.session.execute(
            select(PrincipalRow.id, PrincipalRow.display_name).where(PrincipalRow.id.in_(missing))
        )
        return known | dict(rows.all())

    async def _is_delegate(self, meeting_id: UUID, principal_id: UUID) -> bool:
        """Return True when the principal holds a delegation with the voting right here."""
        found = (
            await self.session.execute(
                select(MeetingDelegation.id).where(
                    MeetingDelegation.meeting_id == meeting_id,
                    MeetingDelegation.delegate_principal_id == principal_id,
                    MeetingDelegation.delegate_voting.is_(True),
                )
            )
        ).first()
        return found is not None

    async def _attendee(self, meeting: Meeting, sub: str) -> PrincipalRow | None:
        """Return the principal of ``sub`` when it is a member or a delegate of the meeting."""
        member = next(
            (m for m in await self._current_members(meeting.gremium_id) if m.sub == sub), None
        )
        if member is not None:
            return member
        person = await self.session.scalar(select(PrincipalRow).where(PrincipalRow.sub == sub))
        if person is None or not await self._is_delegate(meeting.id, person.id):
            return None
        return person

    async def _late_excuse_days(self, meeting: Meeting) -> int:
        """Return the late-excuse period of the meeting, in days (spec 000942).

        A meeting keeps the value of the time it was made. Only a meeting from before
        the column reads the settings.
        """
        kept: int | None = getattr(meeting, "late_excuse_days", None)
        if kept is not None:
            return kept
        return kept_late_excuse_days(
            None,
            await self.session.scalar(
                select(MeetingSettings.late_excuse_days).where(MeetingSettings.id == 1)
            ),
        )

    async def excuse_late(
        self,
        meeting_id: UUID,
        requester_sub: str,
        note: str,
        *,
        now: datetime,
        can_write: bool = False,
    ) -> list[AttendanceOut]:
        """Change the own ``absent`` of a closed meeting to ``excused``.

        The window ends ``lateExcuseDays`` days after the close. The record gets the
        reason and the source ``self``. The caller commits.

        Raises:
            ForbiddenError: The requester has no account row.
            ConflictError: The meeting is not closed (``meeting_not_closed``), the
                requester has no ``absent`` record (``not_absent``), or the window is
                over (``late_excuse_expired``).
        """
        meeting = await self._meeting(meeting_id, for_write=True)
        until = late_excuse_until(meeting, await self._late_excuse_days(meeting))
        if until is None:
            raise ConflictError("A late excuse needs a closed meeting.", code="meeting_not_closed")
        member_id = await self.session.scalar(
            select(PrincipalRow.id).where(PrincipalRow.sub == requester_sub)
        )
        if member_id is None:
            raise ForbiddenError("only a member gives an excuse")
        existing = await self._record(meeting_id, member_id)
        if existing is None or existing.status != "absent":
            raise ConflictError("Only an absence can be excused later.", code="not_absent")
        if now > until:
            raise ConflictError("The period for a late excuse is over.", code="late_excuse_expired")
        before_source = existing.source
        self._write(
            existing,
            meeting_id=meeting_id,
            principal_id=member_id,
            status="excused",
            source="self",
            note=note,
        )
        await self._flush_write()
        await self._audit(
            AuditAction.ATTENDANCE_SET,
            actor=requester_sub,
            meeting_id=meeting_id,
            principal_id=member_id,
            status={"from": "absent", "to": "excused"},
            source={"from": before_source, "to": "self"},
            late=True,
        )
        return await self.roster(meeting_id, requester_sub, can_write=can_write)

    async def _record(self, meeting_id: UUID, principal_id: UUID) -> MeetingAttendance | None:
        """Load the record of one member with a row lock.

        The lock orders a self report and a lead change of the same record, so
        the lead-record check and the write see the same row.
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
                code="concurrent_attendance_change",
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
                "Attendance is read-only once the meeting is closed.", code="meeting_closed"
            )

    async def _ensure_lead_open(self, meeting: Meeting) -> None:
        """Refuse a change of the lead when the protocol of a closed meeting is final.

        The lead corrects the attendance of a closed meeting while its protocol is a
        draft (§F/meetings/meetings/000951). A protocol in its render counts as final.

        Raises:
            ConflictError: The protocol is final (409 ``protocol_final``).
        """
        if meeting.status != "closed":
            return
        state = await self.session.scalar(
            select(Protocol.status).where(Protocol.meeting_id == meeting.id)
        )
        if state in ("rendering", "final"):
            raise ConflictError(
                "Attendance is read-only once the protocol is final.", code="protocol_final"
            )

    async def _recount(self, meeting: Meeting) -> None:
        """Count the present members of a closed meeting again after a correction."""
        if meeting.status == "closed":
            here = await present_count(self.session, meeting.id)
            setattr(meeting, "present_count", here.total)  # noqa: B010

    async def _audit(
        self,
        action: AuditAction,
        *,
        actor: str,
        meeting_id: UUID,
        principal_id: UUID,
        **extra: object,
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
        """Report the own attendance of the requester, a member or a delegate.

        `present` is refused while the member has a delegation for the meeting,
        as for the lead. Else the member counts as present but stays
        blocked from the vote.

        Raises:
            ForbiddenError: The requester is neither a current member of the Gremium
                nor a delegate with the voting right in the meeting.
            ConflictError: The meeting is closed, the meeting lead set the record
                (code `attendance_set_by_lead`), the status is `present` while
                a delegation of the member exists (code `delegation_active`),
                or a parallel change wrote the record first (code `conflict`).
        """
        meeting = await self._meeting(meeting_id, for_write=True)
        self._ensure_not_closed(meeting)
        member = await self._attendee(meeting, requester_sub)
        if member is None:
            raise ForbiddenError("only committee members and delegates can mark their attendance")
        existing = await self._record(meeting_id, member.id)
        if existing is not None and existing.source == "lead":
            raise ConflictError(
                "The meeting lead set this attendance. Only the lead can change it.",
                code="attendance_set_by_lead",
            )
        if status == "present" and await self._delegated(meeting_id, member.id, requester_sub):
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

    async def mark_present_on_cast(self, meeting_id: UUID, voter_sub: str) -> None:
        """Mark a member or a delegate present who casts a ballot in a meeting vote.

        A ballot shows that the person takes part, so the record becomes `present`,
        also over an `absent` or `excused` record of the lead. The source stays as it
        was, so a lead record stays locked against the self report. A delegate who
        casts for the represented members counts as present too
        (§F/meetings/delegations/003152). A caller who is neither a current member nor
        a delegate gets no attendance, and so does a member with a delegation for the
        meeting (present and delegated exclude each other). The method does not commit: the ballot
        commits it, and a refused ballot rolls it back. It does not lock the meeting
        row, because the caller holds the vote row and the lock order is meeting row
        first.
        """
        meeting = await self._meeting(meeting_id)
        if meeting.status == "closed":
            return
        member = await self._attendee(meeting, voter_sub)
        if member is None:
            return
        existing = await self._record(meeting_id, member.id)
        if existing is not None and existing.status == "present":
            return
        if await self._has_delegation(meeting_id, member.id):
            return
        before = existing.status if existing is not None else None
        self._write(
            existing,
            meeting_id=meeting_id,
            principal_id=member.id,
            status="present",
            source=existing.source if existing is not None else "self",
            note=None,
        )
        await self._audit(
            AuditAction.ATTENDANCE_SET,
            actor=voter_sub,
            meeting_id=meeting_id,
            principal_id=member.id,
            status={"from": before, "to": "present"},
            reason="vote_cast",
        )
        await self._flush_write()

    async def _delegated(self, meeting_id: UUID, principal_id: UUID, actor_sub: str) -> bool:
        """Free a pool seat of the member, then tell whether a delegation remains.

        A check-in frees the seat that a pool substitute took for the member
        (`release_pool_seat`). A delegation that the member gave or that the lead
        entered stays and refuses the check-in.
        """
        await release_pool_seat(self.session, meeting_id, principal_id, actor_sub)
        return await self._has_delegation(meeting_id, principal_id)

    async def _has_delegation(self, meeting_id: UUID, principal_id: UUID) -> bool:
        """Return True when the member delegated for this meeting."""
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
        """Set the attendance of a member or of a delegate as the meeting lead.

        The router checks `canWrite` before the call. The change writes
        `attendance_set` with the status before and after it.

        In a closed meeting the change is a correction of the record. It also takes a
        former member who has a record in the meeting, because the roster still lists
        this person. It frees no pool seat and checks no delegation, because the
        votes of the meeting are over and the substitutions belong to its record.

        Raises:
            NotFoundError: The principal is neither a current member of the Gremium
                nor a delegate with the voting right in the meeting, and the meeting is
                not closed or holds no record of the principal.
            ConflictError: The protocol of the closed meeting is final (code
                `protocol_final`), the status is `present` while a
                delegation of the member exists (code `delegation_active`), or
                a parallel change wrote the record first (code `conflict`).
        """
        meeting = await self._meeting(meeting_id, for_write=True)
        await self._ensure_lead_open(meeting)
        closed = meeting.status == "closed"
        members = await self._current_members(meeting.gremium_id)
        is_member = any(m.id == principal_id for m in members) or await self._is_delegate(
            meeting_id, principal_id
        )
        if not is_member and not closed:
            raise NotFoundError("principal is neither a member nor a delegate of this meeting")
        if (
            not closed
            and status == "present"
            and await self._delegated(meeting_id, principal_id, requester_sub)
        ):
            raise ConflictError(_DELEGATION_ACTIVE, code="delegation_active")
        existing = await self._record(meeting_id, principal_id)
        if not is_member and existing is None:
            raise NotFoundError("principal has no attendance record in this meeting")
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
        await self._recount(meeting)
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
            ConflictError: The protocol of the closed meeting is final (409).
        """
        meeting = await self._meeting(meeting_id, for_write=True)
        await self._ensure_lead_open(meeting)
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
            await self._recount(meeting)
            await self.session.commit()
        return await self.roster(meeting_id, requester_sub, can_write=True)
