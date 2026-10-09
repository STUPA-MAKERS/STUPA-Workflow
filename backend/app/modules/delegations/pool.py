"""The single source of the substitute pool.

The pool is the table `delegation_substitute` of a gremium. It holds personal
entries (for one member) and gremium-wide entries (for every member).

Every path that reads the pool uses the helpers of this module: the delegation
create (`via_pool`), the lead entry during a live meeting (O6), the recipient
list, the meeting context, the roster guard, the meeting visibility and
`/auth/me` (`inSubstitutePool`). Do not query the pool table directly in another
place.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import ScalarSelect, Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.delegations.models import DelegationSubstitute


async def substitutes_for(
    session: AsyncSession, gremium_id: UUID, member_id: UUID
) -> set[UUID]:
    """Return every pool substitute that may represent `member_id` in the gremium.

    The set holds the personal entries for the member and the gremium-wide
    entries of `delegation_substitute`.
    """
    stmt = select(DelegationSubstitute.substitute_principal_id).where(
        DelegationSubstitute.gremium_id == gremium_id,
        or_(
            DelegationSubstitute.member_principal_id.is_(None),
            DelegationSubstitute.member_principal_id == member_id,
        ),
    )
    return set((await session.execute(stmt)).scalars().all())


def _substitute_gremien_stmt(principal: UUID | ScalarSelect[UUID]) -> Select[UUID]:
    """Select the gremien in which `principal` is a pool substitute."""
    return (
        select(DelegationSubstitute.gremium_id)
        .where(DelegationSubstitute.substitute_principal_id == principal)
        .distinct()
    )


async def substitute_gremien(session: AsyncSession, principal_id: UUID) -> set[UUID]:
    """Return the gremien in which `principal_id` is a pool substitute."""
    stmt = _substitute_gremien_stmt(principal_id)
    return set((await session.execute(stmt)).scalars().all())


async def substitute_gremien_for_sub(session: AsyncSession, sub: str) -> set[UUID]:
    """Return the gremien in which the principal with `sub` is a pool substitute.

    The call runs one statement: the principal id is a subquery on `sub`.
    """
    pid = select(PrincipalRow.id).where(PrincipalRow.sub == sub).scalar_subquery()
    stmt = _substitute_gremien_stmt(pid)
    return set((await session.execute(stmt)).scalars().all())


async def pool_entries_of(
    session: AsyncSession, principal_id: UUID
) -> list[DelegationSubstitute]:
    """Return every pool entry in which `principal_id` is the substitute or the member.

    The revoke of the rights of a person (`admin/principal_revoke.py`) shows these
    entries per gremium and deletes them.
    """
    stmt = select(DelegationSubstitute).where(
        or_(
            DelegationSubstitute.substitute_principal_id == principal_id,
            DelegationSubstitute.member_principal_id == principal_id,
        )
    )
    return list((await session.scalars(stmt)).all())


def pool_principals_stmt(ids: list[UUID]) -> list[Select[Any]]:
    """Select the principals of `ids` that have a pool entry, as substitute or member.

    The user list of the admin (`hasAccess`) puts these statements into one UNION.
    """
    return [
        select(DelegationSubstitute.substitute_principal_id).where(
            DelegationSubstitute.substitute_principal_id.in_(ids)
        ),
        select(DelegationSubstitute.member_principal_id).where(
            DelegationSubstitute.member_principal_id.in_(ids)
        ),
    ]
