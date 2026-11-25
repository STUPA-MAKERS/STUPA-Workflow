"""Who is a member and who is a manager of a team, read at the time of the request.

* inherent team — the active members of its Gremium (``gremium_membership``) and the
  persons of the substitute pool of its Gremium are members (specs 003061). A member
  whose Gremium role holds ``team.manage`` is a manager (spec 003066).
* free team — the ``team_member`` rows, with the role ``member`` or ``manager`` (spec
  003063).

A sub-team does not add its members to the parent and the parent does not add its
members to the sub-team (spec 003064), so no read walks the tree.

Every read takes only active accounts that were not merged into another one.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Mapping
from dataclasses import dataclass

from sqlalchemy import Select, func, select, union
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.gremien import gremium_roles
from app.modules.gremien.models import Gremium, GremiumMembership
from app.modules.gremien.pool import pool_principals_of_gremien_stmt, substitute_gremien_stmt
from app.modules.teams.models import Team, TeamMember

#: The Gremium permission that manages the inherent team of a Gremium.
TEAM_MANAGE = "team.manage"
#: The global permission that creates a team without a parent.
TEAM_CREATE = "team.create"


def _gremien_of(team_ids: Collection[uuid.UUID]) -> Select[uuid.UUID | None]:
    """Select the Gremien of the inherent teams among ``team_ids``."""
    return select(Team.gremium_id).where(Team.id.in_(team_ids), Team.gremium_id.is_not(None))


def member_ids_stmt(team_ids: Collection[uuid.UUID]) -> Select[uuid.UUID]:
    """Select the active accounts that are members of one of ``team_ids``.

    One account can come once per team; the caller adds ``distinct`` where it counts.
    """
    gremien = _gremien_of(team_ids)
    candidates = union(
        select(TeamMember.principal_id).where(TeamMember.team_id.in_(team_ids)),
        select(GremiumMembership.principal_id).where(GremiumMembership.gremium_id.in_(gremien)),
        pool_principals_of_gremien_stmt(gremien),
    ).subquery()
    return select(PrincipalRow.id).where(
        PrincipalRow.id.in_(select(candidates.c[0])),
        PrincipalRow.active.is_(True),
        PrincipalRow.merged_into.is_(None),
    )


async def member_ids(session: AsyncSession, team_ids: Collection[uuid.UUID]) -> set[uuid.UUID]:
    """Return the ids of the active members of ``team_ids``."""
    if not team_ids:
        return set()
    return set((await session.scalars(member_ids_stmt(team_ids))).all())


async def team_ids_of_account(session: AsyncSession, account_id: uuid.UUID) -> frozenset[uuid.UUID]:
    """Return the teams of which the account is a member (no activity check)."""
    gremien = union(
        select(GremiumMembership.gremium_id).where(GremiumMembership.principal_id == account_id),
        substitute_gremien_stmt(account_id),
    ).subquery()
    rows = await session.scalars(
        union(
            select(TeamMember.team_id).where(TeamMember.principal_id == account_id),
            select(Team.id).where(Team.gremium_id.in_(select(gremien.c[0]))),
        )
    )
    return frozenset(rows.all())


async def member_team_ids(session: AsyncSession, principal: Principal) -> frozenset[uuid.UUID]:
    """Return the teams of the principal; empty for an inactive or merged account."""
    account = await session.scalar(
        select(PrincipalRow.id).where(
            PrincipalRow.sub == principal.sub,
            PrincipalRow.active.is_(True),
            PrincipalRow.merged_into.is_(None),
        )
    )
    return frozenset() if account is None else await team_ids_of_account(session, account)


async def managed_team_ids(session: AsyncSession, principal: Principal) -> frozenset[uuid.UUID]:
    """Return the teams that the principal manages by an own role (no admin bypass).

    The Gremium role with ``team.manage`` for an inherent team, the role ``manager``
    for a free team. The read applies no OAuth scope cap: the caller caps, because a
    board caps by ``todo.configure`` and the team routes by ``team.manage``.
    """
    gremien = await gremium_roles.gremium_ids_with_permission(session, principal.sub, TEAM_MANAGE)
    rows = await session.scalars(
        union(
            select(Team.id).where(Team.gremium_id.in_(gremien)),
            select(TeamMember.team_id)
            .join(PrincipalRow, PrincipalRow.id == TeamMember.principal_id)
            .where(
                PrincipalRow.sub == principal.sub,
                PrincipalRow.active.is_(True),
                PrincipalRow.merged_into.is_(None),
                TeamMember.role == "manager",
            ),
        )
    )
    return frozenset(rows.all())


def team_name() -> Select[uuid.UUID, str]:
    """Select the id and the shown name of every team: its own or its Gremium's."""
    return select(Team.id, func.coalesce(Team.name, Gremium.name)).outerjoin(
        Gremium, Gremium.id == Team.gremium_id
    )


