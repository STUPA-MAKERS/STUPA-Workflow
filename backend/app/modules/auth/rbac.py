"""RBAC resolution.

App-side roles are the truth: permissions come from `role_assignment`
(time-validated: representation/delegation) plus optional `group_mapping`
(OIDC group -> role, convenience). The gremium scope of an assignment/mapping
lands as a group key in `Principal.groups` (`require_group` uses it).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import GremiumMembership, GremiumRole
from app.modules.auth.models import GroupMapping, Role, RoleAssignment, RolePermission
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal


def vote_group_key(gremium_id: object) -> str:
    """Namespaced group key for *gremium voting eligibility*.

    The cast gate must depend on a real ``vote.cast`` gremium membership, never
    on a raw OIDC group claim that happens to equal a gremium UUID string.
    Prefixing the internal key (``vote:<uuid>``) makes it impossible for an
    arbitrary IdP-emitted group name to satisfy cast eligibility.
    ``Vote.eligible_group`` stays the bare UUID-as-text; the voting service
    derives this prefixed key from it for the membership check.
    """
    return f"vote:{gremium_id}"


def _as_aware(dt: datetime | None) -> datetime | None:
    """Treat naive values as UTC (defensive: legacy data / tz-less timestamps).

    The rest of the code uses aware UTC. A naive ``valid_from``/``valid_until``
    from the DB would raise ``TypeError`` when compared with the aware ``now``,
    taking down the entire principal resolution (REST and WS handshake).
    """
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _assignment_valid(
    valid_from: datetime | None, valid_until: datetime | None, now: datetime
) -> bool:
    """Check the validity window (representation/delegation).

    ``now`` is always aware UTC (caller); only the DB columns may be naive.
    """
    valid_from = _as_aware(valid_from)
    valid_until = _as_aware(valid_until)
    after_start = valid_from is None or valid_from <= now
    before_end = valid_until is None or valid_until >= now
    return after_start and before_end


async def resolve_principal(db: AsyncSession, row: PrincipalRow, now: datetime) -> Principal:
    """Resolve a `principal` row into a full `Principal` (roles/permissions/groups)."""
    groups: set[str] = {str(g) for g in (row.oidc_groups or [])}
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

    # Gremium memberships: an active gremium role with ``vote.cast`` grants voting
    # eligibility. The cast gate checks the NAMESPACED key ``vote:<gremium_id>``
    # (``vote_group_key``), never the bare UUID string — so a matching OIDC group
    # claim cannot falsely satisfy gremium voting eligibility. Merely following a
    # meeting goes through ``MeetingService.is_member`` (separate query).
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
