"""RBAC resolution.

The roles of the application are the truth. The permissions come from `role_assignment`,
which the resolver validates against the current time for a delegation. An optional
`group_mapping` adds a role for an OIDC group. The Gremium scope of an assignment or a
mapping lands as a group key in `Principal.groups`. `require_group` reads that key.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import GremiumMembership, GremiumRole
from app.modules.auth.models import GroupMapping, Role, RoleAssignment, RolePermission
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal

# The internal namespace of the voting eligibility. It belongs to this resolver alone.
# `resolve_principal` drops every incoming OIDC group claim that uses it, so a key in
# this namespace always proves an active `vote.cast` membership.
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


def _as_aware(dt: datetime | None) -> datetime | None:
    """Treat a naive value as UTC.

    This guard covers legacy data and timestamps without a time zone. The rest of the code
    uses aware UTC. A naive `valid_from` or `valid_until` from the database would raise
    `TypeError` against the aware `now`. That would break the whole principal resolution,
    for REST and for the WebSocket handshake.
    """
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _assignment_valid(
    valid_from: datetime | None, valid_until: datetime | None, now: datetime
) -> bool:
    """Check the validity window of a delegation.

    The caller always passes an aware UTC `now`. Only the database columns can be naive.
    """
    valid_from = _as_aware(valid_from)
    valid_until = _as_aware(valid_until)
    after_start = valid_from is None or valid_from <= now
    before_end = valid_until is None or valid_until >= now
    return after_start and before_end


async def resolve_principal(db: AsyncSession, row: PrincipalRow, now: datetime) -> Principal:
    """Resolve a `principal` row into a full `Principal` with roles, permissions, groups."""
    # The `vote:` namespace is reserved for the membership loop below. An IdP can emit
    # any group name, including one that copies the internal key, and the cast gate
    # reads that key as proof of an active `vote.cast` membership. The resolver
    # therefore drops such a claim at the door. A `group_mapping` on a reserved name
    # stays without effect for the same reason.
    groups: set[str] = {
        g
        for g in (str(raw) for raw in (row.oidc_groups or []))
        if not g.startswith(VOTE_GROUP_PREFIX)
    }
    role_ids: set = set()

    assignments = (
        await db.execute(
            select(RoleAssignment).where(RoleAssignment.principal_id == row.id)
        )
    ).scalars().all()
    for a in assignments:
        if _assignment_valid(a.valid_from, a.valid_until, now):
            role_ids.add(a.role_id)
            if a.gremium_id is not None:
                groups.add(str(a.gremium_id))

    if groups:
        mappings = (
            await db.execute(
                select(GroupMapping).where(GroupMapping.oidc_group.in_(groups))
            )
        ).scalars().all()
        for m in mappings:
            role_ids.add(m.role_id)
            if m.gremium_id is not None:
                groups.add(str(m.gremium_id))

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

    # An active Gremium role with `vote.cast` grants the voting eligibility. The cast gate
    # checks the namespaced key `vote:<gremium_id>` from `vote_group_key`. It never checks
    # the bare UUID string, so a matching OIDC group claim cannot satisfy the eligibility.
    # A user who only follows a meeting goes through `MeetingService.is_member`, which is
    # a separate query.
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
