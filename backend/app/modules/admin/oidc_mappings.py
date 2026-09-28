"""OIDC group mappings for the gremien: membership and gremium role, kept separate.

- ``GremiumMembershipMapping``: an OIDC group makes a principal a member of a gremium.
- ``GremiumRoleMapping``: an OIDC group gives a member a role in a gremium.

The global roles have their own mapping (``group_mapping``, see ``service/rbac.py``).
Each write here audits the change, syncs the memberships of all principals and commits.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.membership_sync import sync_all_memberships
from app.modules.admin.models import (
    Gremium,
    GremiumMembershipMapping,
    GremiumRole,
    GremiumRoleMapping,
)
from app.modules.admin.schemas import (
    GremiumMembershipMappingCreate,
    GremiumMembershipMappingOut,
    GremiumMembershipMappingUpdate,
    GremiumRoleMappingCreate,
    GremiumRoleMappingOut,
    GremiumRoleMappingUpdate,
)
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import AuditService
from app.shared.errors import ConflictError, NotFoundError


def _membership_mapping_out(row: GremiumMembershipMapping) -> GremiumMembershipMappingOut:
    return GremiumMembershipMappingOut(
        id=row.id, gremium_id=row.gremium_id, oidc_group=row.oidc_group
    )


def _role_mapping_out(row: GremiumRoleMapping, gremium_id: UUID) -> GremiumRoleMappingOut:
    return GremiumRoleMappingOut(
        id=row.id,
        gremium_id=gremium_id,
        gremium_role_id=row.gremium_role_id,
        oidc_group=row.oidc_group,
    )


class OidcMappingService:
    """CRUD for the membership mappings and the gremium role mappings."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _flush(self, message: str) -> None:
        """Flush a mapping write. A duplicate violates a unique constraint and gives 409.

        Raises:
            ConflictError: The same mapping exists already (409).
        """
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(message, code="conflict") from exc

    async def _audit_sync_commit(self, actor: str, target_type: str, target_id: UUID) -> None:
        """Audit the mapping change, sync all memberships to it and commit."""
        await AuditService(self.session).record(
            actor=actor,
            action=AuditAction.ROLE_CHANGE,
            target_type=target_type,
            target_id=str(target_id),
            data={},
        )
        await sync_all_memberships(self.session)
        await self.session.commit()

    # ------------------------------------------------------------ membership

    async def _gremium_exists(self, gremium_id: UUID) -> None:
        if await self.session.get(Gremium, gremium_id) is None:
            raise NotFoundError(f"gremium {gremium_id} not found")

    async def list_membership_mappings(self) -> list[GremiumMembershipMappingOut]:
        rows = (
            await self.session.scalars(
                select(GremiumMembershipMapping).order_by(GremiumMembershipMapping.oidc_group)
            )
        ).all()
        return [_membership_mapping_out(r) for r in rows]

    async def create_membership_mapping(
        self, payload: GremiumMembershipMappingCreate, actor: str
    ) -> GremiumMembershipMappingOut:
        await self._gremium_exists(payload.gremium_id)
        row = GremiumMembershipMapping(
            gremium_id=payload.gremium_id, oidc_group=payload.oidc_group
        )
        self.session.add(row)
        await self._flush("this gremium already maps this OIDC group")
        await self._audit_sync_commit(actor, "gremium_membership_mapping", row.id)
        return _membership_mapping_out(row)

    async def update_membership_mapping(
        self, mapping_id: UUID, payload: GremiumMembershipMappingUpdate, actor: str
    ) -> GremiumMembershipMappingOut:
        row = await self.session.get(GremiumMembershipMapping, mapping_id)
        if row is None:
            raise NotFoundError(f"gremium membership mapping {mapping_id} not found")
        if payload.gremium_id is not None:
            await self._gremium_exists(payload.gremium_id)
            row.gremium_id = payload.gremium_id
        if payload.oidc_group is not None:
            row.oidc_group = payload.oidc_group
        await self._flush("this gremium already maps this OIDC group")
        await self._audit_sync_commit(actor, "gremium_membership_mapping", row.id)
        return _membership_mapping_out(row)

    async def delete_membership_mapping(self, mapping_id: UUID, actor: str) -> None:
        row = await self.session.get(GremiumMembershipMapping, mapping_id)
        if row is None:
            raise NotFoundError(f"gremium membership mapping {mapping_id} not found")
        await self.session.delete(row)
        await self.session.flush()
        await self._audit_sync_commit(actor, "gremium_membership_mapping", mapping_id)

    # ------------------------------------------------------------ role

    async def _role(self, role_id: UUID) -> GremiumRole:
        role = await self.session.get(GremiumRole, role_id)
        if role is None:
            raise NotFoundError(f"gremium role {role_id} not found")
        return role

    async def list_role_mappings(self) -> list[GremiumRoleMappingOut]:
        rows = (
            await self.session.execute(
                select(GremiumRoleMapping, GremiumRole.gremium_id)
                .join(GremiumRole, GremiumRole.id == GremiumRoleMapping.gremium_role_id)
                .order_by(GremiumRoleMapping.oidc_group)
            )
        ).all()
        return [_role_mapping_out(row, gremium_id) for row, gremium_id in rows]

    async def create_role_mapping(
        self, payload: GremiumRoleMappingCreate, actor: str
    ) -> GremiumRoleMappingOut:
        role = await self._role(payload.gremium_role_id)
        row = GremiumRoleMapping(gremium_role_id=role.id, oidc_group=payload.oidc_group)
        self.session.add(row)
        await self._flush("this gremium role already maps this OIDC group")
        await self._audit_sync_commit(actor, "gremium_role_mapping", row.id)
        return _role_mapping_out(row, role.gremium_id)

    async def update_role_mapping(
        self, mapping_id: UUID, payload: GremiumRoleMappingUpdate, actor: str
    ) -> GremiumRoleMappingOut:
        row = await self.session.get(GremiumRoleMapping, mapping_id)
        if row is None:
            raise NotFoundError(f"gremium role mapping {mapping_id} not found")
        role = await self._role(payload.gremium_role_id or row.gremium_role_id)
        row.gremium_role_id = role.id
        if payload.oidc_group is not None:
            row.oidc_group = payload.oidc_group
        await self._flush("this gremium role already maps this OIDC group")
        await self._audit_sync_commit(actor, "gremium_role_mapping", row.id)
        return _role_mapping_out(row, role.gremium_id)

    async def delete_role_mapping(self, mapping_id: UUID, actor: str) -> None:
        row = await self.session.get(GremiumRoleMapping, mapping_id)
        if row is None:
            raise NotFoundError(f"gremium role mapping {mapping_id} not found")
        await self.session.delete(row)
        await self.session.flush()
        await self._audit_sync_commit(actor, "gremium_role_mapping", mapping_id)
