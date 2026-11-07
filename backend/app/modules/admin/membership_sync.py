"""Derive the gremium memberships from the OIDC groups.

The IdP is the only source of gremium membership. Two separate mappings apply:

- ``gremium_membership_mapping``: an OIDC group makes a principal a member of one
  gremium.
- ``gremium_role_mapping``: an OIDC group gives a principal a role in a gremium. The
  role applies only when the principal is a member of that gremium. It never makes a
  principal a member.

A member without a matching role mapping gets the forced role ``member``. When two
groups give different roles in one gremium, the role with more permissions wins, then
the lower key. A (principal, gremium) pair thus has exactly one role, which the unique
constraint on ``gremium_membership`` requires.

The sync compares the cached ``principal.oidc_groups`` with the mappings and writes
``gremium_membership`` to match. Nobody else writes that table. The sync runs at three
points:

- at each OIDC login, after the upsert of the principal refreshes the group cache.
- after each create, change or delete of a gremium mapping, for all principals.
- at the erasure of a principal, whose group cache is then empty.
- at the merge of a principal into another one. A merged principal holds no
  membership.

A membership has no term of office. It holds while the IdP puts the principal into a
mapped group, as of the last login.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, assert_never
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.gremium_roles import GremiumRoleService
from app.modules.admin.models import (
    GremiumMembership,
    GremiumMembershipMapping,
    GremiumRole,
    GremiumRoleMapping,
)
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import AuditService
from app.modules.auth.models import Principal as PrincipalRow

#: The actor of the audit entries that the sync writes.
SYNC_ACTOR = "oidc-sync"

#: The forced gremium role that a member without a role mapping gets.
DEFAULT_ROLE_KEY = "member"


def _role_rank(role: GremiumRole) -> tuple[int, str]:
    """Sort key: more permissions first, then the lower key."""
    return (-len(role.permissions or []), role.key)


async def _find_default_role(session: AsyncSession, gremium_id: UUID) -> GremiumRole | None:
    return (
        await session.scalars(
            select(GremiumRole).where(
                GremiumRole.gremium_id == gremium_id, GremiumRole.key == DEFAULT_ROLE_KEY
            )
        )
    ).first()


async def _default_role(session: AsyncSession, gremium_id: UUID) -> GremiumRole:
    """Return the forced role ``member`` of the gremium. Create it when it is missing."""
    found = await _find_default_role(session, gremium_id)
    if found is not None:
        return found
    await GremiumRoleService(session).ensure_forced_roles(gremium_id)
    created = await _find_default_role(session, gremium_id)
    if created is None:  # pragma: no cover - ensure_forced_roles always creates it
        raise RuntimeError(f"forced gremium role {DEFAULT_ROLE_KEY!r} missing")
    return created


async def _desired_roles(
    session: AsyncSession, groups: set[str]
) -> dict[UUID, UUID]:
    """Return the gremium role per gremium that ``groups`` give, as ``{gremium: role}``."""
    if not groups:
        return {}
    member_of = set(
        (
            await session.scalars(
                select(GremiumMembershipMapping.gremium_id).where(
                    GremiumMembershipMapping.oidc_group.in_(groups)
                )
            )
        ).all()
    )
    if not member_of:
        return {}
    mapped = (
        await session.scalars(
            select(GremiumRole)
            .join(GremiumRoleMapping, GremiumRoleMapping.gremium_role_id == GremiumRole.id)
            .where(
                GremiumRoleMapping.oidc_group.in_(groups),
                GremiumRole.gremium_id.in_(member_of),
            )
        )
    ).all()
    best = {
        gremium_id: min((r for r in mapped if r.gremium_id == gremium_id), key=_role_rank)
        for gremium_id in dict.fromkeys(r.gremium_id for r in mapped)
    }
    defaults = {
        gremium_id: (await _default_role(session, gremium_id)).id
        for gremium_id in member_of - best.keys()
    }
    return {**{gid: role.id for gid, role in best.items()}, **defaults}


MembershipAction = Literal["delete", "move", "keep"]


def _membership_action(
    membership: GremiumMembership,
    desired: Mapping[UUID, UUID],
    first: Mapping[UUID, GremiumMembership],
) -> MembershipAction:
    """Decide what the sync does with one existing membership.

    A membership goes when its gremium has no desired role, or when an earlier row of
    the same gremium stays, because the unique constraint allows one row per pair. A
    kept row moves to the desired role when its role differs.
    """
    role_id = desired.get(membership.gremium_id)
    return (
        "delete"
        if role_id is None or first[membership.gremium_id] is not membership
        else ("move" if membership.gremium_role_id != role_id else "keep")
    )


async def _add_membership(
    session: AsyncSession, principal_id: UUID, gremium_id: UUID, role_id: UUID
) -> UUID:
    """Insert one membership, flush it and return its id."""
    membership = GremiumMembership(
        principal_id=principal_id, gremium_id=gremium_id, gremium_role_id=role_id
    )
    session.add(membership)
    await session.flush()
    return membership.id


async def sync_principal_memberships(
    session: AsyncSession, row: PrincipalRow
) -> bool:
    """Make the memberships of one principal match its OIDC groups and the mappings.

    The function does not commit. The caller owns the transaction. Each added, changed
    or removed membership gets an audit entry.

    A merged principal is a locked reference and holds no membership: its group
    cache stays for the record, but the sync treats it as empty. The deletes flush
    before the inserts, because the unique constraint allows one row per pair only.

    Returns:
        True when the function changed at least one membership.
    """
    groups = (
        set() if row.merged_into is not None else {str(g) for g in (row.oidc_groups or [])}
    )
    desired = await _desired_roles(session, groups)
    existing = (
        await session.scalars(
            select(GremiumMembership).where(GremiumMembership.principal_id == row.id)
        )
    ).all()
    audit = AuditService(session)
    first = {m.gremium_id: m for m in reversed(existing)}
    actions: tuple[tuple[GremiumMembership, MembershipAction], ...] = tuple(
        (m, _membership_action(m, desired, first)) for m in existing
    )
    touched = tuple(m.id for m, action in actions if action != "keep")
    kept = frozenset(m.gremium_id for m, action in actions if action != "delete")
    for membership, action in actions:
        match action:
            case "delete":
                await session.delete(membership)
            case "move":
                membership.gremium_role_id = desired[membership.gremium_id]
            case "keep":
                pass
            case _:
                assert_never(action)
    if touched:
        await session.flush()
    added = [
        await _add_membership(session, row.id, gremium_id, role_id)
        for gremium_id, role_id in desired.items()
        if gremium_id not in kept
    ]
    changed = (*touched, *added)
    for membership_id in changed:
        await audit.record(
            actor=SYNC_ACTOR,
            action=AuditAction.ROLE_CHANGE,
            target_type="gremium_membership",
            target_id=str(membership_id),
            data={"principalId": str(row.id)},
        )
    return bool(changed)


async def sync_all_memberships(session: AsyncSession) -> int:
    """Run the sync for every principal. The function does not commit.

    Returns:
        The number of principals whose memberships changed.
    """
    principals = (await session.scalars(select(PrincipalRow))).all()
    return sum([await sync_principal_memberships(session, row) for row in principals])
