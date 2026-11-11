"""Delegation service and security core.

A delegation is meeting-bound and lives in `meeting_delegation`. Each (meeting,
member) pair has exactly one outgoing delegation. The gremium of the delegation
is the gremium of the meeting. A delegation can also carry the vote. That
transfer is exclusive and never a duplicate.

The server enforces these invariants:

* Feature gate. A meeting delegation, with or without the vote, needs the
  gremium flag `allow_vote_delegation` (§F/meetings/delegations/000110). No
  server setting switches the vote transfer.
* Own vote only. The delegator must be a voting member of the meeting gremium.
  The right comes only from an active gremium membership whose gremium role
  holds `vote.cast`. A global role, a role assignment or an OIDC group mapping
  does not give it. Every other caller gets 403.
* No chains. Per meeting a principal is either delegator or recipient, never
  both, else 422.
* Recipient set. Gremium members and the substitute pool are always eligible.
  Other users need `delegation_allow_external`, else 403. The pool is the
  table `delegation_substitute` of the gremium. The helpers in
  `delegations.pool` are its only source.
* Deadline. A delegation from outside the pool runs until the meeting start minus
  `delegation_lead_minutes` of the gremium config. A pool delegation runs until
  the meeting start. The meeting must still be `planned`, else 422. A revocation
  runs until the meeting start.
* Lead entry. During a live meeting the meeting lead (`can_manage`) enters
  a substitution for a missing member (`delegatorId`). The delegate must be a
  pool substitute of that member: a personal entry for the member or a
  gremium-wide entry. The lead can also revoke a
  delegation while the meeting is live. A ballot that the delegate already cast
  stays.
* Transfer, not duplicate. Each (meeting, recipient) pair carries at most one
  vote delegation, else 409. The delegator cannot vote in that meeting. See
  `voting_delegation_check`. The audit log records every use.
"""

from __future__ import annotations

from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.policy import has_gremium_permission, holds_gremium_permission
from app.modules.auth.principal import Principal
from app.modules.delegations.models import (
    DelegationSubstitute,
    MeetingDelegation,
)
from app.modules.delegations.pool import (
    substitute_gremien_for_sub,
    substitutes_for,
)
from app.modules.delegations.pool_seat import (
    lock_meeting_delegations,
    pool_seat_clause,
    pool_seat_for,
)
from app.modules.delegations.schemas import (
    DelegationCreate,
    DelegationOut,
    MeetingDelegationContext,
    RecipientOut,
    SubstituteCreate,
    SubstituteOut,
    VoteDelegationStatus,
)
from app.modules.gremien.gremium_roles import gremium_member_ids
from app.modules.gremien.models import Gremium, GremiumMembership, GremiumRole
from app.modules.livevote.models import Meeting, MeetingAttendance
from app.modules.livevote.roster import planned_start_utc
from app.modules.voting.models import Vote
from app.settings import Settings
from app.shared.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationProblem,
)

#: Permission that grants the view and the management of foreign delegations.
_ADMIN_PERM = "admin.delegations"
#: Gremium-role permission that may manage the substitute pool. The same
#: permission makes the meeting lead (`can_manage`), who enters a substitution
#: during a live meeting.
_POOL_MANAGE_PERM = "session.manage"
#: Attendance states in which a member counts as missing. No record counts
#: as missing too.
_MISSING_STATES = frozenset({"excused", "absent"})


def _escape_like(needle: str) -> str:
    """Neutralize the LIKE and ILIKE metacharacters in a user search term.

    Without the escape, `%` and `_` act as wildcards. The backslash is the escape
    character and needs an escape too. Call the result with
    `.ilike(pattern, escape=...)` and pass a single backslash as the escape.
    """
    return needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _lead_data(delegator_id: UUID, *, by_lead: bool) -> dict[str, str | bool]:
    """Return the audit fields that mark a delegation write of the meeting lead."""
    return {"delegatorId": str(delegator_id), "byLead": True} if by_lead else {}


def meeting_start_utc(meeting: Meeting, tz_name: str) -> datetime | None:
    """Return the meeting start as an aware UTC datetime.

    The database stores `date` and `start_time` as naive local time in
    `settings.local_timezone`. A meeting without a start time begins at 00:00
    local time.

    Returns:
        The start in UTC, or None when the meeting has no date.
    """
    return planned_start_utc(meeting, tz_name)


async def _membership_with_vote_cast(
    session: AsyncSession, principal_id: UUID, gremium_id: UUID
) -> bool:
    """Report whether a gremium membership grants `vote.cast`."""
    rows = (
        (
            await session.execute(
                select(GremiumRole.permissions)
                .select_from(GremiumMembership)
                .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
                .where(
                    GremiumMembership.principal_id == principal_id,
                    GremiumMembership.gremium_id == gremium_id,
                )
            )
        )
        .scalars()
        .all()
    )
    return any("vote.cast" in (perms or []) for perms in rows)


async def _independently_eligible(
    session: AsyncSession, principal_id: UUID, gremium_id: UUID
) -> bool:
    """Report whether the principal can vote without any delegation.

    The check uses the same source as the cast gate of the voting module: a
    gremium membership whose gremium role holds `vote.cast`. The membership comes from
    the OIDC groups through the gremium mappings. A global role or a raw OIDC group
    never gives the voting right in a gremium.
    """
    return await _membership_with_vote_cast(session, principal_id, gremium_id)