async def team_names(
    session: AsyncSession, team_ids: Collection[uuid.UUID]
) -> Mapping[uuid.UUID, str]:
    """Return the shown name of each team of ``team_ids`` that exists."""
    if not team_ids:
        return {}
    rows = await session.execute(team_name().where(Team.id.in_(team_ids)))
    return {row[0]: row[1] for row in rows}


async def gremien_of_teams(
    session: AsyncSession, team_ids: Collection[uuid.UUID]
) -> Mapping[uuid.UUID, uuid.UUID]:
    """Return the Gremium of each inherent team among ``team_ids``."""
    if not team_ids:
        return {}
    rows = (
        await session.execute(
            select(Team.id, Team.gremium_id).where(
                Team.id.in_(team_ids), Team.gremium_id.is_not(None)
            )
        )
    ).tuples()
    return {tid: gid for tid, gid in rows if gid is not None}


async def teams_of_gremien(
    session: AsyncSession, gremium_ids: Collection[uuid.UUID]
) -> Mapping[uuid.UUID, uuid.UUID]:
    """Return the inherent team of each Gremium among ``gremium_ids``."""
    if not gremium_ids:
        return {}
    rows = (
        await session.execute(
            select(Team.gremium_id, Team.id).where(Team.gremium_id.in_(gremium_ids))
        )
    ).tuples()
    return {gid: tid for gid, tid in rows if gid is not None}


async def ensure_gremium_team(session: AsyncSession, gremium_id: uuid.UUID) -> uuid.UUID:
    """Create the inherent team of a Gremium when it has none and return its id.

    The insert skips a conflict on the unique ``gremium_id``, so two parallel calls
    create one team. The caller commits.
    """
    await session.execute(
        insert(Team)
        .values(id=uuid.uuid4(), gremium_id=gremium_id)
        .on_conflict_do_nothing(index_elements=["gremium_id"])
    )
    team_id = await session.scalar(select(Team.id).where(Team.gremium_id == gremium_id))
    if team_id is None:  # pragma: no cover - the insert above guarantees a row
        raise RuntimeError("inherent team missing")
    return team_id


@dataclass(frozen=True, slots=True)
class TeamInfo:
    """What a list shows of a team: the shown name, its Gremium and its parent's name."""

    id: uuid.UUID
    name: str
    gremium_id: uuid.UUID | None
    cd_variant_id: uuid.UUID | None
    parent_id: uuid.UUID | None
    parent_name: str | None


async def team_infos(
    session: AsyncSession,
    *,
    ids: Collection[uuid.UUID] | None = None,
    pattern: str | None = None,
) -> list[TeamInfo]:
    """Return the teams of ``ids`` (every team for None), by shown name.

    ``pattern`` is an ``ILIKE`` pattern on the shown name, escaped by ``escape_like``.
    """
    if ids is not None and not ids:
        return []
    parent = aliased(Team)
    parent_gremium = aliased(Gremium)
    shown = func.coalesce(Team.name, Gremium.name)
    stmt = (
        select(
            Team.id,
            shown,
            Team.gremium_id,
            Gremium.cd_variant_id,
            Team.parent_id,
            func.coalesce(parent.name, parent_gremium.name),
        )
        .outerjoin(Gremium, Gremium.id == Team.gremium_id)
        .outerjoin(parent, parent.id == Team.parent_id)
        .outerjoin(parent_gremium, parent_gremium.id == parent.gremium_id)
        .where(
            *((Team.id.in_(ids),) if ids is not None else ()),
            *((shown.ilike(pattern, escape="\\"),) if pattern is not None else ()),
        )
        .order_by(shown, Team.id)
    )
    rows = (await session.execute(stmt)).tuples().all()
    return [
        TeamInfo(tid, name or "", gid, variant, pid, pname)
        for tid, name, gid, variant, pid, pname in rows
    ]
