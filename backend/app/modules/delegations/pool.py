"""The single source of the substitute pool (Z5).

The pool has two parts:

* `delegation_substitute`: personal entries (for one member) and gremium-wide
  entries (for every member).
* The faculty groups (`substitute_group`, `substitute_group_member`): a
  substitute of a group may represent every member of the group. A member counts
  only while the gremium membership from the OIDC groups is active.

Every path that reads the pool uses the helpers of this module: the delegation
create (`via_pool`), the recipient list, the meeting context, the roster guard,
the meeting visibility and `/auth/me` (`inSubstitutePool`). Do not query the
pool tables directly in another place.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import CompoundSelect, Exists, ScalarSelect, Select, exists, or_, select, union
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, aliased

from app.modules.admin.models import GremiumMembership
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.delegations.models import (
    DelegationSubstitute,
    SubstituteGroup,
    SubstituteGroupMember,
)
from app.shared.i18n import I18nMap


def _active_membership(
    gremium_id: UUID, principal_col: InstrumentedAttribute[UUID], now: datetime
) -> Exists:
    """Return an EXISTS clause: the principal has an active membership in the gremium."""
    return exists().where(
        GremiumMembership.principal_id == principal_col,
        GremiumMembership.gremium_id == gremium_id,
        (GremiumMembership.valid_from.is_(None)) | (GremiumMembership.valid_from <= now),
        (GremiumMembership.valid_until.is_(None)) | (GremiumMembership.valid_until > now),
    )


def _group_substitutes_stmt(
    gremium_id: UUID, member_id: UUID, now: datetime
) -> Select[UUID]:
    """Select the substitutes of the faculty group of `member_id` in the gremium."""
    member = aliased(SubstituteGroupMember)
    sub = aliased(SubstituteGroupMember)
    return (
        select(sub.principal_id)
        .join(member, member.group_id == sub.group_id)
        .where(
            member.gremium_id == gremium_id,
            member.principal_id == member_id,
            member.kind == "member",
            sub.kind == "substitute",
            _active_membership(gremium_id, member.principal_id, now),
        )
    )


async def group_substitutes_for(
    session: AsyncSession, gremium_id: UUID, member_id: UUID, now: datetime | None = None
) -> set[UUID]:
    """Return the substitutes of the faculty group of `member_id` only.

    The meeting lead uses this set during a live meeting (O6): only a substitute
    of the group of the missing member may step in. The set is empty while the
    member has no active membership in the gremium.
    """
    now = now or datetime.now(UTC)
    stmt = _group_substitutes_stmt(gremium_id, member_id, now)
    return set((await session.execute(stmt)).scalars().all())


async def substitutes_for(
    session: AsyncSession, gremium_id: UUID, member_id: UUID, now: datetime | None = None
) -> set[UUID]:
    """Return every pool substitute that may represent `member_id` in the gremium.

    The set is the union of the personal and the gremium-wide entries of
    `delegation_substitute` and of the substitutes of the faculty group of the
    member. The faculty group counts only while the member has an active
    membership in the gremium.
    """
    now = now or datetime.now(UTC)
    personal = select(DelegationSubstitute.substitute_principal_id).where(
        DelegationSubstitute.gremium_id == gremium_id,
        or_(
            DelegationSubstitute.member_principal_id.is_(None),
            DelegationSubstitute.member_principal_id == member_id,
        ),
    )
    stmt = union(personal, _group_substitutes_stmt(gremium_id, member_id, now))
    return set((await session.execute(stmt)).scalars().all())


def _substitute_gremien_stmt(principal: UUID | ScalarSelect[UUID]) -> CompoundSelect:
    """Select the gremien in which `principal` is a pool substitute."""
    return union(
        select(DelegationSubstitute.gremium_id).where(
            DelegationSubstitute.substitute_principal_id == principal
        ),
        select(SubstituteGroupMember.gremium_id).where(
            SubstituteGroupMember.principal_id == principal,
            SubstituteGroupMember.kind == "substitute",
        ),
    )


async def substitute_gremien(session: AsyncSession, principal_id: UUID) -> set[UUID]:
    """Return the gremien in which `principal_id` is a pool substitute.

    The set covers the entries of `delegation_substitute` and the faculty groups
    in which the principal is a substitute.
    """
    stmt = _substitute_gremien_stmt(principal_id)
    return set((await session.execute(stmt)).scalars().all())


async def substitute_gremien_for_sub(session: AsyncSession, sub: str) -> set[UUID]:
    """Return the gremien in which the principal with `sub` is a pool substitute.

    The call runs one statement: the principal id is a subquery on `sub`.
    """
    pid = select(PrincipalRow.id).where(PrincipalRow.sub == sub).scalar_subquery()
    stmt = _substitute_gremien_stmt(pid)
    return set((await session.execute(stmt)).scalars().all())


async def group_names_for(
    session: AsyncSession,
    gremium_id: UUID,
    principal_ids: Iterable[UUID],
    *,
    member_id: UUID | None = None,
) -> dict[UUID, I18nMap]:
    """Return the name of the faculty group of each principal in the gremium (A8).

    A member has at most one group per gremium, so the name of that group wins.
    For a substitute in more than one group, the group of `member_id` wins, so a
    recipient list shows the group that links the substitute to the delegator.
    Else the group with the lowest position wins. A principal without a group is
    not in the result.
    """
    ids = set(principal_ids)
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(
                SubstituteGroupMember.principal_id,
                SubstituteGroupMember.kind,
                SubstituteGroupMember.group_id,
                SubstituteGroup.name_i18n,
                SubstituteGroup.position,
            )
            .join(SubstituteGroup, SubstituteGroup.id == SubstituteGroupMember.group_id)
            .where(
                SubstituteGroupMember.gremium_id == gremium_id,
                SubstituteGroupMember.principal_id.in_(ids),
            )
        )
    ).all()
    member_group: UUID | None = None
    if member_id is not None:
        member_group = await session.scalar(
            select(SubstituteGroupMember.group_id).where(
                SubstituteGroupMember.gremium_id == gremium_id,
                SubstituteGroupMember.principal_id == member_id,
                SubstituteGroupMember.kind == "member",
            )
        )

    def rank(kind: str, group_id: UUID, position: int) -> tuple[int, int, int]:
        return (
            0 if kind == "member" else 1,
            0 if group_id == member_group else 1,
            position,
        )

    best: dict[UUID, tuple[tuple[int, int, int], I18nMap]] = {}
    for pid, kind, group_id, name, position in rows:
        key = rank(kind, group_id, position)
        if pid not in best or key < best[pid][0]:
            best[pid] = (key, dict(name or {}))
    return {pid: name for pid, (_, name) in best.items()}