async def voting_delegation_check(
    session: AsyncSession,
    sub: str,
    meeting_id: UUID | None,
    eligible_group: str,
    now: datetime,
) -> tuple[bool, str | None]:
    """Give the two-sided vote verdict for `sub`.

    The verdict is meeting-bound. Only `meeting_delegation` rows of this meeting
    count. The gremium of the vote must match the gremium of the delegation, which
    means `eligible_group` equals `str(gremium_id)`. A vote without a meeting has
    no delegation.

    * An outgoing row with `delegate_voting` blocks the caller. The transfer lets
      only the recipient vote. A pool seat (`pool_seat.py`) does not block: the own
      ballot of the member frees it.
    * An incoming row with `delegate_voting` returns the `sub` of the delegator.
      The caller may then cast one delegated ballot next to the own ballot. That
      ballot runs under `delegator_sub`, so it is a transfer and not a duplicate.
      The caller can therefore vote even as an external user.

    `now` keeps the signature equal to the other checks. A delegation is bound to a meeting, not to
    a time.

    Returns:
        The blocked flag and the `sub` of the delegator. The second value is None
        when the caller holds no incoming voting delegation.
    """
    if meeting_id is None:
        return False, None
    try:
        gremium_id = UUID(eligible_group)
    except (ValueError, TypeError):
        return False, None
    pid_subq = select(PrincipalRow.id).where(PrincipalRow.sub == sub).scalar_subquery()
    delegator = aliased(PrincipalRow)
    delegate = aliased(PrincipalRow)
    is_delegator = MeetingDelegation.delegator_principal_id == pid_subq
    rows = (
        await session.execute(
            select(
                is_delegator,
                and_(
                    MeetingDelegation.delegate_voting,
                    or_(~is_delegator, ~pool_seat_clause(delegate)),
                ),
                delegator.sub,
            )
            .join(
                delegator,
                delegator.id == MeetingDelegation.delegator_principal_id,
            )
            .join(delegate, delegate.id == MeetingDelegation.delegate_principal_id)
            .where(
                MeetingDelegation.meeting_id == meeting_id,
                MeetingDelegation.gremium_id == gremium_id,
                or_(
                    MeetingDelegation.delegator_principal_id == pid_subq,
                    MeetingDelegation.delegate_principal_id == pid_subq,
                ),
            )
        )
    ).all()
    blocked = any(is_delegator and voting for is_delegator, voting, _ in rows)
    delegator_sub = next(
        (d_sub for is_delegator, voting, d_sub in rows if not is_delegator and voting),
        None,
    )
    return blocked, delegator_sub


