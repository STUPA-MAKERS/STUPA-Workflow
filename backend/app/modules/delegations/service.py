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
  Other users need `delegation_allow_external`, else 403.
* Deadline. A delegation from outside the pool runs until the meeting start minus
  `delegation_lead_minutes` of the gremium config. A pool delegation runs until
  the meeting start. The meeting must still be `planned`, else 422. A revocation
  runs until the meeting start.
* Transfer, not duplicate. Each (meeting, recipient) pair carries at most one
  vote delegation, else 409. The delegator cannot vote in that meeting. See
  `voting_delegation_check`. The audit log records every use.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from datetime import time as _time
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.admin.gremium_roles import gremium_ids_with_permission, gremium_member_ids
from app.modules.admin.models import Gremium, GremiumMembership, GremiumRole
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.models import GroupMapping, RoleAssignment
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.delegations.models import DelegationSubstitute, MeetingDelegation
from app.modules.delegations.schemas import (
    DelegationCreate,
    DelegationOut,
    DelegationUpdate,
    MeetingDelegationContext,
    RecipientOut,
    SubstituteCreate,
    SubstituteOut,
    VoteDelegationStatus,
)
from app.modules.livevote.models import Meeting
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
# Gremium-role permission that may manage the substitute pool.
_POOL_MANAGE_PERM = "session.manage"
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
    if meeting.date is None:
        return None
    local = datetime.combine(meeting.date, meeting.start_time or _time(0, 0))
    return local.replace(tzinfo=ZoneInfo(tz_name)).astimezone(UTC)


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

    The check uses the same sources as the RBAC resolver. These are a gremium role
    with `vote.cast`, a directly held gremium-scoped `role_assignment`, and an OIDC
    group, either direct or through `group_mapping`.
    """
    if await _membership_with_vote_cast(session, principal_id, gremium_id, now):
        return True
    direct = (
        await session.execute(
            select(RoleAssignment.id)
            .where(
                RoleAssignment.principal_id == principal_id,
                RoleAssignment.delegated_by.is_(None),
                RoleAssignment.gremium_id == gremium_id,
                (RoleAssignment.valid_from.is_(None)) | (RoleAssignment.valid_from <= now),
                (RoleAssignment.valid_until.is_(None)) | (RoleAssignment.valid_until > now),
            )
            .limit(1)
        )
    ).first()
    if direct is not None:
        return True
    row = (
        await session.execute(
            select(PrincipalRow.oidc_groups).where(PrincipalRow.id == principal_id)
        )
    ).first()
    oidc = {str(g) for g in ((row[0] if row else None) or [])}
    if str(gremium_id) in oidc:
        return True
    if not oidc:
        return False
    mapped = (
        await session.execute(
            select(GroupMapping.id)
            .where(
                GroupMapping.gremium_id == gremium_id,
                GroupMapping.oidc_group.in_(oidc),
            )
            .limit(1)
        )
    ).first()
    return mapped is not None


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

    async def _meeting(self, meeting_id: UUID) -> Meeting:
        meeting = await self.session.get(Meeting, meeting_id)
        if meeting is None:
            raise NotFoundError(f"meeting {meeting_id} not found")
        return meeting

    async def _gremium(self, gremium_id: UUID) -> Gremium:
        gremium = await self.session.get(Gremium, gremium_id)
        if gremium is None:
            raise NotFoundError(f"gremium {gremium_id} not found")
        return gremium

    async def _pool_substitute_ids(self, gremium_id: UUID, member_id: UUID) -> set[UUID]:
        """Return the pool recipients for `member_id`: personal and gremium-wide entries."""
        rows = (
            (
                await self.session.execute(
                    select(DelegationSubstitute.substitute_principal_id).where(
                        DelegationSubstitute.gremium_id == gremium_id,
                        or_(
                            DelegationSubstitute.member_principal_id.is_(None),
                            DelegationSubstitute.member_principal_id == member_id,
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        return set(rows)

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

    async def _pool_member_gremium_ids(self, sub: str) -> set[UUID]:
        """Return the Gremien whose substitute pool contains `sub`, for the self view."""
        pid_subq = select(PrincipalRow.id).where(PrincipalRow.sub == sub).scalar_subquery()
        rows = (
            await self.session.execute(
                select(DelegationSubstitute.gremium_id).where(
                    DelegationSubstitute.substitute_principal_id == pid_subq
                )
            )
        ).scalars().all()
        return set(rows)

    async def _assert_can_view_gremium(self, gremium_id: UUID, actor: Principal) -> None:
        """Guard the roster and the pool of a gremium against cross-tenant PII reads.

        Global readers and managers pass the guard. They hold the `admin` role,
        `admin.delegations`, `meeting.manage` or `meeting.view_all`. Members, the
        substitute pool and the holders of the `session.manage` role of this gremium
        also pass. They see the same data as in the meeting timeline.

        Raises:
            ForbiddenError: The actor may not view this gremium (403).
        """
        if (
            "admin" in actor.roles
            or actor.has(_ADMIN_PERM)
            or actor.has("meeting.manage")
            or actor.has("meeting.view_all")
        ):
            return
        if gremium_id in await gremium_member_ids(self.session, actor.sub):
            return
        if gremium_id in await self._pool_member_gremium_ids(actor.sub):
            return
        if gremium_id in await gremium_ids_with_permission(
            self.session, actor.sub, _POOL_MANAGE_PERM
        ):
            return
        raise ForbiddenError("Not allowed to view this gremium's delegation roster.")

    def _revocable(self, meeting: Meeting, now: datetime) -> bool:
        if meeting.status != "planned":
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
    ) -> list[DelegationOut]:
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
                revocable=self._revocable(meeting, now),
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

    def _check_gates(
        self, meeting: Meeting, gremium: Gremium, delegate_voting: bool
    ) -> None:
        """Enforce the gremium switch, the global vote-transfer flag and the meeting status."""
        if not gremium.allow_vote_delegation:
            raise ForbiddenError("Delegation is not enabled for this gremium.")
        if delegate_voting and not self.settings.delegation_voting_enabled:
            raise ValidationProblem(
                "Voting-right delegation is disabled.",
                errors=[{"field": "delegateVoting", "msg": "disabled by configuration"}],
            )
        if meeting.status != "planned":
            raise ValidationProblem(
                "Meeting has already started.",
                errors=[{"field": "meetingId", "msg": "meeting is not planned"}],
            )

    async def _check_recipient(
        self,
        *,
        meeting: Meeting,
        gremium: Gremium,
        delegator: PrincipalRow,
        delegate_id: UUID,
        now: datetime,
    ) -> tuple[PrincipalRow, bool]:
        """Run the recipient, eligibility and deadline rules of a delegation.

        `create` and `update` share this method, so both enforce the same
        invariants.

        Returns:
            The recipient row and the `via_pool` flag.
        """
        delegate = await self._principal_row(pid=delegate_id)
        if delegate is None:
            raise NotFoundError(f"principal {delegate_id} not found")
        if delegate.id == delegator.id:
            raise ValidationProblem(
                "Cannot delegate to yourself.",
                errors=[{"field": "delegateId", "msg": "must differ from delegator"}],
            )

        if not await _independently_eligible(self.session, delegator.id, gremium.id, now):
            raise ForbiddenError("Only voting members of the meeting's gremium may delegate.")

        pool_ids = await self._pool_substitute_ids(gremium.id, delegator.id)
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
        return delegate, via_pool

    async def _check_no_chain(
        self,
        *,
        meeting: Meeting,
        delegator_id: UUID,
        delegate_id: UUID,
        delegate_voting: bool,
        exclude_id: UUID | None = None,
    ) -> None:
        """Enforce the no-chain and one-voting-delegation rules for a meeting.

        `exclude_id` leaves the row that an update rewrites out of the scan, so
        it does not collide with itself.
        """
        # A transaction-scoped advisory lock serializes the write per meeting.
        # Without the lock, a concurrent insert of A to B and B to C could race the
        # read-then-insert check. The second int4 argument is a stable 32-bit
        # derivation of the meeting id.
        meeting_lock_arg = int.from_bytes(meeting.id.bytes[:4], "big") - 0x8000_0000
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:k1, :k2)").bindparams(
                k1=_CREATE_LOCK_KEY, k2=meeting_lock_arg
            )
        )
        stmt = select(
            MeetingDelegation.delegator_principal_id,
            MeetingDelegation.delegate_principal_id,
            MeetingDelegation.delegate_voting,
        ).where(MeetingDelegation.meeting_id == meeting.id)
        if exclude_id is not None:
            stmt = stmt.where(MeetingDelegation.id != exclude_id)
        existing = (await self.session.execute(stmt)).all()
        for other_delegator_id, other_delegate_id, voting in existing:
            if other_delegator_id == delegator_id:
                raise ConflictError("You already delegated for this meeting.", code="conflict")
            if other_delegate_id == delegator_id:
                raise ValidationProblem(
                    "You receive a delegation for this meeting and cannot delegate on.",
                    errors=[{"field": "meetingId", "msg": "no re-delegation chains"}],
                )
            if other_delegator_id == delegate_id:
                raise ValidationProblem(
                    "Recipient has delegated their own vote for this meeting.",
                    errors=[{"field": "delegateId", "msg": "no re-delegation chains"}],
                )
            if delegate_voting and voting and other_delegate_id == delegate_id:
                raise ConflictError(
                    "Recipient already carries a delegated vote for this meeting.",
                    code="conflict",
                )

    async def create(self, payload: DelegationCreate, actor: Principal) -> DelegationOut:
        """Create a meeting delegation.

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
        now = datetime.now(UTC)
        meeting = await self._meeting(payload.meeting_id)
        gremium = await self._gremium(meeting.gremium_id)
        self._check_gates(meeting, gremium, payload.delegate_voting)
        me = await self._principal_row(sub=actor.sub)
        if me is None:
            raise ForbiddenError("Delegator principal not found.")
        delegate, via_pool = await self._check_recipient(
            meeting=meeting,
            gremium=gremium,
            delegator=me,
            delegate_id=payload.delegate_id,
            now=now,
        )
        await self._check_no_chain(
            meeting=meeting,
            delegator_id=me.id,
            delegate_id=delegate.id,
            delegate_voting=payload.delegate_voting,
        )

        row = MeetingDelegation(
            meeting_id=meeting.id,
            gremium_id=gremium.id,
            delegator_principal_id=me.id,
            delegate_principal_id=delegate.id,
            delegate_voting=payload.delegate_voting,
            via_pool=via_pool,
            created_by=actor.sub,
        )
        self.session.add(row)
        await self.session.flush()
        await audit_record(
            self.session,
            actor=actor.sub,
            action=AuditAction.DELEGATION_GRANT,
            target_type="meeting_delegation",
            target_id=str(row.id),
            data={
                "meetingId": str(meeting.id),
                "gremiumId": str(gremium.id),
                "delegateId": str(delegate.id),
                "delegateVoting": payload.delegate_voting,
                "viaPool": via_pool,
            },
        )
        await self.session.commit()
        return (await self._out([(row, meeting, gremium)], now, me.id))[0]

    async def update(
        self, delegation_id: UUID, payload: DelegationUpdate, actor: Principal
    ) -> DelegationOut:
        """Change the recipient or the vote transfer of an existing delegation.

        The row keeps its identity, so the audit trail stays one thread instead
        of a revoke plus a create. Every invariant of `create` applies again,
        with the row itself left out of the chain scan.

        Raises:
            NotFoundError: The delegation or the new recipient does not exist (404).
            ForbiddenError: The actor is neither the delegator nor an admin, the
                gremium gate blocks the delegation, or the recipient is not
                eligible (403).
            ConflictError: The recipient already carries a delegated vote (409).
            ValidationProblem: The vote transfer is disabled, the meeting is not
                planned, the deadline has passed, the delegator picked
                themselves, or the change would build a chain (422).
        """
        now = datetime.now(UTC)
        row = await self.session.get(MeetingDelegation, delegation_id)
        if row is None:
            raise NotFoundError(f"delegation {delegation_id} not found")
        me = await self._principal_row(sub=actor.sub)
        is_owner = me is not None and row.delegator_principal_id == me.id
        if not is_owner and not actor.has(_ADMIN_PERM):
            raise ForbiddenError("Only the delegator (or an admin) may change a delegation.")

        meeting = await self._meeting(row.meeting_id)
        gremium = await self._gremium(meeting.gremium_id)
        delegate_voting = (
            row.delegate_voting if payload.delegate_voting is None else payload.delegate_voting
        )
        self._check_gates(meeting, gremium, delegate_voting)
        delegator = await self._principal_row(pid=row.delegator_principal_id)
        if delegator is None:
            raise ForbiddenError("Delegator principal not found.")
        delegate, via_pool = await self._check_recipient(
            meeting=meeting,
            gremium=gremium,
            delegator=delegator,
            delegate_id=payload.delegate_id or row.delegate_principal_id,
            now=now,
        )
        await self._check_no_chain(
            meeting=meeting,
            delegator_id=delegator.id,
            delegate_id=delegate.id,
            delegate_voting=delegate_voting,
            exclude_id=row.id,
        )

        row.delegate_principal_id = delegate.id
        row.delegate_voting = delegate_voting
        row.via_pool = via_pool
        await audit_record(
            self.session,
            actor=actor.sub,
            action=AuditAction.DELEGATION_UPDATE,
            target_type="meeting_delegation",
            target_id=str(row.id),
            data={
                "meetingId": str(meeting.id),
                "gremiumId": str(gremium.id),
                "delegateId": str(delegate.id),
                "delegateVoting": delegate_voting,
                "viaPool": via_pool,
            },
        )
        await self.session.commit()
        return (await self._out([(row, meeting, gremium)], now, me.id if me else None))[0]

    async def list(self, actor: Principal, meeting_id: UUID | None = None) -> list[DelegationOut]:
        """Return the own outgoing and incoming delegations.

        A holder of `admin.delegations` sees every delegation.
        """
        now = datetime.now(UTC)
        me = await self._principal_row(sub=actor.sub)
        where = []
        if meeting_id is not None:
            where.append(MeetingDelegation.meeting_id == meeting_id)
        if not actor.has(_ADMIN_PERM):
            if me is None:
                return []
            where.append(
                or_(
                    MeetingDelegation.delegator_principal_id == me.id,
                    MeetingDelegation.delegate_principal_id == me.id,
                )
            )
        return await self._out(await self._joined(*where), now, me.id if me else None)

    async def revoke(self, delegation_id: UUID, actor: Principal) -> None:
        """Revoke a delegation with a hard delete that takes effect at once.

        The delegator may revoke until the meeting starts, and only while the
        meeting is `planned`. An admin may revoke at any time.

        Raises:
            NotFoundError: The delegation does not exist (404).
            ForbiddenError: The actor is neither the delegator nor an admin (403).
            ValidationProblem: The meeting already started (422).
        """
        row = await self.session.get(MeetingDelegation, delegation_id)
        if row is None:
            raise NotFoundError(f"delegation {delegation_id} not found")
        me = await self._principal_row(sub=actor.sub)
        is_owner = me is not None and row.delegator_principal_id == me.id
        if not is_owner and not actor.has(_ADMIN_PERM):
            raise ForbiddenError("Only the delegator (or an admin) may revoke.")
        if not actor.has(_ADMIN_PERM):
            meeting = await self._meeting(row.meeting_id)
            if not self._revocable(meeting, datetime.now(UTC)):
                raise ValidationProblem(
                    "Meeting has already started; delegation can no longer be revoked.",
                    errors=[{"field": "id", "msg": "meeting started"}],
                )
        await self.session.delete(row)
        await audit_record(
            self.session,
            actor=actor.sub,
            action=AuditAction.DELEGATION_REVOKE,
            target_type="meeting_delegation",
            target_id=str(delegation_id),
            data={"meetingId": str(row.meeting_id)},
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
            pool_ids = await self._pool_substitute_ids(gremium.id, me.id)
            ids = (member_ids | pool_ids) - {me.id}
            names = await self._names(ids)
            recipients = sorted(
                (
                    RecipientOut(
                        principal_id=pid,
                        display_name=names.get(pid),
                        via_pool=pid in pool_ids,
                        is_member=pid in member_ids,
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

    async def recipients(self, meeting_id: UUID, q: str, actor: Principal) -> list[RecipientOut]:
        """List the eligible recipients for the typeahead.

        With `delegation_allow_external` the search also covers the whole platform
        by name and email. The returned names are PII. Only an authorized caller
        may read them.

        Raises:
            NotFoundError: The meeting does not exist (404).
            ForbiddenError: The actor is not a member, a pool substitute or a
                manager of the meeting gremium (403).
        """
        now = datetime.now(UTC)
        meeting = await self._meeting(meeting_id)
        gremium = await self._gremium(meeting.gremium_id)
        # Check the view rights before the code resolves the recipient names.
        await self._assert_can_view_gremium(gremium.id, actor)
        me = await self._principal_row(sub=actor.sub)
        if me is None:
            return []
        member_ids = await self._member_ids(gremium.id, now)
        pool_ids = await self._pool_substitute_ids(gremium.id, me.id)
        ids = (member_ids | pool_ids) - {me.id}
        names = await self._names(ids)
        needle = q.strip().lower()
        out = [
            RecipientOut(
                principal_id=pid,
                display_name=names.get(pid),
                via_pool=pid in pool_ids,
                is_member=pid in member_ids,
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
        allowed = await gremium_ids_with_permission(self.session, actor.sub, _POOL_MANAGE_PERM)
        if gremium_id not in allowed:
            raise ForbiddenError(
                "Managing the substitute pool requires admin.delegations "
                "or the gremium's session.manage permission."
            )

    async def substitutes_list(self, gremium_id: UUID, actor: Principal) -> list[SubstituteOut]:
        """List the substitute pool of a gremium.

        Only members, pool substitutes and managers of this gremium may read the
        pool. A manager holds `admin.delegations`, a `meeting.*` permission or
        `session.manage`.

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
