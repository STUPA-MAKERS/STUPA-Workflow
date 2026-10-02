"""Read helpers of the protocol keeper (Z3, O20).

The module holds the queries that more than one part of the meeting module needs:

* `keeper_principal_ids` gives the members of a gremium who can keep the minutes.
  O20: the keeper needs the gremium permission `protocol.write`.
* `agenda_positions` gives the 1-based number of each agenda item in the agenda
  order.
* `keeper_summaries` gives the periods and the planned handover of meetings, as
  `MeetingOut` shows them (A13).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import GremiumMembership, GremiumRole
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.livevote.agenda_service import agenda_order
from app.modules.livevote.models import MeetingAgendaItem, ProtocolKeeperPeriod
from app.modules.livevote.schemas import KeeperPeriodOut

# The gremium permission that a protocol keeper needs (O20).
KEEPER_PERMISSION = "protocol.write"

# Per meeting: the running and ended periods in time order, and the planned one.
KeeperSummary = tuple[list[KeeperPeriodOut], KeeperPeriodOut | None]


async def keeper_principal_ids(
    session: AsyncSession, gremium_id: UUID, now: datetime | None = None
) -> set[UUID]:
    """Return the current members of the gremium whose role grants `protocol.write`."""
    now = now or datetime.now(UTC)
    rows = (
        await session.execute(
            select(GremiumMembership.principal_id, GremiumRole.permissions)
            .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
            .where(
                GremiumMembership.gremium_id == gremium_id,
                (GremiumMembership.valid_from.is_(None)) | (GremiumMembership.valid_from <= now),
                (GremiumMembership.valid_until.is_(None))
                | (GremiumMembership.valid_until > now),
            )
        )
    ).all()
    return {pid for pid, perms in rows if KEEPER_PERMISSION in (perms or [])}


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
    counts: dict[UUID, int] = {}
    out: dict[UUID, int] = {}
    for meeting_id, item_id in rows:
        counts[meeting_id] = counts.get(meeting_id, 0) + 1
        out[item_id] = counts[meeting_id]
    return out


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
    """Return the periods and the planned handover of each meeting (A13).

    Three batched queries at most, for any number of meetings: the periods, the
    names, and the agenda positions when a period refers to an agenda item.
    """
    periods = await keeper_periods(session, meeting_ids)
    out: dict[UUID, KeeperSummary] = {mid: ([], None) for mid in meeting_ids}
    if not periods:
        return out
    names = await principal_names(session, {p.principal_id for p in periods})
    referenced = any(
        p.from_agenda_item_id is not None or p.to_agenda_item_id is not None for p in periods
    )
    positions = (
        await agenda_positions(session, list({p.meeting_id for p in periods}))
        if referenced
        else {}
    )
    for p in periods:
        row = KeeperPeriodOut(
            principalId=p.principal_id,
            name=names.get(p.principal_id),
            fromAt=p.from_at,
            toAt=p.to_at,
            fromAgendaItemId=p.from_agenda_item_id,
            toAgendaItemId=p.to_agenda_item_id,
            fromPosition=positions.get(p.from_agenda_item_id) if p.from_agenda_item_id else None,
            toPosition=positions.get(p.to_agenda_item_id) if p.to_agenda_item_id else None,
        )
        done, planned = out[p.meeting_id]
        if p.from_at is None:
            planned = row
        else:
            done.append(row)
        out[p.meeting_id] = (done, planned)
    return out
