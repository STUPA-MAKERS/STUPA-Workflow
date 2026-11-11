"""Read helpers of the protocol keeper.

The module holds the queries that more than one part of the meeting module needs:

* `member_permissions` gives the gremium-role permissions of each current member.
* `keeper_principal_ids` gives the members of a gremium who can keep the minutes.
  The keeper needs the gremium permission `protocol.write`.
* `agenda_positions` gives the 1-based number of each agenda item in the agenda
  order.
* `keeper_summaries` gives the periods and the planned handover of meetings, as
  `MeetingOut` shows them.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.gremien.models import GremiumMembership, GremiumRole
from app.modules.meetings.agenda_service import agenda_order
from app.modules.meetings.models import MeetingAgendaItem, ProtocolKeeperPeriod
from app.modules.meetings.schemas import KeeperPeriodOut

#: The gremium permission that a protocol keeper needs.
KEEPER_PERMISSION = "protocol.write"

#: The gremium permission that gives a member the own vote (the cast gate of voting).
VOTE_PERMISSION = "vote.cast"

#: Per meeting: the running and ended periods in time order, and the planned one.
KeeperSummary = tuple[list[KeeperPeriodOut], KeeperPeriodOut | None]


async def member_permissions(session: AsyncSession, gremium_id: UUID) -> dict[UUID, frozenset[str]]:
    """Return the gremium-role permissions of each member of the gremium."""
    rows = (
        await session.execute(
            select(GremiumMembership.principal_id, GremiumRole.permissions)
            .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
            .where(
                GremiumMembership.gremium_id == gremium_id,
            )
        )
    ).all()
    members = dict.fromkeys(pid for pid, _ in rows)
    return {
        pid: frozenset(perm for member, perms in rows if member == pid for perm in perms or [])
        for pid in members
    }


async def keeper_principal_ids(session: AsyncSession, gremium_id: UUID) -> set[UUID]:
    """Return the members of the gremium whose role grants `protocol.write`."""
    perms = await member_permissions(session, gremium_id)
    return {pid for pid, held in perms.items() if KEEPER_PERMISSION in held}


async def agenda_positions(session: AsyncSession, meeting_ids: Sequence[UUID]) -> dict[UUID, int]:
    """Return the 1-based number of each agenda item of the meetings, in agenda order."""
    if not meeting_ids:
        return {}
    rows = (
        await session.execute(
            select(MeetingAgendaItem.meeting_id, MeetingAgendaItem.id)
            .where(MeetingAgendaItem.meeting_id.in_(list(meeting_ids)))
            .order_by(MeetingAgendaItem.meeting_id, *agenda_order())
        )
    ).all()
    by_meeting = {
        meeting_id: [item_id for owner, item_id in rows if owner == meeting_id]
        for meeting_id in dict.fromkeys(meeting_id for meeting_id, _ in rows)
    }
    return {
        item_id: position
        for item_ids in by_meeting.values()
        for position, item_id in enumerate(item_ids, start=1)
    }


async def keeper_periods(
    session: AsyncSession, meeting_ids: Sequence[UUID]
) -> list[ProtocolKeeperPeriod]:
    """Return the periods of the meetings: by meeting, then in time order.

    The planned period (`from_at` is NULL) comes last.
    """
    if not meeting_ids:
        return []
    return list(
        (
            await session.execute(
                select(ProtocolKeeperPeriod)
                .where(ProtocolKeeperPeriod.meeting_id.in_(list(meeting_ids)))
                .order_by(
                    ProtocolKeeperPeriod.meeting_id,
                    ProtocolKeeperPeriod.from_at.asc().nulls_last(),
                    ProtocolKeeperPeriod.created_at,
                    ProtocolKeeperPeriod.id,
                )
            )
        )
        .scalars()
        .all()
    )


async def principal_names(session: AsyncSession, ids: set[UUID]) -> dict[UUID, str | None]:
    """Return the display name, or the email as a fallback, of each principal."""
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(PrincipalRow.id, PrincipalRow.display_name, PrincipalRow.email).where(
                PrincipalRow.id.in_(ids)
            )
        )
    ).all()
    return {pid: (name or email) for pid, name, email in rows}


async def keeper_summaries(
    session: AsyncSession, meeting_ids: Sequence[UUID]
) -> dict[UUID, KeeperSummary]:
    """Return the periods and the planned handover of each meeting.

    Three batched queries at most, for any number of meetings: the periods, the
    names, and the agenda positions when a period refers to an agenda item.
    """
    periods = await keeper_periods(session, meeting_ids)
    if not periods:
        return {mid: ([], None) for mid in meeting_ids}
    names = await principal_names(session, {p.principal_id for p in periods})
    referenced = any(
        p.from_agenda_item_id is not None or p.to_agenda_item_id is not None for p in periods
    )
    positions = (
        await agenda_positions(session, list({p.meeting_id for p in periods})) if referenced else {}
    )
    rows = tuple((p, _period_out(p, names, positions)) for p in periods)
    return {
        mid: (
            [row for p, row in rows if p.meeting_id == mid and p.from_at is not None],
            next(
                (row for p, row in reversed(rows) if p.meeting_id == mid and p.from_at is None),
                None,
            ),
        )
        for mid in meeting_ids
    }


def _period_out(
    period: ProtocolKeeperPeriod, names: dict[UUID, str | None], positions: dict[UUID, int]
) -> KeeperPeriodOut:
    """Build the wire form of one keeper period."""
    return KeeperPeriodOut(
        principalId=period.principal_id,
        name=names.get(period.principal_id),
        fromAt=period.from_at,
        toAt=period.to_at,
        fromAgendaItemId=period.from_agenda_item_id,
        toAgendaItemId=period.to_agenda_item_id,
        fromPosition=(
            positions.get(period.from_agenda_item_id) if period.from_agenda_item_id else None
        ),
        toPosition=positions.get(period.to_agenda_item_id) if period.to_agenda_item_id else None,
    )
