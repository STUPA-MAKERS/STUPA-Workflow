"""Gremium roles and the read of the memberships.

This module stays separate from the global roles. It holds an own role catalog
(``gremium_role``). The memberships (``gremium_membership``) come from the OIDC groups
only. ``membership_sync`` writes them from the mappings in ``oidc_mappings``. Nobody
can set one by hand.

Core invariant: for each (principal, gremium) pair exactly one role is active.
The sync keeps it. The unique constraint on (principal, gremium) backs it.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import GremiumMembership, GremiumRole, GremiumRoleMapping
from app.modules.admin.schemas import (
    GremiumMembershipOut,
    GremiumRoleCreate,
    GremiumRoleOut,
    GremiumRoleUpdate,
)
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import AuditService
from app.modules.auth.models import Principal as PrincipalRow
from app.shared.errors import ConflictError, NotFoundError

#: Granular per-gremium-role permissions of the meeting domain. The global
#: permission set does not contain them. They apply inside the gremium only and
#: resolve through the active ``gremium_membership``.
#:   session.manage  — create/edit meetings, assign minute-taker, set status
#:   vote.manage     — open/close votes
#:   vote.cast       — vote in meeting votes
#:   protocol.write  — assignable as minute-taker / write the protocol
#:   protocol.finalize — finalize and send the protocol (together with the
#:                     write access to the meeting)
#:   todo.write      — read and work on the to-do board of the gremium (cards,
#:                     moves, comments, checklists, links)
#:   todo.configure  — edit the name, the columns and the labels of that board
#: An OAuth token caps these permissions through its scope. See
#: ``app.modules.auth.policy``.
GREMIUM_PERMISSIONS: tuple[str, ...] = (
    "session.manage",
    "vote.manage",
    "vote.cast",
    "protocol.write",
    "protocol.finalize",
    "todo.write",
    "todo.configure",
)
_ALL_PERMS: list[str] = list(GREMIUM_PERMISSIONS)

#: Forced gremium roles exist in EVERY gremium and nobody can delete them.
#: ``vorstand`` and ``manager`` get all permissions by default. ``member`` gets
#: vote.cast and todo.write. The service creates them together with the gremium and
#: backfills them idempotently on a listing.
FORCED_GREMIUM_ROLES: tuple[tuple[str, dict[str, str], list[str]], ...] = (
    ("vorstand", {"de": "Vorstand", "en": "Board"}, list(_ALL_PERMS)),
    ("manager", {"de": "Manager", "en": "Manager"}, list(_ALL_PERMS)),
    ("member", {"de": "Mitglied", "en": "Member"}, ["vote.cast", "todo.write"]),
)
FORCED_ROLE_KEYS: frozenset[str] = frozenset(key for key, _, _ in FORCED_GREMIUM_ROLES)
FORCED_ROLE_DEFAULT_PERMS: dict[str, list[str]] = {
    key: perms for key, _, perms in FORCED_GREMIUM_ROLES
}


async def active_gremium_roles(session: AsyncSession, sub: str) -> list[tuple[UUID, GremiumRole]]:
    """Return a principal's (gremium, role) pairs."""
    rows = (
        await session.execute(
            select(GremiumMembership.gremium_id, GremiumRole)
            .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
            .join(PrincipalRow, PrincipalRow.id == GremiumMembership.principal_id)
            .where(PrincipalRow.sub == sub)
        )
    ).all()
    return [(gid, role) for gid, role in rows]


async def gremium_ids_with_permission(session: AsyncSession, sub: str, perm: str) -> set[UUID]:
    """Return gremium ids where the principal's active role grants ``perm``.

    This is the roster read without a request principal. A request path uses
    ``app.modules.auth.policy``, which adds the OAuth scope cap.
    """
    return {
        gid
        for gid, role in await active_gremium_roles(session, sub)
        if perm in (role.permissions or [])
    }


async def gremium_member_ids(session: AsyncSession, sub: str) -> set[UUID]:
    """Return gremium ids where the principal is a member (any role)."""
    return {gid for gid, _ in await active_gremium_roles(session, sub)}


