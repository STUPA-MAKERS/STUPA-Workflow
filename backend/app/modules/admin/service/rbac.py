"""RBAC administration: roles, role assignments, principals, group mappings."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, or_, select

from app.modules.admin.schemas import (
    GroupMappingCreate,
    GroupMappingOut,
    GroupMappingUpdate,
    PrincipalOut,
    RoleAssignmentCreate,
    RoleAssignmentOut,
    RoleAssignmentUpdate,
    RoleCreate,
    RoleOut,
    RoleUpdate,
)
from app.modules.admin.service.service_base import ConfigServiceBase, _iso, _parse_dt
from app.modules.audit.actions import AuditAction
from app.modules.auth.models import GroupMapping, Principal, Role, RolePermission
from app.modules.auth.models import RoleAssignment as RoleAssignmentRow
from app.search import escape_like
from app.shared.errors import ConflictError, NotFoundError
from app.shared.permissions import PERMISSION_CATALOGUE


def _assignment_out(row: RoleAssignmentRow) -> RoleAssignmentOut:
    return RoleAssignmentOut(
        id=row.id,
        principal_id=row.principal_id,
        role_id=row.role_id,
        gremium_id=row.gremium_id,
        granted_by=row.granted_by,
        valid_from=_iso(row.valid_from),
        valid_until=_iso(row.valid_until),
        delegate_voting=row.delegate_voting,
    )


def _principal_out(
    row: Principal, assignments: list[RoleAssignmentRow]
) -> PrincipalOut:
    return PrincipalOut(
        id=row.id,
        sub=row.sub,
        email=row.email,
        display_name=row.display_name,
        last_login=_iso(row.last_login),
        active=True if row.active is None else row.active,
        assignments=[_assignment_out(a) for a in assignments],
    )


def _mapping_out(row: GroupMapping) -> GroupMappingOut:
    return GroupMappingOut(
        id=row.id,
        oidc_group=row.oidc_group,
        role_id=row.role_id,
        gremium_id=row.gremium_id,
    )


class RbacOps(ConfigServiceBase):
    """Roles, role assignments, principals and OIDC group mappings."""

    async def list_roles(self) -> list[RoleOut]:
        roles = (await self.session.scalars(select(Role).order_by(Role.key))).all()
        perms = (await self.session.scalars(select(RolePermission))).all()
        by_role: dict[UUID, list[str]] = {}
        for p in perms:
            by_role.setdefault(p.role_id, []).append(p.permission)
        return [
            RoleOut(
                id=r.id,
                key=r.key,
                label=r.name_i18n,
                permissions=sorted(by_role.get(r.id, [])),
            )
            for r in roles
        ]

    async def create_role(self, payload: RoleCreate, actor: str) -> RoleOut:
        existing = (
            await self.session.scalars(select(Role).where(Role.key == payload.key))
        ).first()
        if existing is not None:
            raise ConflictError(f"role {payload.key!r} already exists")
        role = Role(key=payload.key, name_i18n=payload.label)
        self.session.add(role)
        await self.session.flush()
        for perm in set(payload.permissions):
            self.session.add(RolePermission(role_id=role.id, permission=perm))
        await self._audit(actor, AuditAction.ROLE_CHANGE, "role", role.id)
        await self.session.commit()
        return RoleOut(
            id=role.id,
            key=role.key,
            label=role.name_i18n,
            permissions=sorted(set(payload.permissions)),
        )

    async def update_role(
        self, role_id: UUID, payload: RoleUpdate, actor: str
    ) -> RoleOut:
        role = await self.session.get(Role, role_id)
        if role is None:
            raise NotFoundError(f"role {role_id} not found")
        if payload.label is not None:
            role.name_i18n = payload.label
        if payload.permissions is not None:
            await self.session.execute(
                delete(RolePermission).where(RolePermission.role_id == role_id)
            )
            for perm in set(payload.permissions):
                self.session.add(RolePermission(role_id=role_id, permission=perm))
        await self._audit(actor, AuditAction.ROLE_CHANGE, "role", role.id)
        await self.session.commit()
        perms = (
            await self.session.scalars(
                select(RolePermission.permission).where(
                    RolePermission.role_id == role_id
                )
            )
        ).all()
        return RoleOut(
            id=role.id, key=role.key, label=role.name_i18n, permissions=sorted(perms)
        )

    async def delete_role(self, role_id: UUID, actor: str) -> None:
        """Delete a role; ``admin``/``member`` are protected.

        Assignments and permissions cascade (FK ``ON DELETE CASCADE``).
        Unknown id → 404.
        """
        role = await self.session.get(Role, role_id)
        if role is None:
            raise NotFoundError(f"role {role_id} not found")
        if role.key in ("admin", "member"):
            raise ConflictError(f"role {role.key!r} is protected and cannot be deleted")
        await self._audit(actor, AuditAction.ROLE_CHANGE, "role", role.id)
        await self.session.delete(role)
        await self.session.commit()

    async def list_role_assignments(self) -> list[RoleAssignmentOut]:
        rows = (await self.session.scalars(select(RoleAssignmentRow))).all()
        return [_assignment_out(r) for r in rows]

    async def create_role_assignment(
        self, payload: RoleAssignmentCreate, actor: str
    ) -> RoleAssignmentOut:
        if await self.session.get(Principal, payload.principal_id) is None:
            raise NotFoundError(f"principal {payload.principal_id} not found")
        if await self.session.get(Role, payload.role_id) is None:
            raise NotFoundError(f"role {payload.role_id} not found")
        row = RoleAssignmentRow(
            principal_id=payload.principal_id,
            role_id=payload.role_id,
            gremium_id=payload.gremium_id,
            granted_by=actor,
            valid_from=_parse_dt(payload.valid_from),
            valid_until=_parse_dt(payload.valid_until),
            delegate_voting=payload.delegate_voting,
        )
        self.session.add(row)
        await self.session.flush()
        await self._audit(actor, AuditAction.ROLE_CHANGE, "role_assignment", row.id)
        await self.session.commit()
        return _assignment_out(row)

    async def update_role_assignment(
        self, assignment_id: UUID, payload: RoleAssignmentUpdate, actor: str
    ) -> RoleAssignmentOut:
        row = await self.session.get(RoleAssignmentRow, assignment_id)
        if row is None:
            raise NotFoundError(f"role assignment {assignment_id} not found")
        # Prevent self-lockout: ANY mutation of one's own admin assignment is
        # forbidden — e.g. expiring it via a past valid_until. Global role
        # permissions are deliberately not gremium-scoped, so the guard applies
        # uniformly to all fields.
        await self._guard_self_admin_removal(row, actor)
        if payload.role_id is not None:
            if await self.session.get(Role, payload.role_id) is None:
                raise NotFoundError(f"role {payload.role_id} not found")
            row.role_id = payload.role_id
        if payload.gremium_id is not None:
            row.gremium_id = payload.gremium_id
        if payload.valid_from is not None:
            row.valid_from = _parse_dt(payload.valid_from)
        if payload.valid_until is not None:
            row.valid_until = _parse_dt(payload.valid_until)
        if payload.delegate_voting is not None:
            row.delegate_voting = payload.delegate_voting
        await self._audit(actor, AuditAction.ROLE_CHANGE, "role_assignment", row.id)
        await self.session.commit()
        return _assignment_out(row)

    async def delete_role_assignment(self, assignment_id: UUID, actor: str) -> None:
        """Revoke a role: delete the assignment and audit it."""
        row = await self.session.get(RoleAssignmentRow, assignment_id)
        if row is None:
            raise NotFoundError(f"role assignment {assignment_id} not found")
        # Prevent self-lockout: never remove one's own admin role.
        await self._guard_self_admin_removal(row, actor)
        # The global base role member is irrevocable: every user always keeps it.
        role = await self.session.get(Role, row.role_id)
        if role is not None and role.key == "member" and row.gremium_id is None:
            raise ConflictError("the member role cannot be removed")
        await self.session.delete(row)
        await self._audit(actor, AuditAction.ROLE_CHANGE, "role_assignment", assignment_id)
        await self.session.commit()

    async def _guard_self_admin_removal(
        self, row: RoleAssignmentRow, actor: str
    ) -> None:
        """Prevent admins from removing their own admin role.

        ``actor`` is the OIDC ``sub``; an admin assignment of the caller's own
        principal must not be deleted or rewritten (self-lockout).
        """
        role = await self.session.get(Role, row.role_id)
        if role is None or role.key != "admin":
            return
        principal = await self.session.get(Principal, row.principal_id)
        if principal is not None and principal.sub == actor:
            raise ConflictError("admins cannot remove their own admin role")

    async def search_principals(
        self, query: str | None, limit: int = 50
    ) -> list[PrincipalOut]:
        """Search principals (users) by OIDC ``sub``/name/e-mail.

        Without ``query`` the first ``limit`` principals are returned; with
        ``query`` a case-insensitive substring match (the CITEXT e-mail is ci
        anyway). Includes each principal's role assignments (one follow-up
        query, no N+1).
        """
        stmt = select(Principal)
        if query:
            # Escape LIKE metacharacters in user input — otherwise %/_ act as
            # wildcards (wildcard injection / index bypass).
            like = f"%{escape_like(query)}%"
            stmt = stmt.where(
                or_(
                    Principal.sub.ilike(like, escape="\\"),
                    Principal.email.ilike(like, escape="\\"),
                    Principal.display_name.ilike(like, escape="\\"),
                )
            )
        stmt = stmt.order_by(Principal.display_name, Principal.sub).limit(limit)
        rows = (await self.session.scalars(stmt)).all()
        ids = [r.id for r in rows]
        by_principal: dict[UUID, list[RoleAssignmentRow]] = {}
        if ids:
            assignments = (
                await self.session.scalars(
                    select(RoleAssignmentRow).where(
                        RoleAssignmentRow.principal_id.in_(ids)
                    )
                )
            ).all()
            for a in assignments:
                by_principal.setdefault(a.principal_id, []).append(a)
        return [_principal_out(r, by_principal.get(r.id, [])) for r in rows]

    async def set_principal_active(
        self, principal_id: UUID, active: bool, actor: str
    ) -> PrincipalOut:
        """Activate/deactivate a user; 404 for unknown ids.

        Self-lockout guard: the caller (OIDC ``sub``) cannot deactivate their
        own account.
        """
        principal = await self.session.get(Principal, principal_id)
        if principal is None:
            raise NotFoundError(f"principal {principal_id} not found")
        if not active and principal.sub == actor:
            raise ConflictError("you cannot deactivate your own account")
        principal.active = active
        await self._audit(actor, AuditAction.ROLE_CHANGE, "principal", principal.id)
        await self.session.commit()
        assignments = (
            await self.session.scalars(
                select(RoleAssignmentRow).where(
                    RoleAssignmentRow.principal_id == principal_id
                )
            )
        ).all()
        return _principal_out(principal, list(assignments))

    def list_permissions(self) -> list[str]:
        """Catalogue of selectable permission keys for the roles/permissions UI."""
        return list(PERMISSION_CATALOGUE)

    async def list_group_mappings(self) -> list[GroupMappingOut]:
        rows = (await self.session.scalars(select(GroupMapping))).all()
        return [_mapping_out(r) for r in rows]

    async def create_group_mapping(
        self, payload: GroupMappingCreate, actor: str
    ) -> GroupMappingOut:
        if await self.session.get(Role, payload.role_id) is None:
            raise NotFoundError(f"role {payload.role_id} not found")
        row = GroupMapping(
            oidc_group=payload.oidc_group,
            role_id=payload.role_id,
            gremium_id=payload.gremium_id,
        )
        self.session.add(row)
        await self.session.flush()
        await self._audit(actor, AuditAction.ROLE_CHANGE, "group_mapping", row.id)
        await self.session.commit()
        return _mapping_out(row)

    async def update_group_mapping(
        self, mapping_id: UUID, payload: GroupMappingUpdate, actor: str
    ) -> GroupMappingOut:
        row = await self.session.get(GroupMapping, mapping_id)
        if row is None:
            raise NotFoundError(f"group mapping {mapping_id} not found")
        if payload.role_id is not None:
            if await self.session.get(Role, payload.role_id) is None:
                raise NotFoundError(f"role {payload.role_id} not found")
            row.role_id = payload.role_id
        if payload.oidc_group is not None:
            row.oidc_group = payload.oidc_group
        if payload.gremium_id is not None:
            row.gremium_id = payload.gremium_id
        await self._audit(actor, AuditAction.ROLE_CHANGE, "group_mapping", row.id)
        await self.session.commit()
        return _mapping_out(row)

    async def delete_group_mapping(self, mapping_id: UUID, actor: str) -> None:
        row = await self.session.get(GroupMapping, mapping_id)
        if row is None:
            raise NotFoundError(f"group mapping {mapping_id} not found")
        await self._audit(actor, AuditAction.ROLE_CHANGE, "group_mapping", row.id)
        await self.session.delete(row)
        await self.session.commit()
