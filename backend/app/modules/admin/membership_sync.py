"""Derive the gremium memberships from the OIDC groups.

The IdP is the only source of gremium membership. Two separate mappings apply:

- ``gremium_membership_mapping``: an OIDC group makes a principal a member of one
  gremium.
- ``gremium_role_mapping``: an OIDC group gives a principal a role in a gremium. The
  role applies only when the principal is a member of that gremium. It never makes a
  principal a member.

A member without a matching role mapping gets the forced role ``member``. When two
groups give different roles in one gremium, the role with more permissions wins, then
the lower key. A (principal, gremium) pair thus has exactly one role, which the EXCLUDE
constraint on ``gremium_membership`` requires.

The sync compares the cached ``principal.oidc_groups`` with the mappings and writes
``gremium_membership`` to match. Nobody else writes that table. The sync runs at three
points:

- at each OIDC login, after the upsert of the principal refreshes the group cache.
- after each create, change or delete of a gremium mapping, for all principals.
- at the erasure of a principal, whose group cache is then empty.

A membership has no term of office. It holds while the IdP puts the principal into a
mapped group, as of the last login.
"""

from __future__ import annotations

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

# The actor of the audit entries that the sync writes.
SYNC_ACTOR = "oidc-sync"

# The forced gremium role that a member without a role mapping gets.
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
    role = await _find_default_role(session, gremium_id)
    if role is not None:
        return role
    await GremiumRoleService(session).ensure_forced_roles(gremium_id)
    role = await _find_default_role(session, gremium_id)
    if role is None:  # pragma: no cover - ensure_forced_roles always creates it
        raise RuntimeError(f"forced gremium role {DEFAULT_ROLE_KEY!r} missing")
    return role


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
    best: dict[UUID, GremiumRole] = {}
    for role in mapped:
        current = best.get(role.gremium_id)
        if current is None or _role_rank(role) < _role_rank(current):
            best[role.gremium_id] = role
    for gremium_id in member_of - best.keys():
        best[gremium_id] = await _default_role(session, gremium_id)
    return {gid: role.id for gid, role in best.items()}


async def sync_principal_memberships(
    session: AsyncSession, row: PrincipalRow
) -> bool:
    """Make the memberships of one principal match its OIDC groups and the mappings.

    The function does not commit. The caller owns the transaction. Each added, changed
    or removed membership gets an audit entry.

    Returns:
        True when the function changed at least one membership.
    """
    groups = {str(g) for g in (row.oidc_groups or [])}
    desired = await _desired_roles(session, groups)
    existing = (
        await session.scalars(
            select(GremiumMembership).where(GremiumMembership.principal_id == row.id)
        )
    ).all()
    audit = AuditService(session)
    changed: list[UUID] = []
    kept: set[UUID] = set()
    for membership in existing:
        role_id = desired.get(membership.gremium_id)
        if role_id is None or membership.gremium_id in kept:
            await session.delete(membership)
            changed.append(membership.id)
            continue
        kept.add(membership.gremium_id)
        if membership.gremium_role_id != role_id:
            membership.gremium_role_id = role_id
            changed.append(membership.id)
    # Flush the deletes first. The EXCLUDE constraint allows one row per pair only.
    if changed:
        await session.flush()
    for gremium_id, role_id in desired.items():
        if gremium_id in kept:
            continue
        membership = GremiumMembership(
            principal_id=row.id, gremium_id=gremium_id, gremium_role_id=role_id
        )
        session.add(membership)
        await session.flush()
        changed.append(membership.id)
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
    count = 0
    for row in principals:
        if await sync_principal_memberships(session, row):
            count += 1
    return count
