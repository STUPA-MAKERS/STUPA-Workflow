"""Delegation service and security core.

A delegation is meeting-bound and lives in `meeting_delegation`. Each (meeting,
member) pair has exactly one outgoing delegation. The gremium of the delegation
is the gremium of the meeting. A delegation can also carry the vote. That
transfer is exclusive and never a duplicate.

The server enforces these invariants:

* Feature gates. A meeting delegation needs the gremium flag
  `allow_vote_delegation`. `delegate_voting` also needs the global vote transfer
  `delegation_voting_enabled`, else 422.
* Own vote only. The delegator must be a voting member of the meeting gremium.
  The right comes from a gremium role with `vote.cast`, from a direct role
  assignment, or from an OIDC group mapping. Every other caller gets 403.
* No chains. Per meeting a principal is either delegator or recipient, never
  both, else 422.
* Recipient set. Gremium members and the substitute pool are always eligible.
  Other users need `delegation_allow_external`, else 403. The pool is the union
  of `delegation_substitute` and the faculty groups (Z5). The helpers in
  `delegations.pool` are its only source.
* Deadline. A delegation from outside the pool runs until the meeting start minus
  `delegation_lead_minutes` of the gremium config. A pool delegation runs until
  the meeting start. The meeting must still be `planned`, else 422. A revocation
  runs until the meeting start.
* Lead entry (O6). During a live meeting the meeting lead (`can_manage`) enters
  a substitution for a missing member (`delegatorId`). The delegate must be a
  substitute of the faculty group of that member. The lead can also revoke a
  delegation while the meeting is live. A ballot that the delegate already cast
  stays.
* Transfer, not duplicate. Each (meeting, recipient) pair carries at most one
  vote delegation, else 409. The delegator cannot vote in that meeting. See
  `voting_delegation_check`. The audit log records every use.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.admin.gremium_roles import admin_bypass, gremium_ids_for, gremium_member_ids
from app.modules.admin.models import Gremium, GremiumMembership, GremiumRole
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.delegations.models import (
    DelegationSubstitute,
    MeetingDelegation,
    SubstituteGroup,
    SubstituteGroupMember,
)
from app.modules.delegations.pool import (
    group_names_for,
    substitute_gremien_for_sub,
    substitutes_for,
)
from app.modules.delegations.schemas import (
    SUBSTITUTE_WARN_ABOVE,
    DelegationCreate,
    DelegationOut,
    MeetingDelegationContext,
    RecipientOut,
    SubstituteCreate,
    SubstituteGroupCreate,
    SubstituteGroupMemberCreate,
    SubstituteGroupMemberOut,
    SubstituteGroupOut,
    SubstituteGroupUpdate,
    SubstituteOut,
    VoteDelegationStatus,
)
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

# Permission that grants the view and the management of foreign delegations.
_ADMIN_PERM = "admin.delegations"
# Gremium-role permission that may manage the substitute pool. The same
# permission makes the meeting lead (`can_manage`), who enters a substitution
# during a live meeting (O6).
_POOL_MANAGE_PERM = "session.manage"
# Attendance states in which a member counts as missing (O6). No record counts
# as missing too.
_MISSING_STATES = frozenset({"excused", "absent"})
# Advisory-lock base key. It serializes the create per meeting, so a concurrent
# insert cannot race the read-then-insert check of the no-chains rule. The lock
# takes this key and a derivation of the meeting id as two int4 arguments.
_CREATE_LOCK_KEY = 0x4445_4C45  # "DELE"


def _escape_like(needle: str) -> str:
    """Neutralize the LIKE and ILIKE metacharacters in a user search term.

    Without the escape, `%` and `_` act as wildcards. The backslash is the escape
    character and needs an escape too. Call the result with
    `.ilike(pattern, escape=...)` and pass a single backslash as the escape.
    """
    return needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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
    session: AsyncSession, principal_id: UUID, gremium_id: UUID, now: datetime
) -> bool:
    """Report whether an active gremium membership grants `vote.cast`."""
    rows = (
        (
            await session.execute(
                select(GremiumRole.permissions)
                .select_from(GremiumMembership)
                .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
                .where(
                    GremiumMembership.principal_id == principal_id,
                    GremiumMembership.gremium_id == gremium_id,
                    (GremiumMembership.valid_from.is_(None))
                    | (GremiumMembership.valid_from <= now),
                    (GremiumMembership.valid_until.is_(None))
                    | (GremiumMembership.valid_until > now),
                )
            )
        )
        .scalars()
        .all()
    )
    return any("vote.cast" in (perms or []) for perms in rows)


async def _independently_eligible(
    session: AsyncSession, principal_id: UUID, gremium_id: UUID, now: datetime
) -> bool:
    """Report whether the principal can vote without any delegation.

    The check uses the same source as the cast gate of the voting module: an active
    gremium membership whose gremium role holds `vote.cast`. The membership comes from
    the OIDC groups through the gremium mappings. A global role or a raw OIDC group
    never gives the voting right in a gremium.
    """
    return await _membership_with_vote_cast(session, principal_id, gremium_id, now)


async def voting_delegation_check(
    session: AsyncSession,
    sub: str,
    meeting_id: UUID | None,
    eligible_group: str,
    now: datetime,  # noqa: ARG001 - signature consistency; delegations are session-bound
) -> tuple[bool, str | None]:
    """Give the two-sided vote verdict for `sub`.

    The verdict is meeting-bound. Only `meeting_delegation` rows of this meeting
    count. The gremium of the vote must match the gremium of the delegation, which
    means `eligible_group` equals `str(gremium_id)`. A vote without a meeting has
    no delegation.

    * An outgoing row with `delegate_voting` blocks the caller. The transfer lets
      only the recipient vote.
    * An incoming row with `delegate_voting` returns the `sub` of the delegator.
      The caller may then cast one delegated ballot next to the own ballot. That
      ballot runs under `delegator_sub`, so it is a transfer and not a duplicate.
      The caller can therefore vote even as an external user.

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
    rows = (
        await session.execute(
            select(
                MeetingDelegation.delegator_principal_id == pid_subq,
                MeetingDelegation.delegate_voting,
                delegator.sub,
            )
            .join(
                delegator,
                delegator.id == MeetingDelegation.delegator_principal_id,
            )
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


class DelegationService:
    """Delegation service bound to an `AsyncSession` and a `Settings` object."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def _principal_row(
        self, *, sub: str | None = None, pid: UUID | None = None
    ) -> PrincipalRow | None:
        stmt = select(PrincipalRow)
        stmt = (
            stmt.where(PrincipalRow.sub == sub)
            if sub is not None
            else stmt.where(PrincipalRow.id == pid)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _names(self, ids: set[UUID]) -> dict[UUID, str | None]:
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
        and an attendance change run one after the other (O23).

        Raises:
            NotFoundError: No meeting has this id (404).
        """
        if lock:
            meeting = await self.session.get(
                Meeting, meeting_id, with_for_update=True, populate_existing=True
            )
        else:
            meeting = await self.session.get(Meeting, meeting_id)
        if meeting is None:
            raise NotFoundError(f"meeting {meeting_id} not found")
        return meeting

    async def _gremium(self, gremium_id: UUID) -> Gremium:
        gremium = await self.session.get(Gremium, gremium_id)
        if gremium is None:
            raise NotFoundError(f"gremium {gremium_id} not found")
        return gremium

    async def _member_ids(self, gremium_id: UUID, now: datetime) -> set[UUID]:
        """Return the active gremium members with any role."""
        rows = (
            (
                await self.session.execute(
                    select(GremiumMembership.principal_id).where(
                        GremiumMembership.gremium_id == gremium_id,
                        (GremiumMembership.valid_from.is_(None))
                        | (GremiumMembership.valid_from <= now),
                        (GremiumMembership.valid_until.is_(None))
                        | (GremiumMembership.valid_until > now),
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
        if gremium_id in await gremium_ids_for(self.session, actor, _POOL_MANAGE_PERM):
            return
        raise ForbiddenError("Not allowed to view this gremium's delegation roster.")

    async def _can_manage(self, gremium_id: UUID, actor: Principal) -> bool:
        """Check for the meeting lead: gremium `session.manage` or the admin role.

        This is the same rule as `PermissionOps.can_manage` of the meeting module.
        The scope cap applies to both paths.
        """
        if admin_bypass(actor, _POOL_MANAGE_PERM):
            return True
        return gremium_id in await gremium_ids_for(self.session, actor, _POOL_MANAGE_PERM)

    def _revocable(
        self, meeting: Meeting, now: datetime, *, lead: bool = False, own: bool = True
    ) -> bool:
        """Tell if the viewer can revoke a delegation of this meeting.

        The delegator can revoke while the meeting is planned and has not started.
        The meeting lead (`lead`) can also revoke while the meeting is live (O6).
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
        lead_gremien: set[UUID] | None = None,
        *,
        admin: bool = False,
    ) -> list[DelegationOut]:
        """Build the views.

        `lead_gremien` holds the gremien that the viewer leads. `admin` tells that
        the viewer may revoke every row.
        """
        lead_gremien = lead_gremien or set()
        ids: set[UUID] = set()
        for d, _, _ in rows:
            ids.add(d.delegator_principal_id)
            ids.add(d.delegate_principal_id)
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
                # For a fresh row the database default fills `created_at` only on
                # the next select. Use the creation time until then.
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

    async def _joined(self, *where) -> list[tuple[MeetingDelegation, Meeting, Gremium]]:  # noqa: ANN002
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
        missing member while the meeting is live (O6). See `_create_by_lead`.

        Raises:
            ForbiddenError: The gremium gate blocks the delegation, the recipient
                is not eligible, or the delegator may not vote (403).
            NotFoundError: The meeting or the recipient does not exist (404).
            ConflictError: The delegator already delegated for this meeting, or the
                recipient already carries a delegated vote (409).
            ValidationProblem: The vote transfer is disabled, the meeting is not
                planned, the deadline has passed, the delegator picked themselves,
                or the delegation would build a chain (422).
        """
        if payload.delegator_id is not None:
            return await self._create_by_lead(payload, payload.delegator_id, actor)
        now = datetime.now(UTC)
        meeting = await self._meeting(payload.meeting_id)
        gremium = await self._gremium(meeting.gremium_id)

        if not gremium.allow_vote_delegation:
            raise ForbiddenError("Delegation is not enabled for this gremium.")
        self._check_voting_enabled(payload)
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

        if not await _independently_eligible(self.session, me.id, gremium.id, now):
            raise ForbiddenError("Only voting members of the meeting's gremium may delegate.")

        pool_ids = await substitutes_for(self.session, gremium.id, me.id, now)
        member_ids = await self._member_ids(gremium.id, now)
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

    def _check_voting_enabled(self, payload: DelegationCreate) -> None:
        """Refuse a vote transfer while the global switch is off (422)."""
        if payload.delegate_voting and not self.settings.delegation_voting_enabled:
            raise ValidationProblem(
                "Voting-right delegation is disabled.",
                errors=[{"field": "delegateVoting", "msg": "disabled by configuration"}],
            )

    async def _create_by_lead(
        self, payload: DelegationCreate, delegator_id: UUID, actor: Principal
    ) -> DelegationOut:
        """Enter a substitution for a missing member during a live meeting (O6).

        The meeting lead (`can_manage`) names the missing member A (`delegatorId`)
        and a substitute B from the pool of the gremium for A: a personal entry
        for A or a gremium-wide entry. The faculty groups do not count. The
        checks are the same as
        before the meeting: the gremium allows delegations, A may vote, the vote
        transfer switch, and no chains. A is missing when A has no attendance
        record, or the record is `excused` or `absent`. The lead cannot name
        themselves as B. The row stores the lead as `created_by` and
        `via_pool = true`.

        Raises:
            ForbiddenError: The caller is not the meeting lead, the gremium does not
                allow delegations, B is the lead, A may not vote, or B is not in
                the pool for A (403).
            NotFoundError: The meeting, A or B does not exist (404).
            ConflictError: A already has a delegation, or B already carries a
                delegated vote (409).
            ValidationProblem: The vote transfer is disabled, the meeting is not
                live, A and B are the same person, A is present, or the
                delegation would build a chain (422).
        """
        now = datetime.now(UTC)
        meeting = await self._meeting(payload.meeting_id)
        gremium = await self._gremium(meeting.gremium_id)
        if not await self._can_manage(gremium.id, actor):
            raise ForbiddenError(
                "Only the meeting lead may enter a substitution for another member."
            )
        # Lock the meeting row before the status and attendance reads. The
        # attendance writers hold a share lock on this row and then look for a
        # delegation. Thus a `present` report of A and this entry for A cannot
        # both commit (O23).
        meeting = await self._meeting(payload.meeting_id, lock=True)
        if not gremium.allow_vote_delegation:
            raise ForbiddenError("Delegation is not enabled for this gremium.")
        self._check_voting_enabled(payload)
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
            # The missing member does not consent to this entry. Thus the lead
            # must not give the vote to themselves.
            raise ForbiddenError("The meeting lead cannot name themselves as the substitute.")
        if not await _independently_eligible(self.session, delegator.id, gremium.id, now):
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
        if delegate.id not in await substitutes_for(
            self.session, gremium.id, delegator.id, now, include_groups=False
        ):
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

        Raises:
            ConflictError: The delegator already delegated for this meeting, or the
                recipient already carries a delegated vote (409).
            ValidationProblem: The delegation would build a chain (422).
        """
        # No chains: per meeting a principal is either delegator or recipient. A
        # transaction-scoped advisory lock serializes the insert per meeting.
        # Without the lock, a concurrent insert of A to B and B to C could race the
        # read-then-insert check. The second int4 argument is a stable 32-bit
        # derivation of the meeting id.
        meeting_lock_arg = int.from_bytes(meeting.id.bytes[:4], "big") - 0x8000_0000
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:k1, :k2)").bindparams(
                k1=_CREATE_LOCK_KEY, k2=meeting_lock_arg
            )
        )
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
                    "The member already delegated for this meeting.", code="conflict"
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
                    code="conflict",
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
        }
        if by_lead:
            data["delegatorId"] = str(delegator.id)
            data["byLead"] = True
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
        the lead can revoke one during the live meeting (O6).
        """
        now = datetime.now(UTC)
        me = await self._principal_row(sub=actor.sub)
        where = []
        lead_gremien: set[UUID] = set()
        sees_all = actor.has(_ADMIN_PERM)
        if meeting_id is not None:
            where.append(MeetingDelegation.meeting_id == meeting_id)
            meeting = await self.session.get(Meeting, meeting_id)
            if meeting is not None and await self._can_manage(meeting.gremium_id, actor):
                lead_gremien.add(meeting.gremium_id)
                sees_all = True
        if not sees_all:
            if me is None:
                return []
            where.append(
                or_(
                    MeetingDelegation.delegator_principal_id == me.id,
                    MeetingDelegation.delegate_principal_id == me.id,
                )
            )
        return await self._out(
            await self._joined(*where),
            now,
            me.id if me else None,
            lead_gremien,
            admin=actor.has(_ADMIN_PERM),
        )

    async def revoke(self, delegation_id: UUID, actor: Principal) -> None:
        """Revoke a delegation with a hard delete that takes effect at once.

        The delegator may revoke until the meeting starts, and only while the
        meeting is `planned`. The meeting lead (`can_manage`) may revoke while the
        meeting is `live` (O6), for example when the substituted member arrives.
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
        by_lead = False
        if not actor.has(_ADMIN_PERM):
            meeting = await self._meeting(row.meeting_id)
            by_lead = meeting.status == "live" and await self._can_manage(
                meeting.gremium_id, actor
            )
            if not by_lead:
                me = await self._principal_row(sub=actor.sub)
                if me is None or row.delegator_principal_id != me.id:
                    raise ForbiddenError(
                        "Only the delegator, the meeting lead of a live meeting, "
                        "or an admin may revoke."
                    )
                if not self._revocable(meeting, datetime.now(UTC)):
                    raise ValidationProblem(
                        "Meeting has already started; delegation can no longer be revoked.",
                        errors=[{"field": "id", "msg": "meeting started"}],
                    )
        data: dict[str, str | bool] = {"meetingId": str(row.meeting_id)}
        if by_lead:
            data["delegatorId"] = str(row.delegator_principal_id)
            data["byLead"] = True
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

    async def meeting_context(self, meeting_id: UUID, actor: Principal) -> MeetingDelegationContext:
        """Build the context for the set-up-delegation dialog of a meeting.

        The roster and the recipient names are PII and must not leak to outsiders.

        Raises:
            NotFoundError: The meeting does not exist (404).
            ForbiddenError: The actor is not a member, a pool substitute or a
                manager of the meeting gremium (403).
        """
        now = datetime.now(UTC)
        meeting = await self._meeting(meeting_id)
        gremium = await self._gremium(meeting.gremium_id)
        # Check the view rights before the code builds the roster and the PII.
        await self._assert_can_view_gremium(gremium.id, actor)
        me = await self._principal_row(sub=actor.sub)

        start = meeting_start_utc(meeting, self.settings.local_timezone)
        deadline = (
            start - timedelta(minutes=gremium.delegation_lead_minutes)
            if start is not None
            else None
        )
        meeting_started = meeting.status != "planned" or (start is not None and now >= start)

        my_delegation: DelegationOut | None = None
        incoming: list[DelegationOut] = []
        recipients: list[RecipientOut] = []
        can_delegate = False
        if me is not None:
            can_delegate = gremium.allow_vote_delegation and await _independently_eligible(
                self.session, me.id, gremium.id, now
            )
            rows = await self._joined(
                MeetingDelegation.meeting_id == meeting.id,
                or_(
                    MeetingDelegation.delegator_principal_id == me.id,
                    MeetingDelegation.delegate_principal_id == me.id,
                ),
            )
            outs = await self._out(rows, now, me.id)
            for (d, _, _), out in zip(rows, outs, strict=True):
                if d.delegator_principal_id == me.id:
                    my_delegation = out
                else:
                    incoming.append(out)

            member_ids = await self._member_ids(gremium.id, now)
            pool_ids = await substitutes_for(self.session, gremium.id, me.id, now)
            ids = (member_ids | pool_ids) - {me.id}
            names = await self._names(ids)
            groups = await group_names_for(self.session, gremium.id, ids, member_id=me.id)
            recipients = sorted(
                (
                    RecipientOut(
                        principal_id=pid,
                        display_name=names.get(pid),
                        via_pool=pid in pool_ids,
                        is_member=pid in member_ids,
                        substitute_group_name=groups.get(pid),
                    )
                    for pid in ids
                ),
                key=lambda r: (not r.via_pool, (r.display_name or "").lower()),
            )

        return MeetingDelegationContext(
            meeting_id=meeting.id,
            gremium_id=gremium.id,
            allow_vote_delegation=gremium.allow_vote_delegation,
            voting_delegation_enabled=self.settings.delegation_voting_enabled,
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
        substitutes of that member for the lead entry (O6), see
        `_lead_recipients`.

        Raises:
            NotFoundError: The meeting does not exist (404).
            ForbiddenError: The actor is not a member, a pool substitute or a
                manager of the meeting gremium, or the actor sends
                `delegator_id` and is not the meeting lead (403).
        """
        now = datetime.now(UTC)
        meeting = await self._meeting(meeting_id)
        gremium = await self._gremium(meeting.gremium_id)
        # Check the view rights before the code resolves the recipient names.
        await self._assert_can_view_gremium(gremium.id, actor)
        if delegator_id is not None:
            return await self._lead_recipients(gremium.id, delegator_id, q, actor, now)
        me = await self._principal_row(sub=actor.sub)
        if me is None:
            return []
        member_ids = await self._member_ids(gremium.id, now)
        pool_ids = await substitutes_for(self.session, gremium.id, me.id, now)
        ids = (member_ids | pool_ids) - {me.id}
        names = await self._names(ids)
        groups = await group_names_for(self.session, gremium.id, ids, member_id=me.id)
        needle = q.strip().lower()
        out = [
            RecipientOut(
                principal_id=pid,
                display_name=names.get(pid),
                via_pool=pid in pool_ids,
                is_member=pid in member_ids,
                substitute_group_name=groups.get(pid),
            )
            for pid in ids
            if not needle or needle in (names.get(pid) or "").lower()
        ]
        if gremium.delegation_allow_external and needle:
            # Escape the LIKE metacharacters, so a `%` or `_` from the user is no
            # wildcard.
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
            seen = {r.principal_id for r in out} | {me.id}
            out.extend(
                RecipientOut(
                    principal_id=pid,
                    display_name=name or email,
                    via_pool=False,
                    is_member=False,
                )
                for pid, name, email in rows
                if pid not in seen
            )
        out.sort(key=lambda r: (not r.via_pool, not r.is_member, (r.display_name or "").lower()))
        return out[:20]

    async def _lead_recipients(
        self, gremium_id: UUID, delegator_id: UUID, q: str, actor: Principal, now: datetime
    ) -> list[RecipientOut]:
        """List the pool substitutes of a member for the lead entry (O6).

        The list has the personal entries for the member and the gremium-wide
        entries, the same set that `_create_by_lead` accepts. It does not read the
        faculty groups. The lead and the member are not in the list: the lead
        cannot name themselves, and a member cannot represent themselves.

        Raises:
            ForbiddenError: The actor is not the meeting lead (403).
        """
        if not await self._can_manage(gremium_id, actor):
            raise ForbiddenError("Only the meeting lead may list the substitutes of a member.")
        me = await self._principal_row(sub=actor.sub)
        excluded = {delegator_id} | ({me.id} if me is not None else set())
        pool_ids = await substitutes_for(
            self.session, gremium_id, delegator_id, now, include_groups=False
        )
        ids = pool_ids - excluded
        member_ids = await self._member_ids(gremium_id, now)
        names = await self._names(ids)
        needle = q.strip().lower()
        out = [
            RecipientOut(
                principal_id=pid,
                display_name=names.get(pid),
                via_pool=True,
                is_member=pid in member_ids,
            )
            for pid in ids
            if not needle or needle in (names.get(pid) or "").lower()
        ]
        out.sort(key=lambda r: (r.display_name or "").lower())
        return out

    async def vote_status(self, vote_id: UUID, actor: Principal) -> VoteDelegationStatus:
        """Return the delegation view of one vote for the frontend banner."""
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
        rows = (
            (
                await self.session.execute(
                    select(MeetingDelegation).where(
                        MeetingDelegation.meeting_id == vote.meeting_id,
                        MeetingDelegation.gremium_id == gremium_id,
                        MeetingDelegation.delegate_voting.is_(True),
                        or_(
                            MeetingDelegation.delegator_principal_id == me.id,
                            MeetingDelegation.delegate_principal_id == me.id,
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        blocked = False
        exercising = False
        delegated_to: UUID | None = None
        delegated_by: UUID | None = None
        for d in rows:
            if d.delegator_principal_id == me.id:
                blocked = True
                delegated_to = d.delegate_principal_id
            else:
                exercising = True
                delegated_by = d.delegator_principal_id
        names = await self._names({i for i in (delegated_to, delegated_by) if i})
        return VoteDelegationStatus(
            blocked=blocked,
            delegated_to_name=names.get(delegated_to) if delegated_to else None,
            exercising=exercising,
            delegated_by_name=names.get(delegated_by) if delegated_by else None,
        )

    async def _require_pool_manage(self, gremium_id: UUID, actor: Principal) -> None:
        if actor.has(_ADMIN_PERM):
            return
        allowed = await gremium_ids_for(self.session, actor, _POOL_MANAGE_PERM)
        if gremium_id not in allowed:
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
        ids: set[UUID] = set()
        for r in rows:
            ids.add(r.substitute_principal_id)
            if r.member_principal_id is not None:
                ids.add(r.member_principal_id)
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
            raise ConflictError("Substitute entry already exists.", code="conflict")
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

    # ------------------------------------------------------------------
    # Faculty substitute groups (Z5)
    # ------------------------------------------------------------------

    async def _group(self, group_id: UUID) -> SubstituteGroup:
        group = await self.session.get(SubstituteGroup, group_id)
        if group is None:
            raise NotFoundError(f"substitute group {group_id} not found")
        return group

    async def _groups_out(self, groups: list[SubstituteGroup]) -> list[SubstituteGroupOut]:
        """Build the group views with the members, the names and the warning flag."""
        if not groups:
            return []
        rows = (
            (
                await self.session.execute(
                    select(SubstituteGroupMember)
                    .where(SubstituteGroupMember.group_id.in_([g.id for g in groups]))
                    .order_by(SubstituteGroupMember.created_at)
                )
            )
            .scalars()
            .all()
        )
        names = await self._names({r.principal_id for r in rows})
        now = datetime.now(UTC)
        active: dict[UUID, set[UUID]] = {}
        for gremium_id in {g.gremium_id for g in groups}:
            active[gremium_id] = await self._member_ids(gremium_id, now)
        out: list[SubstituteGroupOut] = []
        for group in groups:
            members = [
                SubstituteGroupMemberOut(
                    principal_id=r.principal_id,
                    display_name=names.get(r.principal_id),
                    kind="member" if r.kind == "member" else "substitute",
                    active=r.kind != "member" or r.principal_id in active[group.gremium_id],
                )
                for r in rows
                if r.group_id == group.id
            ]
            substitutes = sum(1 for m in members if m.kind == "substitute")
            out.append(
                SubstituteGroupOut(
                    id=group.id,
                    gremium_id=group.gremium_id,
                    name_i18n=dict(group.name_i18n or {}),
                    position=group.position,
                    members=members,
                    too_many_substitutes=substitutes > SUBSTITUTE_WARN_ABOVE,
                )
            )
        return out

    async def _group_out(self, group: SubstituteGroup) -> SubstituteGroupOut:
        return (await self._groups_out([group]))[0]

    async def substitute_groups_list(
        self, gremium_id: UUID, actor: Principal
    ) -> list[SubstituteGroupOut]:
        """List the faculty groups of a gremium with their members (Z5).

        The same readers as for the substitute pool may read the groups.

        Raises:
            NotFoundError: The gremium does not exist (404).
            ForbiddenError: The actor may not view this gremium (403).
        """
        await self._gremium(gremium_id)
        await self._assert_can_view_gremium(gremium_id, actor)
        groups = (
            (
                await self.session.execute(
                    select(SubstituteGroup)
                    .where(SubstituteGroup.gremium_id == gremium_id)
                    .order_by(SubstituteGroup.position, SubstituteGroup.created_at)
                )
            )
            .scalars()
            .all()
        )
        return await self._groups_out(list(groups))

    async def substitute_group_create(
        self, payload: SubstituteGroupCreate, actor: Principal
    ) -> SubstituteGroupOut:
        """Create a faculty group in a gremium.

        The caller needs `admin.delegations` or `session.manage` for the gremium.
        The audit log records `delegation_substitute_add`.

        Raises:
            ForbiddenError: The actor may not manage the pool of the gremium (403).
            NotFoundError: The gremium does not exist (404).
        """
        await self._require_pool_manage(payload.gremium_id, actor)
        await self._gremium(payload.gremium_id)
        group = SubstituteGroup(
            gremium_id=payload.gremium_id,
            name_i18n=payload.name_i18n,
            position=payload.position,
            created_by=actor.sub,
        )
        self.session.add(group)
        await self.session.flush()
        await audit_record(
            self.session,
            actor=actor.sub,
            action=AuditAction.DELEGATION_SUBSTITUTE_ADD,
            target_type="substitute_group",
            target_id=str(group.id),
            data={"gremiumId": str(payload.gremium_id)},
        )
        await self.session.commit()
        return await self._group_out(group)

    async def substitute_group_update(
        self, group_id: UUID, payload: SubstituteGroupUpdate, actor: Principal
    ) -> SubstituteGroupOut:
        """Change the name or the position of a faculty group.

        The change does not change who may represent whom, so it writes no audit
        entry.

        Raises:
            NotFoundError: The group does not exist (404).
            ForbiddenError: The actor may not manage the pool of the gremium (403).
        """
        group = await self._group(group_id)
        await self._require_pool_manage(group.gremium_id, actor)
        if payload.name_i18n is not None:
            group.name_i18n = payload.name_i18n
        if payload.position is not None:
            group.position = payload.position
        await self.session.commit()
        return await self._group_out(group)

    async def substitute_group_delete(self, group_id: UUID, actor: Principal) -> None:
        """Delete a faculty group with its members and substitutes.

        Existing delegations stay. The audit log records
        `delegation_substitute_remove` with the ids of the people in the group.

        Raises:
            NotFoundError: The group does not exist (404).
            ForbiddenError: The actor may not manage the pool of the gremium (403).
        """
        group = await self._group(group_id)
        await self._require_pool_manage(group.gremium_id, actor)
        rows = (
            await self.session.execute(
                select(SubstituteGroupMember.principal_id, SubstituteGroupMember.kind).where(
                    SubstituteGroupMember.group_id == group.id
                )
            )
        ).all()
        await audit_record(
            self.session,
            actor=actor.sub,
            action=AuditAction.DELEGATION_SUBSTITUTE_REMOVE,
            target_type="substitute_group",
            target_id=str(group.id),
            data={
                "gremiumId": str(group.gremium_id),
                "memberIds": sorted(str(pid) for pid, kind in rows if kind == "member"),
                "substituteIds": sorted(str(pid) for pid, kind in rows if kind != "member"),
            },
        )
        await self.session.delete(group)
        await self.session.commit()

    async def substitute_group_member_add(
        self, group_id: UUID, payload: SubstituteGroupMemberCreate, actor: Principal
    ) -> SubstituteGroupOut:
        """Add a person to a faculty group as a member or as a substitute.

        A member is in at most one group per gremium. A substitute may be in more
        than one group. A member counts only while the gremium membership is
        active, so the call accepts a person without a membership. There is no
        limit of substitutes: the response sets `tooManySubstitutes` above two.
        The audit log records `delegation_substitute_add`.

        Raises:
            NotFoundError: The group or the principal does not exist (404).
            ForbiddenError: The actor may not manage the pool of the gremium (403).
            ConflictError: The person is already in this group, or is already a
                member of another group of the gremium (409).
        """
        group = await self._group(group_id)
        await self._require_pool_manage(group.gremium_id, actor)
        principal = await self._principal_row(pid=payload.principal_id)
        if principal is None:
            raise NotFoundError(f"principal {payload.principal_id} not found")
        in_group = await self.session.get(
            SubstituteGroupMember, {"group_id": group.id, "principal_id": principal.id}
        )
        if in_group is not None:
            raise ConflictError("The person is already in this group.", code="conflict")
        if payload.kind == "member":
            other = await self.session.scalar(
                select(SubstituteGroupMember.group_id).where(
                    SubstituteGroupMember.gremium_id == group.gremium_id,
                    SubstituteGroupMember.principal_id == principal.id,
                    SubstituteGroupMember.kind == "member",
                )
            )
            if other is not None:
                raise ConflictError(
                    "The person is already a member of another group of this gremium.",
                    code="conflict",
                )
        self.session.add(
            SubstituteGroupMember(
                group_id=group.id,
                principal_id=principal.id,
                gremium_id=group.gremium_id,
                kind=payload.kind,
                created_by=actor.sub,
            )
        )
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(
                "Another change of this group ran at the same time. Try again.",
                code="conflict",
            ) from exc
        await audit_record(
            self.session,
            actor=actor.sub,
            action=AuditAction.DELEGATION_SUBSTITUTE_ADD,
            target_type="substitute_group_member",
            target_id=str(group.id),
            data={
                "gremiumId": str(group.gremium_id),
                "groupId": str(group.id),
                "principalId": str(principal.id),
                "kind": payload.kind,
            },
        )
        await self.session.commit()
        return await self._group_out(group)

    async def substitute_group_member_remove(
        self, group_id: UUID, principal_id: UUID, actor: Principal
    ) -> None:
        """Remove a person from a faculty group.

        Existing delegations stay. The audit log records
        `delegation_substitute_remove`.

        Raises:
            NotFoundError: The group does not exist, or the person is not in it (404).
            ForbiddenError: The actor may not manage the pool of the gremium (403).
        """
        group = await self._group(group_id)
        await self._require_pool_manage(group.gremium_id, actor)
        row = await self.session.get(
            SubstituteGroupMember, {"group_id": group.id, "principal_id": principal_id}
        )
        if row is None:
            raise NotFoundError(f"principal {principal_id} is not in group {group_id}")
        await audit_record(
            self.session,
            actor=actor.sub,
            action=AuditAction.DELEGATION_SUBSTITUTE_REMOVE,
            target_type="substitute_group_member",
            target_id=str(group.id),
            data={
                "gremiumId": str(group.gremium_id),
                "groupId": str(group.id),
                "principalId": str(principal_id),
                "kind": row.kind,
            },
        )
        await self.session.delete(row)
        await self.session.commit()