@dataclass(frozen=True, slots=True)
class DelegationService:
    """Delegation service bound to an `AsyncSession` and a `Settings` object.

    Attributes:
        session: The database session of the request.
        settings: The application settings.
    """

    session: AsyncSession
    settings: Settings

    async def _principal_row(
        self, *, sub: str | None = None, pid: UUID | None = None
    ) -> PrincipalRow | None:
        clause = PrincipalRow.sub == sub if sub is not None else PrincipalRow.id == pid
        return (await self.session.execute(select(PrincipalRow).where(clause))).scalar_one_or_none()

    async def _names(self, ids: AbstractSet[UUID]) -> dict[UUID, str | None]:
        if not ids:
            return {}
        rows = (
            await self.session.execute(
                select(PrincipalRow.id, PrincipalRow.display_name, PrincipalRow.email).where(
                    PrincipalRow.id.in_(ids)
                )
            )
        ).all()
        return {pid: (name or email) for pid, name, email in rows}

    async def _meeting(self, meeting_id: UUID, *, lock: bool = False) -> Meeting:
        """Load a meeting by id.

        `lock` takes the meeting row FOR UPDATE and reads the current values again.
        The attendance writers hold a share lock on the same row, so a lead entry
        and an attendance change run one after the other.

        Raises:
            NotFoundError: No meeting has this id (404).
        """
        meeting = (
            await self.session.get(
                Meeting, meeting_id, with_for_update=True, populate_existing=True
            )
            if lock
            else await self.session.get(Meeting, meeting_id)
        )
        if meeting is None:
            raise NotFoundError(f"meeting {meeting_id} not found")
        return meeting

    async def _gremium(self, gremium_id: UUID) -> Gremium:
        gremium = await self.session.get(Gremium, gremium_id)
        if gremium is None:
            raise NotFoundError(f"gremium {gremium_id} not found")
        return gremium

    async def _member_ids(self, gremium_id: UUID) -> set[UUID]:
        """Return the gremium members with any role."""
        rows = (
            (
                await self.session.execute(
                    select(GremiumMembership.principal_id).where(
                        GremiumMembership.gremium_id == gremium_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        return set(rows)

    async def _assert_can_view_gremium(self, gremium_id: UUID, actor: Principal) -> None:
        """Guard the roster and the pool of a gremium against cross-tenant PII reads.

        Global readers and managers pass the guard. They hold `admin.delegations`
        or `meeting.view_all`; the `admin` role holds both. Both checks go through
        `Principal.has`, so the OAuth scope cap applies: an admin token without
        either right in its scope does not pass as a global reader. Members, the
        substitute pool and the holders of the `session.manage` role of this gremium
        also pass. They see the same data as in the meeting timeline.

        Raises:
            ForbiddenError: The actor may not view this gremium (403).
        """
        if actor.has(_ADMIN_PERM) or actor.has("meeting.view_all"):
            return
        if gremium_id in await gremium_member_ids(self.session, actor.sub):
            return
        if gremium_id in await substitute_gremien_for_sub(self.session, actor.sub):
            return
        if await holds_gremium_permission(self.session, actor, _POOL_MANAGE_PERM, gremium_id):
            return
        raise ForbiddenError("Not allowed to view this gremium's delegation roster.")

    async def _can_manage(self, gremium_id: UUID, actor: Principal) -> bool:
        """Check for the meeting lead: gremium `session.manage` or the admin role.

        This is the same rule as `PermissionOps.can_manage` of the meeting module.
        The scope cap applies to both paths.
        """
        return await has_gremium_permission(self.session, actor, _POOL_MANAGE_PERM, gremium_id)

    def _revocable(
        self, meeting: Meeting, now: datetime, *, lead: bool = False, own: bool = True
    ) -> bool:
        """Tell if the viewer can revoke a delegation of this meeting.

        The delegator can revoke while the meeting is planned and has not started.
        The meeting lead (`lead`) can also revoke while the meeting is live.
        `own` is False for a row that the viewer sees only as the meeting lead.
        The lead cannot revoke such a row before the start, so it is not revocable.
        """
        if lead and meeting.status == "live":
            return True
        if not own or meeting.status != "planned":
            return False
        start = meeting_start_utc(meeting, self.settings.local_timezone)
        return start is None or now < start

    @staticmethod
    def _direction(d: MeetingDelegation, me_id: UUID | None) -> str | None:
        if me_id is None:
            return None
        if d.delegator_principal_id == me_id:
            return "outgoing"
        if d.delegate_principal_id == me_id:
            return "incoming"
        return None

    async def _out(
        self,
        rows: list[tuple[MeetingDelegation, Meeting, Gremium]],
        now: datetime,
        me_id: UUID | None = None,
        lead_gremien: AbstractSet[UUID] = frozenset(),
        *,
        admin: bool = False,
    ) -> list[DelegationOut]:
        """Build the views.

        `lead_gremien` holds the gremien that the viewer leads. `admin` tells that
        the viewer may revoke every row.

        A fresh row gets `created_at` from the database default only on the next select, so the view
        uses the creation time until then.
        """
        ids = {
            pid for d, _, _ in rows for pid in (d.delegator_principal_id, d.delegate_principal_id)
        }
        names = await self._names(ids)
        return [
            DelegationOut(
                id=d.id,
                meeting_id=d.meeting_id,
                meeting_title=meeting.title,
                meeting_date=meeting.date.isoformat() if meeting.date else None,
                gremium_id=d.gremium_id,
                gremium_name=gremium.name,
                delegator_id=d.delegator_principal_id,
                delegator_name=names.get(d.delegator_principal_id),
                delegate_id=d.delegate_principal_id,
                delegate_name=names.get(d.delegate_principal_id),
                delegate_voting=d.delegate_voting,
                via_pool=d.via_pool,
                created_at=d.created_at or now,
                revocable=self._revocable(
                    meeting,
                    now,
                    lead=d.gremium_id in lead_gremien,
                    own=admin or self._direction(d, me_id) is not None,
                ),
                direction=self._direction(d, me_id),
            )
            for d, meeting, gremium in rows
        ]

    async def _joined(
        self, *where: ColumnElement[bool]
    ) -> list[tuple[MeetingDelegation, Meeting, Gremium]]:
        rows = (
            await self.session.execute(
                select(MeetingDelegation, Meeting, Gremium)
                .join(Meeting, Meeting.id == MeetingDelegation.meeting_id)
                .join(Gremium, Gremium.id == MeetingDelegation.gremium_id)
                .where(*where)
                .order_by(MeetingDelegation.created_at.desc())
            )
        ).all()
        return [(d, m, g) for d, m, g in rows]

    async def create(self, payload: DelegationCreate, actor: Principal) -> DelegationOut:
        """Create a meeting delegation.

        Without `delegatorId` the caller delegates for themselves while the meeting
        is planned. With `delegatorId` the meeting lead enters a substitution for a
        missing member while the meeting is live. See `_create_by_lead`.

        Raises:
            ForbiddenError: The gremium gate blocks the delegation, the recipient
                is not eligible, or the delegator may not vote (403).
            NotFoundError: The meeting or the recipient does not exist (404).
            ConflictError: The delegator already delegated for this meeting, or the
                recipient already carries a delegated vote (409).
            ValidationProblem: The meeting is not planned, the deadline has
                passed, the delegator picked themselves, or the delegation would
                build a chain (422).
        """
        if payload.delegator_id is not None:
            return await self._create_by_lead(payload, payload.delegator_id, actor)
        now = datetime.now(UTC)
        meeting = await self._meeting(payload.meeting_id)
        gremium = await self._gremium(meeting.gremium_id)

        if not gremium.allow_vote_delegation:
            raise ForbiddenError("Delegation is not enabled for this gremium.")
        if meeting.status != "planned":
            raise ValidationProblem(
                "Meeting has already started.",
                errors=[{"field": "meetingId", "msg": "meeting is not planned"}],
            )

        me = await self._principal_row(sub=actor.sub)
        if me is None:
            raise ForbiddenError("Delegator principal not found.")
        delegate = await self._principal_row(pid=payload.delegate_id)
        if delegate is None:
            raise NotFoundError(f"principal {payload.delegate_id} not found")
        if delegate.id == me.id:
            raise ValidationProblem(
                "Cannot delegate to yourself.",
                errors=[{"field": "delegateId", "msg": "must differ from delegator"}],
            )

        if not await _independently_eligible(self.session, me.id, gremium.id):
            raise ForbiddenError("Only voting members of the meeting's gremium may delegate.")

        pool_ids = await substitutes_for(self.session, gremium.id, me.id)
        member_ids = await self._member_ids(gremium.id)
        via_pool = delegate.id in pool_ids
        if not via_pool and delegate.id not in member_ids and not gremium.delegation_allow_external:
            raise ForbiddenError("Recipient must be a gremium member or a designated substitute.")

        start = meeting_start_utc(meeting, self.settings.local_timezone)
        if start is not None:
            deadline = (
                start if via_pool else start - timedelta(minutes=gremium.delegation_lead_minutes)
            )
            if now >= deadline:
                raise ValidationProblem(
                    "Delegation deadline for this meeting has passed.",
                    errors=[{"field": "meetingId", "msg": "deadline passed"}],
                )

        row = await self._insert(
            meeting,
            gremium,
            delegator=me,
            delegate=delegate,
            delegate_voting=payload.delegate_voting,
            via_pool=via_pool,
            actor=actor,
            by_lead=False,
        )
        return (await self._out([(row, meeting, gremium)], now, me.id))[0]

    async def _create_by_lead(
        self, payload: DelegationCreate, delegator_id: UUID, actor: Principal
    ) -> DelegationOut:
        """Enter a substitution for a missing member during a live meeting.

        The meeting lead (`can_manage`) names the missing member A (`delegatorId`)
        and a substitute B from the pool of the gremium for A: a personal entry
        for A or a gremium-wide entry. The checks are the same as before the
        meeting: the gremium allows delegations, A may vote, and no chains. A is
        missing when A has no attendance record, or the record is `excused` or
        `absent`. The lead cannot name themselves as B. The row stores the lead as `created_by` and
        `via_pool = true`.

        Lock the meeting row before the status and attendance reads. The attendance writers hold a
        share lock on this row and then look for a delegation. Thus a `present` report of A and this
        entry for A cannot both commit. The missing member does not consent to this entry, so the
        lead must not give the vote to themselves.

        Raises:
            ForbiddenError: The caller is not the meeting lead, the gremium does not
                allow delegations, B is the lead, A may not vote, or B is not in
                the pool for A (403).
            NotFoundError: The meeting, A or B does not exist (404).
            ConflictError: A already has a delegation, or B already carries a
                delegated vote (409).
            ValidationProblem: The meeting is not live, A and B are the same
                person, A is present, or the delegation would build a chain (422).
        """
        now = datetime.now(UTC)
        unlocked = await self._meeting(payload.meeting_id)
        gremium = await self._gremium(unlocked.gremium_id)
        if not await self._can_manage(gremium.id, actor):
            raise ForbiddenError(
                "Only the meeting lead may enter a substitution for another member."
            )
        meeting = await self._meeting(payload.meeting_id, lock=True)
        if not gremium.allow_vote_delegation:
            raise ForbiddenError("Delegation is not enabled for this gremium.")
        if meeting.status != "live":
            raise ValidationProblem(
                "The meeting lead enters a substitution only during a live meeting.",
                errors=[{"field": "meetingId", "msg": "meeting is not live"}],
            )
        delegator = await self._principal_row(pid=delegator_id)
        if delegator is None:
            raise NotFoundError(f"principal {delegator_id} not found")
        delegate = await self._principal_row(pid=payload.delegate_id)
        if delegate is None:
            raise NotFoundError(f"principal {payload.delegate_id} not found")
        if delegate.id == delegator.id:
            raise ValidationProblem(
                "A member cannot substitute for themselves.",
                errors=[{"field": "delegateId", "msg": "must differ from delegator"}],
            )
        if delegate.sub == actor.sub:
            raise ForbiddenError("The meeting lead cannot name themselves as the substitute.")
        if not await _independently_eligible(self.session, delegator.id, gremium.id):
            raise ForbiddenError(
                "Only a voting member of the meeting's gremium can be substituted."
            )
        attendance = await self.session.scalar(
            select(MeetingAttendance.status).where(
                MeetingAttendance.meeting_id == meeting.id,
                MeetingAttendance.principal_id == delegator.id,
            )
        )
        if attendance is not None and attendance not in _MISSING_STATES:
            raise ValidationProblem(
                "The member is present and needs no substitution.",
                errors=[{"field": "delegatorId", "msg": "member is not missing"}],
            )
        if delegate.id not in await substitutes_for(self.session, gremium.id, delegator.id):
            raise ForbiddenError("Recipient must be a pool substitute of the member.")
        row = await self._insert(
            meeting,
            gremium,
            delegator=delegator,
            delegate=delegate,
            delegate_voting=payload.delegate_voting,
            via_pool=True,
            actor=actor,
            by_lead=True,
        )
        return (await self._out([(row, meeting, gremium)], now, None, {gremium.id}))[0]

    async def _insert(
        self,
        meeting: Meeting,
        gremium: Gremium,
        *,
        delegator: PrincipalRow,
        delegate: PrincipalRow,
        delegate_voting: bool,
        via_pool: bool,
        actor: Principal,
        by_lead: bool,
    ) -> MeetingDelegation:
        """Check the chain rules, then store the delegation and write the audit entry.

        No chains: per meeting a principal is either delegator or recipient. A transaction-scoped
        advisory lock serializes the insert per meeting, because without it a concurrent insert of A
        to B and B to C could race the read-then-insert check. The second int4 argument of the lock
        is a stable 32-bit derivation of the meeting id.

        Raises:
            ConflictError: The delegator already delegated for this meeting, or the
                recipient already carries a delegated vote (409).
            ValidationProblem: The delegation would build a chain (422).
        """
        await lock_meeting_delegations(self.session, meeting.id)
        existing = (
            await self.session.execute(
                select(
                    MeetingDelegation.delegator_principal_id,
                    MeetingDelegation.delegate_principal_id,
                    MeetingDelegation.delegate_voting,
                ).where(MeetingDelegation.meeting_id == meeting.id)
            )
        ).all()
        for delegator_id, delegate_id, voting in existing:
            if delegator_id == delegator.id:
                raise ConflictError(
                    "The member already delegated for this meeting.", code="delegation_exists"
                )
            if delegate_id == delegator.id:
                raise ValidationProblem(
                    "The member receives a delegation for this meeting and cannot delegate on.",
                    errors=[{"field": "meetingId", "msg": "no re-delegation chains"}],
                )
            if delegator_id == delegate.id:
                raise ValidationProblem(
                    "Recipient has delegated their own vote for this meeting.",
                    errors=[{"field": "delegateId", "msg": "no re-delegation chains"}],
                )
            if delegate_voting and voting and delegate_id == delegate.id:
                raise ConflictError(
                    "Recipient already carries a delegated vote for this meeting.",
                    code="delegate_already_voting",
                )

        row = MeetingDelegation(
            meeting_id=meeting.id,
            gremium_id=gremium.id,
            delegator_principal_id=delegator.id,
            delegate_principal_id=delegate.id,
            delegate_voting=delegate_voting,
            via_pool=via_pool,
            created_by=actor.sub,
        )
        self.session.add(row)
        await self.session.flush()
        data: dict[str, str | bool] = {
            "meetingId": str(meeting.id),
            "gremiumId": str(gremium.id),
            "delegateId": str(delegate.id),
            "delegateVoting": delegate_voting,
            "viaPool": via_pool,
            **_lead_data(delegator.id, by_lead=by_lead),
        }
        await audit_record(
            self.session,
            actor=actor.sub,
            action=AuditAction.DELEGATION_GRANT,
            target_type="meeting_delegation",
            target_id=str(row.id),
            data=data,
        )
        await self.session.commit()
        return row

    async def list(self, actor: Principal, meeting_id: UUID | None = None) -> list[DelegationOut]:
        """Return the own outgoing and incoming delegations.

        A holder of `admin.delegations` sees every delegation. With `meeting_id`,
        the meeting lead (`can_manage`) sees every delegation of that meeting, so
        the lead can revoke one during the live meeting.
        """
        now = datetime.now(UTC)
        me = await self._principal_row(sub=actor.sub)
        admin = actor.has(_ADMIN_PERM)
        meeting = await self.session.get(Meeting, meeting_id) if meeting_id is not None else None
        lead_gremien = (
            frozenset({meeting.gremium_id})
            if meeting is not None and await self._can_manage(meeting.gremium_id, actor)
            else frozenset[UUID]()
        )
        sees_all = admin or bool(lead_gremien)
        if not sees_all and me is None:
            return []
        meeting_clause = (
            (MeetingDelegation.meeting_id == meeting_id,) if meeting_id is not None else ()
        )
        own_clause = (
            ()
            if sees_all or me is None
            else (
                or_(
                    MeetingDelegation.delegator_principal_id == me.id,
                    MeetingDelegation.delegate_principal_id == me.id,
                ),
            )
        )
        return await self._out(
            await self._joined(*meeting_clause, *own_clause),
            now,
            me.id if me else None,
            lead_gremien,
            admin=admin,
        )

    async def revoke(self, delegation_id: UUID, actor: Principal) -> None:
        """Revoke a delegation with a hard delete that takes effect at once.

        The delegator may revoke until the meeting starts, and only while the
        meeting is `planned`. The meeting lead (`can_manage`) may revoke while the
        meeting is `live`, for example when the substituted member arrives.
        A ballot that the delegate already cast stays. An admin may revoke at any
        time.

        Raises:
            NotFoundError: The delegation does not exist (404).
            ForbiddenError: The actor is not the delegator, not the meeting lead of
                a live meeting, and not an admin (403).
            ValidationProblem: The meeting already started (422).
        """
        row = await self.session.get(MeetingDelegation, delegation_id)
        if row is None:
            raise NotFoundError(f"delegation {delegation_id} not found")
        by_lead = not actor.has(_ADMIN_PERM) and await self._revoke_as_lead(row, actor)
        data: dict[str, str | bool] = {
            "meetingId": str(row.meeting_id),
            **_lead_data(row.delegator_principal_id, by_lead=by_lead),
        }
        await self.session.delete(row)
        await audit_record(
            self.session,
            actor=actor.sub,
            action=AuditAction.DELEGATION_REVOKE,
            target_type="meeting_delegation",
            target_id=str(delegation_id),
            data=data,
        )
        await self.session.commit()

    async def _revoke_as_lead(self, row: MeetingDelegation, actor: Principal) -> bool:
        """Check the revoke of a caller without `admin.delegations`.

        Returns:
            True when the meeting lead revokes during a live meeting, False when the
            delegator revokes their own delegation in time.

        Raises:
            ForbiddenError: The actor is not the delegator and not the meeting lead of
                a live meeting (403).
            ValidationProblem: The meeting already started (422).
        """
        meeting = await self._meeting(row.meeting_id)
        if meeting.status == "live" and await self._can_manage(meeting.gremium_id, actor):
            return True
        me = await self._principal_row(sub=actor.sub)
        if me is None or row.delegator_principal_id != me.id:
            raise ForbiddenError(
                "Only the delegator, the meeting lead of a live meeting, or an admin may revoke."
            )
        if not self._revocable(meeting, datetime.now(UTC)):
            raise ValidationProblem(
                "Meeting has already started; delegation can no longer be revoked.",
                errors=[{"field": "id", "msg": "meeting started"}],
            )
        return False

    async def _candidates(
        self, gremium_id: UUID, me_id: UUID, needle: str = ""
    ) -> list[RecipientOut]:
        """Return the members and the pool of the caller as recipients, without the caller.

        A non-empty `needle` keeps only the names that contain it.
        """
        member_ids = await self._member_ids(gremium_id)
        pool_ids = await substitutes_for(self.session, gremium_id, me_id)
        ids = (member_ids | pool_ids) - {me_id}
        names = await self._names(ids)
        return [
            RecipientOut(
                principal_id=pid,
                display_name=names.get(pid),
                via_pool=pid in pool_ids,
                is_member=pid in member_ids,
            )
            for pid in ids
            if not needle or needle in (names.get(pid) or "").lower()
        ]

    async def _own_delegations(
        self, meeting_id: UUID, me_id: UUID, now: datetime
    ) -> tuple[DelegationOut | None, list[DelegationOut]]:
        """Return the outgoing delegation and the incoming delegations of the caller.

        A meeting has at most one outgoing delegation per delegator; the last one wins.
        """
        rows = await self._joined(
            MeetingDelegation.meeting_id == meeting_id,
            or_(
                MeetingDelegation.delegator_principal_id == me_id,
                MeetingDelegation.delegate_principal_id == me_id,
            ),
        )
        outs = await self._out(rows, now, me_id)
        pairs = tuple(zip(rows, outs, strict=True))
        outgoing = [out for (d, _, _), out in pairs if d.delegator_principal_id == me_id]
        incoming = [out for (d, _, _), out in pairs if d.delegator_principal_id != me_id]
        return (outgoing[-1] if outgoing else None), incoming

    async def meeting_context(self, meeting_id: UUID, actor: Principal) -> MeetingDelegationContext:
        """Build the context for the set-up-delegation dialog of a meeting.

        The roster and the recipient names are PII and must not leak to outsiders.

        Check the view rights before the roster and the personal data are built.

        Raises:
            NotFoundError: The meeting does not exist (404).
            ForbiddenError: The actor is not a member, a pool substitute or a
                manager of the meeting gremium (403).
        """
        now = datetime.now(UTC)
        meeting = await self._meeting(meeting_id)
        gremium = await self._gremium(meeting.gremium_id)
        await self._assert_can_view_gremium(gremium.id, actor)
        me = await self._principal_row(sub=actor.sub)

        start = meeting_start_utc(meeting, self.settings.local_timezone)
        deadline = (
            start - timedelta(minutes=gremium.delegation_lead_minutes)
            if start is not None
            else None
        )
        meeting_started = meeting.status != "planned" or (start is not None and now >= start)

        can_delegate = (
            me is not None
            and gremium.allow_vote_delegation
            and await _independently_eligible(self.session, me.id, gremium.id)
        )
        my_delegation, incoming = (
            await self._own_delegations(meeting.id, me.id, now) if me is not None else (None, [])
        )
        candidates = await self._candidates(gremium.id, me.id) if me is not None else []
        recipients = sorted(
            candidates, key=lambda r: (not r.via_pool, (r.display_name or "").lower())
        )

        return MeetingDelegationContext(
            meeting_id=meeting.id,
            gremium_id=gremium.id,
            allow_vote_delegation=gremium.allow_vote_delegation,
            voting_delegation_enabled=gremium.allow_vote_delegation,
            delegation_allow_external=gremium.delegation_allow_external,
            deadline=deadline,
            deadline_passed=deadline is not None and now >= deadline,
            meeting_started=meeting_started,
            can_delegate=can_delegate,
            my_delegation=my_delegation,
            incoming=incoming,
            recipients=recipients,
        )

    async def recipients(
        self,
        meeting_id: UUID,
        q: str,
        actor: Principal,
        delegator_id: UUID | None = None,
    ) -> list[RecipientOut]:
        """List the eligible recipients for the typeahead.

        With `delegation_allow_external` the search also covers the whole platform
        by name and email. The returned names are PII. Only an authorized caller
        may read them. With `delegator_id` the meeting lead gets the pool
        substitutes of that member for the lead entry, see
        `_lead_recipients`.

        Check the view rights before the recipient names are resolved. Escape the LIKE
        metacharacters, so a `%` or `_` from the user is no wildcard.

        Raises:
            NotFoundError: The meeting does not exist (404).
            ForbiddenError: The actor is not a member, a pool substitute or a
                manager of the meeting gremium, or the actor sends
                `delegator_id` and is not the meeting lead (403).
        """
        datetime.now(UTC)
        meeting = await self._meeting(meeting_id)
        gremium = await self._gremium(meeting.gremium_id)
        await self._assert_can_view_gremium(gremium.id, actor)
        if delegator_id is not None:
            return await self._lead_recipients(gremium.id, delegator_id, q, actor)
        me = await self._principal_row(sub=actor.sub)
        if me is None:
            return []
        needle = q.strip().lower()
        local = await self._candidates(gremium.id, me.id, needle)
        seen = {r.principal_id for r in local} | {me.id}
        external = (
            await self._external_recipients(needle, seen)
            if gremium.delegation_allow_external and needle
            else []
        )
        return sorted(
            (*local, *external),
            key=lambda r: (not r.via_pool, not r.is_member, (r.display_name or "").lower()),
        )[:20]

    async def _external_recipients(
        self, needle: str, seen: AbstractSet[UUID]
    ) -> list[RecipientOut]:
        """Search active principals by name and email, without the ones in `seen`."""
        pattern = f"%{_escape_like(needle)}%"
        rows = (
            await self.session.execute(
                select(PrincipalRow.id, PrincipalRow.display_name, PrincipalRow.email)
                .where(
                    PrincipalRow.active.is_(True),
                    or_(
                        PrincipalRow.display_name.ilike(pattern, escape="\\"),
                        PrincipalRow.email.ilike(pattern, escape="\\"),
                    ),
                )
                .limit(10)
            )
        ).all()
        return [
            RecipientOut(
                principal_id=pid,
                display_name=name or email,
                via_pool=False,
                is_member=False,
            )
            for pid, name, email in rows
            if pid not in seen
        ]

    async def _lead_recipients(
        self, gremium_id: UUID, delegator_id: UUID, q: str, actor: Principal
    ) -> list[RecipientOut]:
        """List the pool substitutes of a member for the lead entry.

        The list has the personal entries for the member and the gremium-wide
        entries, the same set that `_create_by_lead` accepts. The lead and the
        member are not in the list: the lead cannot name themselves, and a
        member cannot represent themselves.

        Raises:
            ForbiddenError: The actor is not the meeting lead (403).
        """
        if not await self._can_manage(gremium_id, actor):
            raise ForbiddenError("Only the meeting lead may list the substitutes of a member.")
        me = await self._principal_row(sub=actor.sub)
        excluded = {delegator_id} | ({me.id} if me is not None else set())
        pool_ids = await substitutes_for(self.session, gremium_id, delegator_id)
        ids = pool_ids - excluded
        member_ids = await self._member_ids(gremium_id)
        names = await self._names(ids)
        needle = q.strip().lower()
        return sorted(
            (
                RecipientOut(
                    principal_id=pid,
                    display_name=names.get(pid),
                    via_pool=True,
                    is_member=pid in member_ids,
                )
                for pid in ids
                if not needle or needle in (names.get(pid) or "").lower()
            ),
            key=lambda r: (r.display_name or "").lower(),
        )

    async def vote_status(self, vote_id: UUID, actor: Principal) -> VoteDelegationStatus:
        """Return the delegation view of one vote for the frontend banner.

        A pool seat does not block the member. A pool substitute without a voting
        delegation exercises the free seat that its represented ballot would take
        (`pool_seat_for`), so the ballot shows the proxy row for that member.
        """
        vote = await self.session.get(Vote, vote_id)
        if vote is None:
            raise NotFoundError(f"vote {vote_id} not found")
        empty = VoteDelegationStatus(blocked=False, exercising=False)
        if vote.meeting_id is None:
            return empty
        me = await self._principal_row(sub=actor.sub)
        if me is None:
            return empty
        try:
            gremium_id = UUID(vote.eligible_group)
        except (ValueError, TypeError):
            return empty
        delegate = aliased(PrincipalRow)
        rows = (
            await self.session.execute(
                select(MeetingDelegation, pool_seat_clause(delegate))
                .join(delegate, delegate.id == MeetingDelegation.delegate_principal_id)
                .where(
                    MeetingDelegation.meeting_id == vote.meeting_id,
                    MeetingDelegation.gremium_id == gremium_id,
                    MeetingDelegation.delegate_voting.is_(True),
                    or_(
                        MeetingDelegation.delegator_principal_id == me.id,
                        MeetingDelegation.delegate_principal_id == me.id,
                    ),
                )
            )
        ).all()
        incoming = [d.delegator_principal_id for d, _ in rows if d.delegator_principal_id != me.id]
        outgoing = [
            d.delegate_principal_id
            for d, seat in rows
            if d.delegator_principal_id == me.id and not seat
        ]
        free = (
            None
            if incoming
            else await pool_seat_for(self.session, actor.sub, vote.meeting_id, vote.eligible_group)
        )
        delegated_to = outgoing[-1] if outgoing else None
        delegated_by = incoming[-1] if incoming else (free.id if free is not None else None)
        names = await self._names({i for i in (delegated_to, delegated_by) if i})
        return VoteDelegationStatus(
            blocked=bool(outgoing),
            delegated_to_name=names.get(delegated_to) if delegated_to else None,
            exercising=bool(incoming) or free is not None,
            delegated_by_name=names.get(delegated_by) if delegated_by else None,
        )

    async def _require_pool_manage(self, gremium_id: UUID, actor: Principal) -> None:
        if actor.has(_ADMIN_PERM):
            return
        if not await holds_gremium_permission(self.session, actor, _POOL_MANAGE_PERM, gremium_id):
            raise ForbiddenError(
                "Managing the substitute pool requires admin.delegations "
                "or the gremium's session.manage permission."
            )

    async def substitutes_list(self, gremium_id: UUID, actor: Principal) -> list[SubstituteOut]:
        """List the substitute pool of a gremium.

        Only members, pool substitutes and managers of this gremium may read the
        pool. A manager holds `admin.delegations`, `meeting.view_all` or the
        gremium permission `session.manage`.

        Raises:
            NotFoundError: The gremium does not exist (404).
            ForbiddenError: The actor may not view this gremium (403).
        """
        await self._gremium(gremium_id)
        await self._assert_can_view_gremium(gremium_id, actor)
        rows = (
            (
                await self.session.execute(
                    select(DelegationSubstitute)
                    .where(DelegationSubstitute.gremium_id == gremium_id)
                    .order_by(DelegationSubstitute.created_at)
                )
            )
            .scalars()
            .all()
        )
        ids = {
            pid
            for r in rows
            for pid in (r.substitute_principal_id, r.member_principal_id)
            if pid is not None
        }
        names = await self._names(ids)
        return [
            SubstituteOut(
                id=r.id,
                gremium_id=r.gremium_id,
                member_id=r.member_principal_id,
                member_name=names.get(r.member_principal_id) if r.member_principal_id else None,
                substitute_id=r.substitute_principal_id,
                substitute_name=names.get(r.substitute_principal_id),
            )
            for r in rows
        ]

    async def substitute_create(self, payload: SubstituteCreate, actor: Principal) -> SubstituteOut:
        """Create a pool entry.

        The caller needs `admin.delegations` or `session.manage` for the gremium.
        """
        await self._require_pool_manage(payload.gremium_id, actor)
        await self._gremium(payload.gremium_id)
        substitute = await self._principal_row(pid=payload.substitute_id)
        if substitute is None:
            raise NotFoundError(f"principal {payload.substitute_id} not found")
        if payload.member_id is not None:
            member = await self._principal_row(pid=payload.member_id)
            if member is None:
                raise NotFoundError(f"principal {payload.member_id} not found")
            if member.id == substitute.id:
                raise ValidationProblem(
                    "Substitute must differ from the member.",
                    errors=[{"field": "substituteId", "msg": "must differ from member"}],
                )
        dup = (
            await self.session.execute(
                select(DelegationSubstitute.id).where(
                    DelegationSubstitute.gremium_id == payload.gremium_id,
                    DelegationSubstitute.substitute_principal_id == substitute.id,
                    DelegationSubstitute.member_principal_id.is_(None)
                    if payload.member_id is None
                    else DelegationSubstitute.member_principal_id == payload.member_id,
                )
            )
        ).first()
        if dup is not None:
            raise ConflictError("Substitute entry already exists.", code="substitute_exists")
        row = DelegationSubstitute(
            gremium_id=payload.gremium_id,
            member_principal_id=payload.member_id,
            substitute_principal_id=substitute.id,
            created_by=actor.sub,
        )
        self.session.add(row)
        await self.session.flush()
        await audit_record(
            self.session,
            actor=actor.sub,
            action=AuditAction.DELEGATION_SUBSTITUTE_ADD,
            target_type="delegation_substitute",
            target_id=str(row.id),
            data={
                "gremiumId": str(payload.gremium_id),
                "memberId": str(payload.member_id) if payload.member_id else None,
                "substituteId": str(substitute.id),
            },
        )
        await self.session.commit()
        names = await self._names(
            {substitute.id} | ({payload.member_id} if payload.member_id else set())
        )
        return SubstituteOut(
            id=row.id,
            gremium_id=row.gremium_id,
            member_id=row.member_principal_id,
            member_name=names.get(row.member_principal_id) if row.member_principal_id else None,
            substitute_id=row.substitute_principal_id,
            substitute_name=names.get(row.substitute_principal_id),
        )

    async def substitute_delete(self, substitute_id: UUID, actor: Principal) -> None:
        """Delete a pool entry with the same rights as for creating one."""
        row = await self.session.get(DelegationSubstitute, substitute_id)
        if row is None:
            raise NotFoundError(f"substitute {substitute_id} not found")
        await self._require_pool_manage(row.gremium_id, actor)
        await self.session.delete(row)
        await audit_record(
            self.session,
            actor=actor.sub,
            action=AuditAction.DELEGATION_SUBSTITUTE_REMOVE,
            target_type="delegation_substitute",
            target_id=str(substitute_id),
            data={"gremiumId": str(row.gremium_id)},
        )
        await self.session.commit()
