"""Gremium roles plus time-bound memberships.

This module stays separate from the global roles. It holds an own role catalog
(``gremium_role``) and memberships with terms of office (``gremium_membership``).

Core invariant: for each (principal, gremium) pair exactly one role is active at
any point in time. Overlapping terms are forbidden. Consecutive terms are
allowed. The overlap check is a pure function. The service wraps the database
access and the audit entry.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import GremiumMembership, GremiumRole
from app.modules.admin.schemas import (
    GremiumMembershipCreate,
    GremiumMembershipOut,
    GremiumMembershipUpdate,
    GremiumRoleCreate,
    GremiumRoleOut,
    GremiumRoleUpdate,
)
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import AuditService
from app.modules.auth.models import Principal as PrincipalRow
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem

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


def intervals_overlap(
    a_from: datetime | None,
    a_until: datetime | None,
    b_from: datetime | None,
    b_until: datetime | None,
) -> bool:
    """Return True if the half-open intervals ``[from, until)`` overlap.

    ``None`` means unbounded. Adjacent intervals (``a_until == b_from``) do not
    overlap, because the intervals are half-open.
    """
    left_ok = a_from is None or b_until is None or a_from < b_until
    right_ok = b_from is None or a_until is None or b_from < a_until
    return left_ok and right_ok


def _parse_dt(value: str | None) -> datetime | None:
    """Parse a term bound into a tz-aware UTC ``datetime``. Empty means open.

    A naive input counts as UTC.

    Raises:
        ValidationProblem: The value is no ISO-8601 datetime (422).
    """
    if value is None or value == "":
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValidationProblem(
            "Invalid datetime.",
            errors=[{"field": "validFrom/validUntil", "msg": str(exc)}],
        ) from exc
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


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
        valid_from=_iso(row.valid_from),
        valid_until=_iso(row.valid_until),
    )


class GremiumRoleService:
    """CRUD for gremium roles plus memberships (with the overlap invariant)."""

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

    async def create_membership(
        self, gremium_id: UUID, payload: GremiumMembershipCreate, actor: str
    ) -> GremiumMembershipOut:
        role = await self.session.get(GremiumRole, payload.gremium_role_id)
        if role is None:
            raise NotFoundError(f"gremium role {payload.gremium_role_id} not found")
        if role.gremium_id != gremium_id:
            raise ConflictError("gremium role does not belong to this gremium")
        # Turn an unknown principal_id into a clean 404. Without this check the
        # database rejects the row at commit only. The IntegrityError then gives
        # a 500.
        if await self.session.get(PrincipalRow, payload.principal_id) is None:
            raise NotFoundError(f"principal {payload.principal_id} not found")
        new_from = _parse_dt(payload.valid_from)
        new_until = _parse_dt(payload.valid_until)
        self._assert_ordered(new_from, new_until)
        # Overlap invariant: no time-overlapping entry for the same principal in
        # THIS gremium.
        await self._assert_no_overlap(
            gremium_id, payload.principal_id, new_from, new_until
        )
        row = GremiumMembership(
            principal_id=payload.principal_id,
            gremium_id=gremium_id,
            gremium_role_id=payload.gremium_role_id,
            valid_from=new_from,
            valid_until=new_until,
        )
        self.session.add(row)
        # The EXCLUDE constraint fires at INSERT (flush), not at commit. A
        # concurrent race therefore surfaces here. Guard the flush, the audit and
        # the commit together and translate the IntegrityError into a 409 instead
        # of a 500.
        try:
            await self.session.flush()
            await self._audit(actor, "gremium_membership", row.id)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(
                "overlapping membership for this member in this gremium",
                code="conflict",
            ) from exc
        return _membership_out(row)

    async def _assert_no_overlap(
        self,
        gremium_id: UUID,
        principal_id: UUID,
        new_from: datetime | None,
        new_until: datetime | None,
        *,
        exclude_id: UUID | None = None,
    ) -> None:
        """Check the overlap invariant for one (principal, gremium) pair.

        Only a fast path with a clear message; ``ex_gremium_membership_no_overlap``
        stays the authoritative guard. ``exclude_id`` leaves the row under edit
        out, so a patch never conflicts with itself.

        Raises:
            ConflictError: Another term of this member overlaps (409).
        """
        existing = (
            await self.session.scalars(
                select(GremiumMembership).where(
                    GremiumMembership.gremium_id == gremium_id,
                    GremiumMembership.principal_id == principal_id,
                )
            )
        ).all()
        for m in existing:
            if m.id == exclude_id:
                continue
            if intervals_overlap(new_from, new_until, m.valid_from, m.valid_until):
                raise ConflictError(
                    "overlapping membership for this member in this gremium",
                    code="conflict",
                )

    @staticmethod
    def _assert_ordered(new_from: datetime | None, new_until: datetime | None) -> None:
        """Reject a term that ends before it starts.

        Raises:
            ValidationProblem: ``validFrom`` is not before ``validUntil`` (422).
        """
        if new_from is not None and new_until is not None and new_from >= new_until:
            raise ValidationProblem(
                "validFrom must be before validUntil.",
                errors=[{"field": "validUntil", "msg": "must be after validFrom"}],
            )

    async def update_membership(
        self, membership_id: UUID, payload: GremiumMembershipUpdate, actor: str
    ) -> GremiumMembershipOut:
        """Change the role or the term of office of a membership.

        The member and the Gremium stay immutable; a new role must belong to the
        same Gremium.

        Raises:
            NotFoundError: The membership or the new role does not exist (404).
            ConflictError: The role belongs to another Gremium, or the new term
                overlaps another term of this member (409).
            ValidationProblem: ``validFrom`` is not before ``validUntil`` (422).
        """
        row = await self.session.get(GremiumMembership, membership_id)
        if row is None:
            raise NotFoundError(f"gremium membership {membership_id} not found")
        provided = payload.model_fields_set
        if payload.gremium_role_id is not None:
            role = await self.session.get(GremiumRole, payload.gremium_role_id)
            if role is None:
                raise NotFoundError(f"gremium role {payload.gremium_role_id} not found")
            if role.gremium_id != row.gremium_id:
                raise ConflictError("gremium role does not belong to this gremium")
        new_from = _parse_dt(payload.valid_from) if "valid_from" in provided else row.valid_from
        new_until = (
            _parse_dt(payload.valid_until) if "valid_until" in provided else row.valid_until
        )
        self._assert_ordered(new_from, new_until)
        await self._assert_no_overlap(
            row.gremium_id, row.principal_id, new_from, new_until, exclude_id=row.id
        )
        if payload.gremium_role_id is not None:
            row.gremium_role_id = payload.gremium_role_id
        row.valid_from = new_from
        row.valid_until = new_until
        # The EXCLUDE constraint fires on the UPDATE flush, so a concurrent write
        # surfaces here and must become a 409, not a 500.
        try:
            await self.session.flush()
            await self._audit(actor, "gremium_membership", row.id)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(
                "overlapping membership for this member in this gremium",
                code="conflict",
            ) from exc
        return _membership_out(row)

    async def delete_membership(self, membership_id: UUID, actor: str) -> None:
        row = await self.session.get(GremiumMembership, membership_id)
        if row is None:
            raise NotFoundError(f"gremium membership {membership_id} not found")
        await self.session.delete(row)
        await self._audit(actor, "gremium_membership", membership_id)
        await self.session.commit()
