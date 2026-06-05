"""RBAC-Auflösung (security.md §2, api.md §1).

App-seitige Rollen sind die Wahrheit: Permissions stammen aus `role_assignment`
(zeit-validiert: Vertretung/Delegation) **plus** optional `group_mapping`
(OIDC-Gruppe → Rolle, Komfort). Gremium-Scope eines Assignments/Mappings landet als
Gruppen-Key in `Principal.groups` (`require_group` greift darauf).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import GroupMapping, Role, RoleAssignment, RolePermission
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal


def _assignment_valid(
    valid_from: datetime | None, valid_until: datetime | None, now: datetime
) -> bool:
    """Gültigkeitsfenster (Vertretung/Delegation) prüfen."""
    after_start = valid_from is None or valid_from <= now
    before_end = valid_until is None or valid_until >= now
    return after_start and before_end


async def resolve_principal(db: AsyncSession, row: PrincipalRow, now: datetime) -> Principal:
    """`principal`-Zeile → vollständiger `Principal` (Rollen/Permissions/Gruppen)."""
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

    return Principal(
        sub=row.sub,
        email=row.email,
        display_name=row.display_name,
        roles=role_keys,
        permissions=permissions,
        groups=groups,
    )
