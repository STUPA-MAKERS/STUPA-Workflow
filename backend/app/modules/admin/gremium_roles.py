"""Gremium roles, OIDC group mappings and the read of the memberships.

This module stays separate from the global roles. It holds an own role catalog
(``gremium_role``) and the mappings from an OIDC group to a gremium role
(``gremium_group_mapping``). The memberships (``gremium_membership``) come from the
OIDC groups only. ``membership_sync`` writes them. Nobody can set one by hand.

Core invariant: for each (principal, gremium) pair exactly one role is active.
The sync keeps it. The EXCLUDE constraint on the table backs it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.membership_sync import sync_all_memberships
from app.modules.admin.models import GremiumGroupMapping, GremiumMembership, GremiumRole
from app.modules.admin.schemas import (
    GremiumGroupMappingCreate,
    GremiumGroupMappingOut,
    GremiumGroupMappingUpdate,
    GremiumMembershipOut,
    GremiumRoleCreate,
    GremiumRoleOut,
    GremiumRoleUpdate,
)
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import AuditService
from app.modules.auth.models import Principal as PrincipalRow
from app.shared.errors import ConflictError, NotFoundError

# Granular per-gremium-role permissions of the meeting domain. The global
# permission set does not contain them. They apply inside the gremium only and
# resolve through the active ``gremium_membership``.
#   session.manage  — create/edit meetings, assign minute-taker, set status
#   vote.manage     — open/close votes
#   vote.cast       — vote in meeting votes
#   protocol.write  — assignable as minute-taker / write the protocol
GREMIUM_PERMISSIONS: tuple[str, ...] = (
    "session.manage",
    "vote.manage",
    "vote.cast",
    "protocol.write",
)
_ALL_PERMS: list[str] = list(GREMIUM_PERMISSIONS)

# Forced gremium roles exist in EVERY gremium and nobody can delete them.
# ``vorstand`` and ``manager`` get all permissions by default. ``member`` gets
# vote.cast only. The service creates them together with the gremium and
# backfills them idempotently on a listing. Migration 0040 backfilled the
# gremien that already existed.
FORCED_GREMIUM_ROLES: tuple[tuple[str, dict[str, str], list[str]], ...] = (
    ("vorstand", {"de": "Vorstand", "en": "Board"}, list(_ALL_PERMS)),
    ("manager", {"de": "Manager", "en": "Manager"}, list(_ALL_PERMS)),
    ("member", {"de": "Mitglied", "en": "Member"}, ["vote.cast"]),
)
FORCED_ROLE_KEYS: frozenset[str] = frozenset(key for key, _, _ in FORCED_GREMIUM_ROLES)
FORCED_ROLE_DEFAULT_PERMS: dict[str, list[str]] = {
    key: perms for key, _, perms in FORCED_GREMIUM_ROLES
}


def _time_valid_clause(now: datetime):
    """SQLAlchemy clause: the ``gremium_membership`` is active at ``now``."""
    return (
        (GremiumMembership.valid_from.is_(None))
        | (GremiumMembership.valid_from <= now)
    ) & (
        (GremiumMembership.valid_until.is_(None))
        | (GremiumMembership.valid_until > now)
    )


async def active_gremium_roles(
    session: AsyncSession, sub: str, now: datetime | None = None
) -> list[tuple[UUID, GremiumRole]]:
    """Return a principal's active (gremium, role) pairs (time-validated)."""
    now = now or datetime.now(UTC)
    rows = (
        await session.execute(
            select(GremiumMembership.gremium_id, GremiumRole)
            .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
            .join(PrincipalRow, PrincipalRow.id == GremiumMembership.principal_id)
            .where(PrincipalRow.sub == sub, _time_valid_clause(now))
        )
    ).all()
    return [(gid, role) for gid, role in rows]


async def gremium_ids_with_permission(
    session: AsyncSession, sub: str, perm: str, now: datetime | None = None
) -> set[UUID]:
    """Return gremium ids where the principal's active role grants ``perm``."""
    return {
        gid
        for gid, role in await active_gremium_roles(session, sub, now)
        if perm in (role.permissions or [])
    }


async def gremium_member_ids(
    session: AsyncSession, sub: str, now: datetime | None = None
) -> set[UUID]:
    """Return gremium ids where the principal is currently a member (any role)."""
    return {gid for gid, _ in await active_gremium_roles(session, sub, now)}


