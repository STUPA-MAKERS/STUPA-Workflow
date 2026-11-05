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
    groups: set[str] = {
        g
        for g in (str(raw) for raw in (row.oidc_groups or []))
        if not g.startswith(VOTE_GROUP_PREFIX)
    }
    role_ids: set[UUID] = set(
        (
            await db.execute(
                select(RoleAssignment.role_id).where(
                    RoleAssignment.principal_id == row.id
                )
            )
        ).scalars().all()
    )

    if groups:
        mappings = (
            await db.execute(
                select(GroupMapping).where(GroupMapping.oidc_group.in_(groups))
            )
        ).scalars().all()
        for m in mappings:
            role_ids.add(m.role_id)

    permissions: set[str] = set()
    role_keys: list[str] = []
    if role_ids:
        permissions = set(
            (
                await db.execute(
                    select(RolePermission.permission).where(
                        RolePermission.role_id.in_(role_ids)
                    )
                )
            ).scalars().all()
        )
        role_keys = list(
            (
                await db.execute(select(Role.key).where(Role.id.in_(role_ids)))
            ).scalars().all()
        )

    membership_rows = (
        await db.execute(
            select(GremiumMembership.gremium_id, GremiumRole.permissions)
            .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
            .where(
                GremiumMembership.principal_id == row.id,
                (GremiumMembership.valid_from.is_(None))
                | (GremiumMembership.valid_from <= now),
                (GremiumMembership.valid_until.is_(None))
                | (GremiumMembership.valid_until > now),
            )
        )
    ).all()
    for gremium_id, perms in membership_rows:
        if "vote.cast" in (perms or []):
            groups.add(vote_group_key(gremium_id))

    return Principal(
        sub=row.sub,
        email=row.email,
        display_name=row.display_name,
        roles=role_keys,
        permissions=permissions,
        groups=groups,
    )
