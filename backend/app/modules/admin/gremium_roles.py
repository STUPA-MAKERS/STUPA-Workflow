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
from sqlalchemy.exc import IntegrityError
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
from app.modules.auth.models import Principal as PrincipalRow
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem

# Granulare, **pro Gremium-Rolle** konfigurierbare Berechtigungen (Sitzungs-Domäne).
# Getrennt vom globalen 16-Permission-Satz: diese gelten nur innerhalb des Gremiums
# und werden über die aktive ``gremium_membership`` aufgelöst.
#   session.manage  — Sitzungen anlegen/bearbeiten, Protokollant zuweisen, Status setzen
#   vote.manage     — Abstimmungen (Beschlussfragen) öffnen/schließen
#   vote.cast       — in Sitzungs-Abstimmungen mitstimmen
#   protocol.write  — als Protokollant zuweisbar / Protokoll schreiben
GREMIUM_PERMISSIONS: tuple[str, ...] = (
    "session.manage",
    "vote.manage",
    "vote.cast",
    "protocol.write",
)
_ALL_PERMS: list[str] = list(GREMIUM_PERMISSIONS)

# Pflicht-Gremium-Rollen: existieren in JEDEM Gremium und sind nicht löschbar.
# ``vorstand`` + ``manager`` dürfen per Default Sitzungen verwalten (session.manage)
# und Abstimmungen führen; ``member`` darf per Default nur mitstimmen (vote.cast).
# Der je Sitzung zugewiesene **Protokollant** schreibt das Protokoll (zusätzlich zu
# einer ``protocol.write``-Rolle). Anlegen beim Gremium-Erstellen + idempotenter
# Backfill beim Auflisten (Bestands-Gremien via Migration 0040).
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
    """SQLAlchemy-Klausel: ``gremium_membership`` ist zum Zeitpunkt ``now`` aktiv."""
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
    """Aktive (Gremium, Rolle)-Paare eines Principals (zeit-validiert)."""
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
    """Gremium-IDs, in denen die aktive Rolle des Principals ``perm`` gewährt."""
    return {
        gid
        for gid, role in await active_gremium_roles(session, sub, now)
        if perm in (role.permissions or [])
    }


async def gremium_member_ids(
    session: AsyncSession, sub: str, now: datetime | None = None
) -> set[UUID]:
    """Gremium-IDs, in denen der Principal aktuell (beliebige Rolle) Mitglied ist."""
    return {gid for gid, _ in await active_gremium_roles(session, sub, now)}


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


def _sanitize_perms(perms: list[str] | None) -> list[str]:
    """Nur bekannte Gremium-Permissions, dedupliziert, in Katalog-Reihenfolge."""
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
    async def ensure_forced_roles(self, gremium_id: UUID) -> bool:
        """Pflichtrollen (Vorstand/Schriftführung) idempotent für ein Gremium anlegen.

        Gibt ``True`` zurück, wenn etwas angelegt wurde. Committet **nicht** selbst —
        der Aufrufer steuert die Transaktion (so nutzbar beim Gremium-Anlegen wie
        beim Auflisten)."""
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
        # Bestands-Gremien lazy nachrüsten, damit die Pflichtrollen immer da sind.
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
            # Granulare Berechtigungen sind auch auf Pflichtrollen editierbar
            # (nur der Schlüssel/das Löschen ist bei Pflichtrollen gesperrt).
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
        role = await self.session.get(GremiumRole, payload.gremium_role_id)
        if role is None:
            raise NotFoundError(f"gremium role {payload.gremium_role_id} not found")
        if role.gremium_id != gremium_id:
            raise ConflictError("gremium role does not belong to this gremium")
        # Unbekannte principal_id sauber als 404 — sonst platzt erst der FK beim
        # Commit (IntegrityError → 500).
        if await self.session.get(PrincipalRow, payload.principal_id) is None:
            raise NotFoundError(f"principal {payload.principal_id} not found")
        new_from = _parse_dt(payload.valid_from)
        new_until = _parse_dt(payload.valid_until)
        if new_from is not None and new_until is not None and new_from >= new_until:
            raise ValidationProblem(
                "validFrom must be before validUntil.",
                errors=[{"field": "validUntil", "msg": "must be after validFrom"}],
            )
        # Overlap-Invariante: kein zeitlich überlappender Eintrag desselben Principals
        # in DIESEM Gremium (genau eine aktive Rolle je Zeitpunkt). Diese Python-Prüfung
        # ist nur ein Fast-Path mit klarer Fehlermeldung; verbindlich durchgesetzt wird
        # die Invariante über die EXCLUDE-Constraint ``ex_gremium_membership_no_overlap``
        # (schließt die TOCTOU-Lücke bei parallelen Inserts, AUD-029).
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
        # Die EXCLUDE-Constraint wird beim INSERT (flush) geprüft, nicht erst beim
        # Commit — der konkurrierende Race feuert also bereits hier. flush + Audit +
        # Commit daher gemeinsam absichern und den IntegrityError in einen 409
        # übersetzen (statt 500); der Client kann erneut versuchen.
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