def _sanitize_perms(perms: list[str] | None) -> list[str]:
    """Keep only known gremium permissions, deduplicated, in catalog order."""
    given = set(perms or [])
    return [p for p in GREMIUM_PERMISSIONS if p in given]


def _role_out(row: GremiumRole) -> GremiumRoleOut:
    return GremiumRoleOut(
        id=row.id,
        gremium_id=row.gremium_id,
        key=row.key,
        name=row.name_i18n or {},
        forced=row.key in FORCED_ROLE_KEYS,
        permissions=list(row.permissions or []),
    )


def _membership_out(row: GremiumMembership) -> GremiumMembershipOut:
    return GremiumMembershipOut(
        id=row.id,
        principal_id=row.principal_id,
        gremium_id=row.gremium_id,
        gremium_role_id=row.gremium_role_id,
    )


def _mapping_out(row: GremiumGroupMapping) -> GremiumGroupMappingOut:
    return GremiumGroupMappingOut(
        id=row.id,
        gremium_id=row.gremium_id,
        gremium_role_id=row.gremium_role_id,
        oidc_group=row.oidc_group,
    )


class GremiumRoleService:
    """CRUD for gremium roles and group mappings, plus the membership read."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _audit(self, actor: str, target_type: str, target_id: object) -> None:
        await AuditService(self.session).record(
            actor=actor,
            action=AuditAction.ROLE_CHANGE,
            target_type=target_type,
            target_id=str(target_id),
            data={},
        )

    async def ensure_forced_roles(self, gremium_id: UUID) -> bool:
        """Create the missing forced roles of a gremium.

        The call is idempotent. It does not commit, because the caller controls
        the transaction.

        Returns:
            True if the call created at least one role.
        """
        present = set(
            (
                await self.session.scalars(
                    select(GremiumRole.key).where(GremiumRole.gremium_id == gremium_id)
                )
            ).all()
        )
        added = False
        for key, name, perms in FORCED_GREMIUM_ROLES:
            if key not in present:
                self.session.add(
                    GremiumRole(
                        gremium_id=gremium_id,
                        key=key,
                        name_i18n=name,
                        permissions=list(perms),
                    )
                )
                added = True
        if added:
            await self.session.flush()
        return added

    async def list_roles(self, gremium_id: UUID) -> list[GremiumRoleOut]:
        # Lazily backfill existing gremien so the forced roles are always present.
        if await self.ensure_forced_roles(gremium_id):
            await self.session.commit()
        rows = (
            await self.session.scalars(
                select(GremiumRole)
                .where(GremiumRole.gremium_id == gremium_id)
                .order_by(GremiumRole.key)
            )
        ).all()
        return [_role_out(r) for r in rows]

    async def create_role(
        self, gremium_id: UUID, payload: GremiumRoleCreate, actor: str
    ) -> GremiumRoleOut:
        existing = (
            await self.session.scalars(
                select(GremiumRole).where(
                    GremiumRole.gremium_id == gremium_id,
                    GremiumRole.key == payload.key,
                )
            )
        ).first()
        if existing is not None:
            raise ConflictError(
                f"gremium role {payload.key!r} already exists in this gremium"
            )
        row = GremiumRole(
            gremium_id=gremium_id,
            key=payload.key,
            name_i18n=payload.name,
            permissions=_sanitize_perms(payload.permissions),
        )
        self.session.add(row)
        await self.session.flush()
        await self._audit(actor, "gremium_role", row.id)
        await self.session.commit()
        return _role_out(row)

    async def update_role(
        self, role_id: UUID, payload: GremiumRoleUpdate, actor: str
    ) -> GremiumRoleOut:
        row = await self.session.get(GremiumRole, role_id)
        if row is None:
            raise NotFoundError(f"gremium role {role_id} not found")
        if payload.name is not None:
            row.name_i18n = payload.name
        if payload.permissions is not None:
            # A forced role also accepts permission edits. Only the key and the
            # delete stay locked.
            row.permissions = _sanitize_perms(payload.permissions)
        await self._audit(actor, "gremium_role", row.id)
        await self.session.commit()
        return _role_out(row)

    async def delete_role(self, role_id: UUID, actor: str) -> None:
        row = await self.session.get(GremiumRole, role_id)
        if row is None:
            raise NotFoundError(f"gremium role {role_id} not found")
        if row.key in FORCED_ROLE_KEYS:
            raise ConflictError("forced gremium role cannot be deleted")
        in_use = (
            await self.session.scalars(
                select(GremiumMembership.id).where(
                    GremiumMembership.gremium_role_id == role_id
                )
            )
        ).first()
        if in_use is not None:
            raise ConflictError("gremium role is in use by a membership")
        mapped = (
            await self.session.scalars(
                select(GremiumGroupMapping.id).where(
                    GremiumGroupMapping.gremium_role_id == role_id
                )
            )
        ).first()
        if mapped is not None:
            raise ConflictError("gremium role is in use by a group mapping")
        await self.session.delete(row)
        await self._audit(actor, "gremium_role", role_id)
        await self.session.commit()

    async def list_memberships(self, gremium_id: UUID) -> list[GremiumMembershipOut]:
        rows = (
            await self.session.scalars(
                select(GremiumMembership)
                .where(GremiumMembership.gremium_id == gremium_id)
                .order_by(GremiumMembership.valid_from)
            )
        ).all()
        return [_membership_out(r) for r in rows]

    async def list_group_mappings(self, gremium_id: UUID) -> list[GremiumGroupMappingOut]:
        rows = (
            await self.session.scalars(
                select(GremiumGroupMapping)
                .where(GremiumGroupMapping.gremium_id == gremium_id)
                .order_by(GremiumGroupMapping.oidc_group)
            )
        ).all()
        return [_mapping_out(r) for r in rows]

    async def _role_in_gremium(self, role_id: UUID, gremium_id: UUID) -> None:
        """Check that the role exists and belongs to the gremium.

        Raises:
            NotFoundError: The role does not exist (404).
            ConflictError: The role belongs to another gremium (409).
        """
        role = await self.session.get(GremiumRole, role_id)
        if role is None:
            raise NotFoundError(f"gremium role {role_id} not found")
        if role.gremium_id != gremium_id:
            raise ConflictError("gremium role does not belong to this gremium")

    async def _flush_mapping(self) -> None:
        """Flush a mapping write.

        A second mapping with the same group in the same gremium violates the
        unique constraint at the flush. That gives 409, not 500.

        Raises:
            ConflictError: The gremium already maps this group (409).
        """
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(
                "this gremium already maps this OIDC group", code="conflict"
            ) from exc

    async def _audit_sync_commit(self, actor: str, mapping_id: UUID) -> None:
        """Audit the mapping change, sync all memberships to it and commit."""
        await self._audit(actor, "gremium_group_mapping", mapping_id)
        await sync_all_memberships(self.session)
        await self.session.commit()

    async def create_group_mapping(
        self, gremium_id: UUID, payload: GremiumGroupMappingCreate, actor: str
    ) -> GremiumGroupMappingOut:
        await self._role_in_gremium(payload.gremium_role_id, gremium_id)
        row = GremiumGroupMapping(
            gremium_id=gremium_id,
            gremium_role_id=payload.gremium_role_id,
            oidc_group=payload.oidc_group,
        )
        self.session.add(row)
        await self._flush_mapping()
        await self._audit_sync_commit(actor, row.id)
        return _mapping_out(row)

    async def update_group_mapping(
        self, mapping_id: UUID, payload: GremiumGroupMappingUpdate, actor: str
    ) -> GremiumGroupMappingOut:
        row = await self.session.get(GremiumGroupMapping, mapping_id)
        if row is None:
            raise NotFoundError(f"gremium group mapping {mapping_id} not found")
        if payload.gremium_role_id is not None:
            await self._role_in_gremium(payload.gremium_role_id, row.gremium_id)
            row.gremium_role_id = payload.gremium_role_id
        if payload.oidc_group is not None:
            row.oidc_group = payload.oidc_group
        await self._flush_mapping()
        await self._audit_sync_commit(actor, row.id)
        return _mapping_out(row)

    async def delete_group_mapping(self, mapping_id: UUID, actor: str) -> None:
        row = await self.session.get(GremiumGroupMapping, mapping_id)
        if row is None:
            raise NotFoundError(f"gremium group mapping {mapping_id} not found")
        await self.session.delete(row)
        await self.session.flush()
        await self._audit_sync_commit(actor, mapping_id)
