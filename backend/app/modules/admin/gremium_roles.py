"""Gremium-Rollen + zeitbegrenzte Mitgliedschaften (#42).

Getrennt von den globalen Rollen: ein eigener Rollen-Katalog (``gremium_role``) und
Mitgliedschaften mit Amtszeit (``gremium_membership``). Kerninvariante: pro
(Principal, Gremium) ist zu jedem Zeitpunkt **genau eine** Rolle aktiv — überlappende
Amtszeiten sind verboten, nicht-überlappende (aufeinanderfolgende) erlaubt.

Die Overlap-Prüfung ist eine reine Funktion (isoliert testbar); der Service kapselt
DB-Zugriff + Audit.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import GremiumMembership, GremiumRole
from app.modules.admin.schemas import (
    GremiumMembershipCreate,
    GremiumMembershipOut,
    GremiumRoleCreate,
    GremiumRoleOut,
    GremiumRoleUpdate,
)
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import AuditService
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem


def intervals_overlap(
    a_from: datetime | None,
    a_until: datetime | None,
    b_from: datetime | None,
    b_until: datetime | None,
) -> bool:
    """``True`` wenn sich die halboffenen Intervalle ``[from, until)`` überlappen.

    ``None`` = unbegrenzt (``from=None`` ⇒ −∞, ``until=None`` ⇒ +∞). Zwei Intervalle
    überlappen, wenn ``a_from < b_until`` **und** ``b_from < a_until`` (mit den
    Unendlich-Sonderfällen). Aneinandergrenzende Intervalle (``a_until == b_from``)
    überlappen **nicht** (halboffen)."""
    left_ok = a_from is None or b_until is None or a_from < b_until
    right_ok = b_from is None or a_until is None or b_from < a_until
    return left_ok and right_ok


def _parse_dt(value: str | None) -> datetime | None:
    if value is None or value == "":
        return None
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _role_out(row: GremiumRole) -> GremiumRoleOut:
    return GremiumRoleOut(id=row.id, key=row.key, name=row.name_i18n or {})


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
    """CRUD für Gremium-Rollen + Mitgliedschaften (mit Overlap-Invariante)."""

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

    # ----------------------------------------------------------- role catalogue
    async def list_roles(self) -> list[GremiumRoleOut]:
        rows = (
            await self.session.scalars(select(GremiumRole).order_by(GremiumRole.key))
        ).all()
        return [_role_out(r) for r in rows]

    async def create_role(self, payload: GremiumRoleCreate, actor: str) -> GremiumRoleOut:
        existing = (
            await self.session.scalars(
                select(GremiumRole).where(GremiumRole.key == payload.key)
            )
        ).first()
        if existing is not None:
            raise ConflictError(f"gremium role {payload.key!r} already exists")
        row = GremiumRole(key=payload.key, name_i18n=payload.name)
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
        await self._audit(actor, "gremium_role", row.id)
        await self.session.commit()
        return _role_out(row)

    async def delete_role(self, role_id: UUID, actor: str) -> None:
        row = await self.session.get(GremiumRole, role_id)
        if row is None:
            raise NotFoundError(f"gremium role {role_id} not found")
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

    # --------------------------------------------------------------- memberships
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
        if await self.session.get(GremiumRole, payload.gremium_role_id) is None:
            raise NotFoundError(f"gremium role {payload.gremium_role_id} not found")
        new_from = _parse_dt(payload.valid_from)
        new_until = _parse_dt(payload.valid_until)
        if new_from is not None and new_until is not None and new_from >= new_until:
            raise ValidationProblem(
                "validFrom must be before validUntil.",
                errors=[{"field": "validUntil", "msg": "must be after validFrom"}],
            )
        # Overlap-Invariante: kein zeitlich überlappender Eintrag desselben Principals
        # in DIESEM Gremium (genau eine aktive Rolle je Zeitpunkt).
        existing = (
            await self.session.scalars(
                select(GremiumMembership).where(
                    GremiumMembership.gremium_id == gremium_id,
                    GremiumMembership.principal_id == payload.principal_id,
                )
            )
        ).all()
        for m in existing:
            if intervals_overlap(new_from, new_until, m.valid_from, m.valid_until):
                raise ConflictError(
                    "overlapping membership for this member in this gremium",
                    code="conflict",
                )
        row = GremiumMembership(
            principal_id=payload.principal_id,
            gremium_id=gremium_id,
            gremium_role_id=payload.gremium_role_id,
            valid_from=new_from,
            valid_until=new_until,
        )
        self.session.add(row)
        await self.session.flush()
        await self._audit(actor, "gremium_membership", row.id)
        await self.session.commit()
        return _membership_out(row)

    async def delete_membership(self, membership_id: UUID, actor: str) -> None:
        row = await self.session.get(GremiumMembership, membership_id)
        if row is None:
            raise NotFoundError(f"gremium membership {membership_id} not found")
        await self.session.delete(row)
        await self._audit(actor, "gremium_membership", membership_id)
        await self.session.commit()
