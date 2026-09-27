"""Derive the gremium memberships from the OIDC groups.

The IdP is the only source of gremium membership. ``gremium_group_mapping`` maps an
OIDC group to a role in one gremium. The sync compares the cached
``principal.oidc_groups`` with the mappings and writes ``gremium_membership`` to match.
Nobody else writes that table.

The sync runs at three points:

- at each OIDC login, after the upsert of the principal refreshes the group cache.
- after each create, change or delete of a mapping, for all principals.
- at the erasure of a principal, whose group cache is then empty.

A membership has no term of office. It holds while the IdP puts the principal into a
mapped group, as of the last login.

When two groups of a principal map to different roles in the same gremium, the role
with more permissions wins, then the lower key. A (principal, gremium) pair thus has
exactly one role, which the EXCLUDE constraint on ``gremium_membership`` requires.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import GremiumGroupMapping, GremiumMembership, GremiumRole
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import AuditService
from app.modules.auth.models import Principal as PrincipalRow

# The actor of the audit entries that the sync writes.
SYNC_ACTOR = "oidc-sync"


def _role_rank(role: GremiumRole) -> tuple[int, str]:
    """Sort key: more permissions first, then the lower key."""
    return (-len(role.permissions or []), role.key)


async def _desired_roles(
    session: AsyncSession, groups: set[str]
) -> dict[UUID, UUID]:
    """Return the gremium role per gremium that ``groups`` give, as ``{gremium: role}``."""
    if not groups:
        return {}
    rows = (
        await session.execute(
            select(GremiumGroupMapping.gremium_id, GremiumRole)
            .join(GremiumRole, GremiumRole.id == GremiumGroupMapping.gremium_role_id)
            .where(GremiumGroupMapping.oidc_group.in_(groups))
        )
    ).all()
    best: dict[UUID, GremiumRole] = {}
    for gremium_id, role in rows:
        current = best.get(gremium_id)
        if current is None or _role_rank(role) < _role_rank(current):
            best[gremium_id] = role
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
