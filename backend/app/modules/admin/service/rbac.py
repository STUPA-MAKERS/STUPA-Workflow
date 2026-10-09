"""RBAC administration: roles, principals, group mappings, and the assignment read.

Global roles come from OIDC groups through ``group_mapping``. The only
``role_assignment`` rows are the ones that the bootstrap grants (``admin`` from the
settings and the implicit ``member``). The admin API lists them but cannot write them.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from uuid import UUID

from sqlalchemy import delete, or_, select

from app.modules.admin.principal_revoke import (
    has_groups_filter,
    last_login_filter,
    principals_with_access,
)
from app.modules.admin.schemas import (
    GroupMappingCreate,
    GroupMappingOut,
    GroupMappingUpdate,
    PrincipalOut,
    RoleAssignmentOut,
    RoleCreate,
    RoleOut,
    RoleUpdate,
)
from app.modules.admin.service.service_base import ConfigServiceBase, _iso
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
    row: Principal,
    assignments: list[RoleAssignmentRow],
    merged_names: dict[UUID, str | None] | None = None,
    *,
    has_access: bool = False,
) -> PrincipalOut:
    return PrincipalOut(
        id=row.id,
        sub=row.sub,
        email=row.email,
        display_name=row.display_name,
        last_login=_iso(row.last_login),
        active=True if row.active is None else row.active,
        assignments=[_assignment_out(a) for a in assignments],
        oidc_groups=[str(g) for g in (row.oidc_groups or [])],
        merged_into_id=row.merged_into,
        merged_into_name=(
            (merged_names or {}).get(row.merged_into) if row.merged_into else None
        ),
        merged_at=_iso(row.merged_at),
        has_access=has_access or bool(row.oidc_groups),
    )


def _mapping_out(row: GroupMapping) -> GroupMappingOut:
    return GroupMappingOut(
        id=row.id,
        oidc_group=row.oidc_group,
        role_id=row.role_id,
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
        """Delete a role.

        The roles ``admin`` and ``member`` are protected. Assignments and
        permissions cascade through the FK ``ON DELETE CASCADE``.

        Raises:
            NotFoundError: No role has this id (404).
            ConflictError: The role is protected.
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

    async def search_principals(
        self,
        query: str | None,
        limit: int = 50,
        *,
        last_login_before: date | None = None,
        include_never: bool = False,
        has_groups: bool | None = None,
    ) -> list[PrincipalOut]:
        """Search principals (users) by OIDC ``sub``, name or e-mail.

        ``query`` matches as a case-insensitive substring. The e-mail column is
        CITEXT and therefore case-insensitive anyway. Without ``query`` the
        search returns the first ``limit`` principals.

        The filters of the user list (F3): ``last_login_before`` keeps the people
        whose last login is before that day, ``include_never`` adds the people who
        never logged in (alone: only those), ``has_groups`` keeps the people with
        (true) or without (false) OIDC groups.

        Returns:
            The principals with their role assignments and ``hasAccess``. One
            follow-up query loads the assignments and one the access ties, so there
            is no N+1.
        """
        stmt = select(Principal)
        for clause in (
            last_login_filter(last_login_before, include_never),
            has_groups_filter(has_groups),
        ):
            if clause is not None:
                stmt = stmt.where(clause)
        if query:
            # Escape the LIKE metacharacters in user input. Without the escape,
            # % and _ act as wildcards and allow wildcard injection or an index
            # bypass.
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
        access = await principals_with_access(self.session, ids)
        merged_names = await self._merged_names(rows)
        return [
            _principal_out(
                r, by_principal.get(r.id, []), merged_names, has_access=r.id in access
            )
            for r in rows
        ]

    async def _merged_names(self, rows: Sequence[Principal]) -> dict[UUID, str | None]:
        """Name the accounts that the merged rows point at. One query."""
        from app.modules.auth.identity import refs_by_id

        refs = await refs_by_id(self.session, {r.merged_into for r in rows if r.merged_into})
        return {pid: ref.name for pid, ref in refs.items()}

    async def set_principal_active(
        self, principal_id: UUID, active: bool, actor: str
    ) -> PrincipalOut:
        """Activate or deactivate a user.

        ``actor`` is the OIDC ``sub`` of the caller.

        Raises:
            NotFoundError: No principal has this id (404).
            ConflictError: The caller tries to deactivate their own account.
                This is the self-lockout guard.
        """
        principal = await self.session.get(Principal, principal_id)
        if principal is None:
            raise NotFoundError(f"principal {principal_id} not found")
        if not active and principal.sub == actor:
            raise ConflictError("you cannot deactivate your own account")
        if active and principal.merged_into is not None:
            # A merged account is a locked reference. It never logs in again.
            raise ConflictError(
                "a merged account cannot be activated", code="principal_merged"
            )
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
        return _principal_out(
            principal, list(assignments), await self._merged_names([principal])
        )

    def list_permissions(self) -> list[str]:
        """Return the catalog of permission keys for the roles and permissions UI."""
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
