"""RBAC resolution.

The roles of the application are the truth. The permissions come from the bootstrap
`role_assignment` rows and from `group_mapping`, which adds a global role for an OIDC
group. A global role has no gremium
scope. The gremium rights come from the active `gremium_membership`, which the resolver
turns into the namespaced `vote:` key.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import GremiumMembership, GremiumRole
from app.modules.auth.models import GroupMapping, Role, RoleAssignment, RolePermission
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal

#: The internal namespace of the voting eligibility. It belongs to this resolver alone.
#: `resolve_principal` drops every incoming OIDC group claim that uses it, so a key in
#: this namespace always proves an active `vote.cast` membership.
VOTE_GROUP_PREFIX = "vote:"


def vote_group_key(gremium_id: object) -> str:
    """Build the namespaced group key for the voting eligibility in a Gremium.

    The cast gate depends on a real `vote.cast` membership in the Gremium. It must never
    depend on a raw OIDC group claim. The prefix of the internal key, `vote:<uuid>`,
    keeps the two apart: a claim that equals a Gremium UUID string misses the prefix,
    and a claim that carries the prefix never enters the group set. `Vote.eligible_group`
    stays the bare UUID as text. The voting service derives this prefixed key from it for
    the membership check.
    """
    return f"{VOTE_GROUP_PREFIX}{gremium_id}"


async def _assigned_role_ids(db: AsyncSession, principal_id: UUID) -> set[UUID]:
    """Return the ids of the roles that a `role_assignment` gives the principal."""
    rows = await db.execute(
        select(RoleAssignment.role_id).where(RoleAssignment.principal_id == principal_id)
    )
    return set(rows.scalars().all())


async def _mapped_role_ids(db: AsyncSession, groups: set[str]) -> set[UUID]:
    """Return the ids of the roles that `group_mapping` adds for the OIDC groups."""
    rows = await db.execute(select(GroupMapping).where(GroupMapping.oidc_group.in_(groups)))
    return {m.role_id for m in rows.scalars().all()}


async def _role_permissions(db: AsyncSession, role_ids: set[UUID]) -> set[str]:
    """Return the permissions of the roles."""
    rows = await db.execute(
        select(RolePermission.permission).where(RolePermission.role_id.in_(role_ids))
    )
    return set(rows.scalars().all())


async def _role_keys(db: AsyncSession, role_ids: set[UUID]) -> list[str]:
    """Return the keys of the roles."""
    rows = await db.execute(select(Role.key).where(Role.id.in_(role_ids)))
    return list(rows.scalars().all())


async def _vote_keys(db: AsyncSession, principal_id: UUID) -> set[str]:
    """Return the `vote:` key of each Gremium where a membership role holds `vote.cast`."""
    rows = await db.execute(
        select(GremiumMembership.gremium_id, GremiumRole.permissions)
        .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
        .where(
            GremiumMembership.principal_id == principal_id,
        )
    )
    return {
        vote_group_key(gremium_id)
        for gremium_id, perms in rows.all()
        if "vote.cast" in (perms or [])
    }


async def resolve_principal(db: AsyncSession, row: PrincipalRow, now: datetime) -> Principal:
    """Resolve a `principal` row into a full `Principal` with roles, permissions, groups.

    The ``vote:`` namespace is reserved for the membership step. An IdP can emit any
    group name, including one that copies the internal key, and the cast gate reads
    that key as proof of an active ``vote.cast`` membership. The resolver therefore
    drops such a claim at the door, and a ``group_mapping`` on a reserved name stays
    without effect.

    An active Gremium role with ``vote.cast`` is the only source of the voting
    eligibility: ``vote.cast`` is no global permission, and a vote names a gremium
    UUID as its eligible group. The cast gate checks the namespaced key
    ``vote:<gremium_id>`` from ``vote_group_key``, never the bare UUID, so a matching
    OIDC group claim cannot satisfy it. A user who only follows a meeting goes
    through ``MeetingService.is_member``, a separate query.
    """
    claimed = {
        g
        for g in (str(raw) for raw in (row.oidc_groups or []))
        if not g.startswith(VOTE_GROUP_PREFIX)
    }
    assigned = await _assigned_role_ids(db, row.id)
    mapped = await _mapped_role_ids(db, claimed) if claimed else set[UUID]()
    role_ids = assigned | mapped
    permissions = await _role_permissions(db, role_ids) if role_ids else set[str]()
    role_keys = await _role_keys(db, role_ids) if role_ids else list[str]()
    vote_keys = await _vote_keys(db, row.id)
    return Principal(
        sub=row.sub,
        email=row.email,
        display_name=row.display_name,
        roles=role_keys,
        permissions=permissions,
        groups=claimed | vote_keys,
    )