async def gremium_reader_ids(session: AsyncSession, sub: str) -> set[UUID]:
    """Return the Gremien whose committee read scope the principal holds.

    These are the memberships (`gremium_member_ids`) and the Gremien in whose
    substitute pool the principal stands. A pool substitute reads the applications,
    the cost centers and the meetings of the Gremium like a member. The pool gives no
    gremium permission (`vote.cast`, `todo.write`, ...): those stay with the roles.
    """
    from app.modules.delegations.pool import substitute_gremien_for_sub

    return await gremium_member_ids(session, sub) | await substitute_gremien_for_sub(
        session, sub
    )


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


def _membership_out(
    row: GremiumMembership,
    display_name: str | None = None,
    email: str | None = None,
    active: bool = True,
) -> GremiumMembershipOut:
    return GremiumMembershipOut(
        id=row.id,
        principal_id=row.principal_id,
        gremium_id=row.gremium_id,
        gremium_role_id=row.gremium_role_id,
        display_name=display_name,
        email=email,
        active=active,
    )


class GremiumRoleService:
    """CRUD for gremium roles, plus the membership read."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the service to a database session."""
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
        missing = tuple(
            (key, name, perms) for key, name, perms in FORCED_GREMIUM_ROLES if key not in present
        )
        for key, name, perms in missing:
            self.session.add(
                GremiumRole(
                    gremium_id=gremium_id,
                    key=key,
                    name_i18n=name,
                    permissions=list(perms),
                )
            )
        if missing:
            await self.session.flush()
        return bool(missing)

    async def list_roles(self, gremium_id: UUID) -> list[GremiumRoleOut]:
        """List the roles of a gremium, and backfill its forced roles first."""
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
        """Create a role in a gremium.

        Raises:
            ConflictError: The key exists in this gremium already.
        """
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
                f"gremium role {payload.key!r} already exists in this gremium",
                code="gremium_role_exists",
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
        """Update the name and the permissions of a role.

        A forced role also accepts permission edits. Only its key and its delete stay
        locked.

        Raises:
            NotFoundError: No gremium role has this id.
        """
        row = await self.session.get(GremiumRole, role_id)
        if row is None:
            raise NotFoundError(f"gremium role {role_id} not found")
        if payload.name is not None:
            row.name_i18n = payload.name
        if payload.permissions is not None:
            row.permissions = _sanitize_perms(payload.permissions)
        await self._audit(actor, "gremium_role", row.id)
        await self.session.commit()
        return _role_out(row)

    async def delete_role(self, role_id: UUID, actor: str) -> None:
        """Delete a role of a gremium.

        Raises:
            NotFoundError: No gremium role has this id.
            ConflictError: The role is forced or still in use.
        """
        row = await self.session.get(GremiumRole, role_id)
        if row is None:
            raise NotFoundError(f"gremium role {role_id} not found")
        if row.key in FORCED_ROLE_KEYS:
            raise ConflictError("forced gremium role cannot be deleted", code="gremium_role_forced")
        in_use = (
            await self.session.scalars(
                select(GremiumMembership.id).where(
                    GremiumMembership.gremium_role_id == role_id
                )
            )
        ).first()
        if in_use is not None:
            raise ConflictError(
                "gremium role is in use by a membership",
                code="gremium_role_in_use",
            )
        mapped = (
            await self.session.scalars(
                select(GremiumRoleMapping.id).where(
                    GremiumRoleMapping.gremium_role_id == role_id
                )
            )
        ).first()
        if mapped is not None:
            raise ConflictError(
                "gremium role is in use by a group mapping",
                code="gremium_role_mapped",
            )
        await self.session.delete(row)
        await self._audit(actor, "gremium_role", role_id)
        await self.session.commit()

    async def list_memberships(self, gremium_id: UUID) -> list[GremiumMembershipOut]:
        """List the memberships of a gremium with the name and e-mail of each member.

        Each row tells if it is active: the principal is active. This is the rule of
        the member count in the gremien list. A row without a principal row is not
        active.
        """
        rows = (
            await self.session.execute(
                select(
                    GremiumMembership,
                    PrincipalRow.display_name,
                    PrincipalRow.email,
                    PrincipalRow.active,
                )
                .outerjoin(PrincipalRow, PrincipalRow.id == GremiumMembership.principal_id)
                .where(GremiumMembership.gremium_id == gremium_id)
                .order_by(GremiumMembership.id)
            )
        ).all()
        return [
            _membership_out(m, name, email, active=bool(active))
            for m, name, email, active in rows
        ]
