"""Gremium roles and the read of the memberships.

This module stays separate from the global roles. It holds an own role catalog
(``gremium_role``). The memberships (``gremium_membership``) come from the OIDC groups
only. ``membership_sync`` writes them from the mappings in ``oidc_mappings``. Nobody
can set one by hand.

Core invariant: for each (principal, gremium) pair exactly one role is active.
The sync keeps it. The EXCLUDE constraint on the table backs it.
"""

from __future__ import annotations

from datetime import UTC, datetime
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
from app.modules.auth.principal import Principal as AuthPrincipal
from app.shared.errors import ConflictError, NotFoundError

# Granular per-gremium-role permissions of the meeting domain. The global
# permission set does not contain them. They apply inside the gremium only and
# resolve through the active ``gremium_membership``.
#   session.manage  — create/edit meetings, assign minute-taker, set status
#   vote.manage     — open/close votes
#   vote.cast       — vote in meeting votes
#   protocol.write  — assignable as minute-taker / write the protocol
#   protocol.finalize — finalize and send the protocol (together with the
#                     write access to the meeting)
#   todo.write      — read and work on the to-do board of the gremium (cards,
#                     moves, comments, checklists, links)
#   todo.configure  — edit the name, the columns and the labels of that board
# An OAuth token caps these permissions through its scope. See
# ``gremium_ids_for``.
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

# Forced gremium roles exist in EVERY gremium and nobody can delete them.
# ``vorstand`` and ``manager`` get all permissions by default. ``member`` gets
# vote.cast and todo.write. The service creates them together with the gremium and
# backfills them idempotently on a listing. Migration 0040 backfilled the
# gremien that already existed.
FORCED_GREMIUM_ROLES: tuple[tuple[str, dict[str, str], list[str]], ...] = (
    ("vorstand", {"de": "Vorstand", "en": "Board"}, list(_ALL_PERMS)),
    ("manager", {"de": "Manager", "en": "Manager"}, list(_ALL_PERMS)),
    ("member", {"de": "Mitglied", "en": "Member"}, ["vote.cast", "todo.write"]),
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


async def gremium_ids_for(
    session: AsyncSession,
    principal: AuthPrincipal,
    perm: str,
    now: datetime | None = None,
) -> set[UUID]:
    """Return the gremium ids where ``principal`` can use ``perm``, scope-capped.

    Use this function on every path that acts for a logged-in principal. A scoped
    OAuth token gets the empty set when its scope does not contain ``perm``. Thus a
    ``read`` token cannot use ``session.manage`` or ``protocol.write``, whatever the
    gremium roles of its owner are.

    The sub-based ``gremium_ids_with_permission`` stays for the system and roster
    paths that have no request principal (principal resolution, quorum count,
    delegation eligibility, mail recipients).
    """
    if not principal.scope_allows(perm):
        return set()
    return await gremium_ids_with_permission(session, principal.sub, perm, now)


def admin_bypass(principal: AuthPrincipal, perm: str) -> bool:
    """Tell if the admin role lets ``principal`` use ``perm`` in every gremium.

    The bypass applies the scope cap: an admin token without ``perm`` in its scope
    does not get it.
    """
    return principal.is_admin and principal.scope_allows(perm)


async def gremium_member_ids(
    session: AsyncSession, sub: str, now: datetime | None = None
) -> set[UUID]:
    """Return gremium ids where the principal is currently a member (any role)."""
    return {gid for gid, _ in await active_gremium_roles(session, sub, now)}


# Global permission that lets a principal see every Gremium, not only the Gremien
# it is a member of. The admin role holds it through the admin bypass of `has`.
GREMIUM_VIEW_ALL = "gremium.view_all"


async def can_view_gremium(
    session: AsyncSession,
    principal: AuthPrincipal,
    gremium_id: UUID,
    now: datetime | None = None,
) -> bool:
    """Tell if ``principal`` may see the Gremium ``gremium_id``.

    A principal sees a Gremium when it holds the global permission
    ``gremium.view_all`` (the admin role included, scope-capped through ``has``),
    or when it is an active member of the Gremium now. The membership path also
    obeys the OAuth scope cap, so a token without the ``read`` scope sees no
    Gremium. A read route that refuses answers 404, not 403, so the answer does
    not tell that the Gremium exists.
    """
    visible = await gremium_view_scope(session, principal, now)
    return visible is None or gremium_id in visible


async def gremium_view_scope(
    session: AsyncSession,
    principal: AuthPrincipal,
    now: datetime | None = None,
) -> set[UUID] | None:
    """Return the Gremien that ``principal`` may see: ``None`` for every Gremium.

    The set form of ``can_view_gremium``, for a reader that checks many Gremien at
    once (the to-do links): ``gremium.view_all`` gives ``None``, a token without the
    ``read`` scope the empty set, anyone else the active memberships now.
    """
    if principal.has(GREMIUM_VIEW_ALL):
        return None
    if not principal.scope_allows(GREMIUM_VIEW_ALL):
        return set()
    return await gremium_member_ids(session, principal.sub, now)


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


def _valid_at(row: GremiumMembership, now: datetime) -> bool:
    """Return True if the membership is valid at ``now`` (see ``_time_valid_clause``)."""
    return (row.valid_from is None or row.valid_from <= now) and (
        row.valid_until is None or row.valid_until > now
    )


class GremiumRoleService:
    """CRUD for gremium roles, plus the membership read."""

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
                select(GremiumRoleMapping.id).where(
                    GremiumRoleMapping.gremium_role_id == role_id
                )
            )
        ).first()
        if mapped is not None:
            raise ConflictError("gremium role is in use by a group mapping")
        await self.session.delete(row)
        await self._audit(actor, "gremium_role", role_id)
        await self.session.commit()

    async def list_memberships(self, gremium_id: UUID) -> list[GremiumMembershipOut]:
        """List the memberships of a gremium with the name and e-mail of each member.

        Each row tells if it is active: the principal is active and the membership is
        valid now. This is the rule of the member count in the gremien list. A row
        without a principal row is not active.
        """
        now = datetime.now(UTC)
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
                .order_by(GremiumMembership.valid_from)
            )
        ).all()
        return [
            _membership_out(m, name, email, active=bool(active) and _valid_at(m, now))
            for m, name, email, active in rows
        ]
