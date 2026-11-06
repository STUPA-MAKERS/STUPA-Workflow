"""Pool seats: a pool substitute votes for a missing member without a delegation.

A substitute in the pool of a gremium may take the seat of a member that the pool
entries let it represent. Nobody announces or enters this beforehand. The first
represented ballot of the substitute in a meeting claims the seat: it stores a
meeting delegation from the member to the substitute with `via_pool`,
`delegate_voting` and `created_by` = the `sub` of the substitute. That last value
marks the row as a pool seat (`pool_seat_clause`). From then on the normal
delegation rules apply: the represented ballot runs under the `sub` of the member,
so each seat takes one ballot per vote. The members and their substitutes together
therefore never cast more ballots than the members have seats. With two members A
and B and two substitutes X and Y for both, at most two of the four vote.

A member is missing while the member is not checked in: no attendance record, or a
record `excused` or `absent`. This is the rule of the lead entry. A pool seat never
blocks the member. A check-in of the member or an own ballot of the member frees the
seat (`release_pool_seat`). A ballot that the substitute already cast for the member
stays, so the member gets 409 in that vote.

The only gate is a live meeting of the gremium of the vote. The pool entries are the
rule that the gremium keeps for its substitutes, so the delegation switch of the
gremium (`allow_vote_delegation`) does not apply: it governs the free transfers
between members. No chains: a substitute who
delegated the own vote, or who already holds a voting delegation in the meeting,
claims no further seat. A member who holds or gives a delegation in the meeting has
no free seat.

The claim takes the advisory lock of the delegation create, so two parallel claims
cannot take the same seat. It does not lock the meeting row, because the caller
holds the vote row and the lock order is meeting row first. A check-in that races
a claim leaves a seat for a present member, and the next own ballot or check-in of
that member frees it.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import ColumnElement, and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.admin.models import GremiumMembership, GremiumRole
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.delegations.models import MeetingDelegation
from app.modules.delegations.pool import members_for_substitute
from app.modules.livevote.models import Meeting, MeetingAttendance

#: Advisory-lock base key. It serializes the delegation writes per meeting, so a
#: concurrent insert cannot race the read-then-insert check of the no-chains rule
#: or take the same seat. The lock takes this key and a derivation of the meeting
#: id as two int4 arguments. The value spells "DELE" in ASCII.
_CREATE_LOCK_KEY = 0x4445_4C45


async def lock_meeting_delegations(session: AsyncSession, meeting_id: UUID) -> None:
    """Take the transaction-bound advisory lock of the delegation writes of a meeting.

    The second int4 argument is a stable 32-bit derivation of the meeting id.
    """
    lock_arg = int.from_bytes(meeting_id.bytes[:4], "big") - 0x8000_0000
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:k1, :k2)").bindparams(k1=_CREATE_LOCK_KEY, k2=lock_arg)
    )


def pool_seat_clause(delegate: type[PrincipalRow]) -> ColumnElement[bool]:
    """Match a delegation row that a pool substitute claimed for itself.

    `delegate` is an alias of `principal` joined on the delegate of the row. The
    clause is never NULL, so its negation is safe for a row without `created_by`.
    """
    return and_(
        MeetingDelegation.via_pool.is_(True),
        MeetingDelegation.created_by.is_not_distinct_from(delegate.sub),
    )


def _gremium_of(eligible_group: str) -> UUID | None:
    """Return the gremium id of a vote, or None for an old free group key."""
    try:
        return UUID(eligible_group)
    except (ValueError, TypeError):
        return None


async def _meeting_live(session: AsyncSession, meeting_id: UUID, gremium_id: UUID) -> bool:
    """Tell whether the meeting is live and belongs to the gremium of the vote."""
    meeting = await session.get(Meeting, meeting_id)
    return meeting is not None and meeting.status == "live" and meeting.gremium_id == gremium_id


async def _voting_member_ids(session: AsyncSession, gremium_id: UUID) -> set[UUID]:
    """Return the members whose gremium role holds `vote.cast`."""
    rows = (
        await session.execute(
            select(GremiumMembership.principal_id, GremiumRole.permissions)
            .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
            .where(
                GremiumMembership.gremium_id == gremium_id,
            )
        )
    ).all()
    return {pid for pid, perms in rows if "vote.cast" in (perms or [])}


async def _find_seat(
    session: AsyncSession,
    sub: str,
    meeting_id: UUID | None,
    eligible_group: str,
) -> tuple[PrincipalRow, PrincipalRow] | None:
    """Return the substitute and the first free seat it may take, or None.

    The personal entries come before the gremium-wide entry, then the name orders
    the members, so the pick is stable.
    """
    if meeting_id is None:
        return None
    gremium_id = _gremium_of(eligible_group)
    if gremium_id is None or not await _meeting_live(session, meeting_id, gremium_id):
        return None
    deputy = await session.scalar(select(PrincipalRow).where(PrincipalRow.sub == sub))
    if deputy is None:
        return None
    personal, gremium_wide = await members_for_substitute(session, gremium_id, deputy.id)
    if not personal and not gremium_wide:
        return None
    rows = (
        await session.execute(
            select(
                MeetingDelegation.delegator_principal_id,
                MeetingDelegation.delegate_principal_id,
                MeetingDelegation.delegate_voting,
            ).where(MeetingDelegation.meeting_id == meeting_id)
        )
    ).all()
    taken: set[UUID] = set()
    for delegator_id, delegate_id, voting in rows:
        if delegator_id == deputy.id or (voting and delegate_id == deputy.id):
            return None
        taken.update((delegator_id, delegate_id))
    voters = await _voting_member_ids(session, gremium_id)
    pool = voters if gremium_wide else personal & voters
    present = set(
        (
            await session.execute(
                select(MeetingAttendance.principal_id).where(
                    MeetingAttendance.meeting_id == meeting_id,
                    MeetingAttendance.status == "present",
                )
            )
        )
        .scalars()
        .all()
    )
    free = pool - taken - present - {deputy.id}
    if not free:
        return None
    members = (
        (await session.execute(select(PrincipalRow).where(PrincipalRow.id.in_(free))))
        .scalars()
        .all()
    )
    first = min(
        members,
        key=lambda m: (m.id not in personal, (m.display_name or "").casefold(), str(m.id)),
    )
    return deputy, first


async def pool_seat_for(
    session: AsyncSession,
    sub: str,
    meeting_id: UUID | None,
    eligible_group: str,
) -> PrincipalRow | None:
    """Return the member whose seat `sub` would take with a represented ballot now.

    The read takes no lock and writes nothing. `claim_pool_seat` repeats it under the
    lock.
    """
    found = await _find_seat(session, sub, meeting_id, eligible_group)
    return found[1] if found is not None else None


async def claim_pool_seat(
    session: AsyncSession,
    sub: str,
    meeting_id: UUID | None,
    eligible_group: str,
) -> str | None:
    """Claim a free seat for the substitute `sub` and return the `sub` of the member.

    The claim stores the delegation row and its `delegation_grant` audit entry
    (`poolSeat`). It does not commit: the ballot commits it, and a refused ballot
    rolls it back.

    Returns:
        The `sub` of the represented member, or None when no seat is free.
    """
    if meeting_id is not None:
        await lock_meeting_delegations(session, meeting_id)
    found = await _find_seat(session, sub, meeting_id, eligible_group)
    if found is None:
        return None
    deputy, member = found
    row = MeetingDelegation(
        meeting_id=meeting_id,
        gremium_id=UUID(eligible_group),
        delegator_principal_id=member.id,
        delegate_principal_id=deputy.id,
        delegate_voting=True,
        via_pool=True,
        created_by=sub,
    )
    session.add(row)
    await session.flush()
    await audit_record(
        session,
        actor=sub,
        action=AuditAction.DELEGATION_GRANT,
        target_type="meeting_delegation",
        target_id=str(row.id),
        data={
            "meetingId": str(meeting_id),
            "gremiumId": eligible_group,
            "delegatorId": str(member.id),
            "delegateId": str(deputy.id),
            "delegateVoting": True,
            "viaPool": True,
            "poolSeat": True,
        },
    )
    return member.sub


async def release_pool_seat(
    session: AsyncSession, meeting_id: UUID, member_id: UUID, actor_sub: str
) -> bool:
    """Free the pool seat of a member who checks in or casts the own ballot.

    Only a row that a substitute claimed (`pool_seat_clause`) goes. A delegation that
    the member gave or that the lead entered stays. The call does not commit.

    Returns:
        True when a seat was freed.
    """
    delegate = aliased(PrincipalRow)
    row = await session.scalar(
        select(MeetingDelegation)
        .join(delegate, delegate.id == MeetingDelegation.delegate_principal_id)
        .where(
            MeetingDelegation.meeting_id == meeting_id,
            MeetingDelegation.delegator_principal_id == member_id,
            pool_seat_clause(delegate),
        )
    )
    if row is None:
        return False
    await session.delete(row)
    await audit_record(
        session,
        actor=actor_sub,
        action=AuditAction.DELEGATION_REVOKE,
        target_type="meeting_delegation",
        target_id=str(row.id),
        data={
            "meetingId": str(meeting_id),
            "delegatorId": str(member_id),
            "poolSeat": True,
        },
    )
    await session.flush()
    return True


async def release_pool_seat_of(session: AsyncSession, meeting_id: UUID, member_sub: str) -> bool:
    """Free the pool seat of the member with `member_sub` (see `release_pool_seat`)."""
    member_id = await session.scalar(select(PrincipalRow.id).where(PrincipalRow.sub == member_sub))
    if member_id is None:
        return False
    return await release_pool_seat(session, meeting_id, member_id, member_sub)
