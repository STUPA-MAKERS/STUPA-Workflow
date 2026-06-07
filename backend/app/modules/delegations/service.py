"""Delegation-Service (T-45, R1.5).

Anlegen/Auflisten/Widerrufen zeitbegrenzter Selbst-Delegationen. Eine Delegation ist
ein ``role_assignment`` mit gesetztem ``delegated_by`` (= ``sub`` des Delegierenden);
der RBAC-Resolver (T-10) zählt sie im Gültigkeitsfenster automatisch mit, ein Widerruf
(Hard-Delete der Zeile) wirkt daher **sofort**. Jede Delegation/jeder Widerruf wird
auditiert (T-23).

**RBAC serverseitig autoritativ.** Delegieren darf nur, wer die Rolle **selbst hält**
(``role.key`` in den aufgelösten Rollen des Aufrufers) — sonst 403. Stimmrecht-
Delegation (``delegateVoting``) ist nur bei aktivierter Settings-Option zulässig
(satzungsrechtlicher Vorbehalt Q5), sonst 422.

**Doppelte Stimmrechte.** :func:`has_active_voting_delegation` meldet dem Voting-
Modul (T-15), ob ein Aufrufer sein Stimmrecht (für den Scope der Abstimmung) bereits
abgegeben hat — der Delegierende darf dann nicht zusätzlich selbst abstimmen.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.models import Role, RoleAssignment
from app.modules.auth.principal import Principal
from app.modules.auth.rbac import _assignment_valid
from app.modules.delegations.schemas import DelegationCreate, DelegationOut
from app.settings import Settings
from app.shared.errors import ForbiddenError, NotFoundError, ValidationProblem

# Permission, die die volle (fremde) Delegations-Sicht/-Verwaltung freischaltet.
_ADMIN_PERM = "admin.roles"


def _to_utc(value: datetime | None) -> datetime | None:
    """Naive Eingaben defensiv als UTC interpretieren, aware → UTC normalisieren.

    Die Spalten sind ``timestamptz`` (Migration 0015): wir schreiben konsequent
    tz-aware UTC, damit der Resolver-Vergleich mit ``datetime.now(UTC)`` stimmt.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _scope_clause(scope: str | None):  # noqa: ANN202 — SQLAlchemy-ColumnElement
    """SQL-Filter für den Delegations-Scope einer Abstimmung.

    Globale Delegationen (``gremium_id IS NULL``) gelten immer; gremien-scoped nur,
    wenn der ``eligible_group``-Scharnierwert eine passende Gremium-UUID ist.
    """
    base = RoleAssignment.gremium_id.is_(None)
    if scope is None:
        return base
    try:
        gid = UUID(scope)
    except ValueError:
        return base
    return or_(base, RoleAssignment.gremium_id == gid)


async def has_active_voting_delegation(
    session: AsyncSession, delegator_sub: str, scope: str | None, now: datetime
) -> bool:
    """Hat ``delegator_sub`` sein Stimmrecht (für ``scope``) aktiv delegiert?

    Genutzt vom Voting-Modul zur Doppel-Stimmrechts-Sperre: wer sein Stimmrecht
    abgegeben hat, darf nicht zusätzlich selbst abstimmen.
    """
    stmt = (
        select(RoleAssignment.id)
        .where(
            RoleAssignment.delegated_by == delegator_sub,
            RoleAssignment.delegate_voting.is_(True),
            or_(RoleAssignment.valid_from.is_(None), RoleAssignment.valid_from <= now),
            or_(RoleAssignment.valid_until.is_(None), RoleAssignment.valid_until >= now),
            _scope_clause(scope),
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first() is not None


class DelegationService:
    """An eine ``AsyncSession`` + ``Settings`` gebundener Delegations-Service."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    # ------------------------------------------------------------------ create
    async def create(self, payload: DelegationCreate, actor: Principal) -> DelegationOut:
        """Delegation anlegen. 422 (Config/Fenster/Selbst), 403 (Rolle nicht gehalten),
        404 (Empfänger/Rolle unbekannt)."""
        now = datetime.now(UTC)
        if payload.delegate_voting and not self.settings.delegation_voting_enabled:
            raise ValidationProblem(
                "Voting-right delegation is disabled.",
                errors=[{"field": "delegateVoting", "msg": "disabled by configuration"}],
            )

        valid_from = _to_utc(payload.valid_from)
        valid_until = _to_utc(payload.valid_until)
        assert valid_until is not None  # payload-Pflichtfeld
        start = valid_from or now
        if valid_until <= start:
            raise ValidationProblem(
                "validUntil must be after validFrom.",
                errors=[{"field": "validUntil", "msg": "must be after start of window"}],
            )
        if valid_until <= now:
            raise ValidationProblem(
                "Delegation window already elapsed.",
                errors=[{"field": "validUntil", "msg": "must lie in the future"}],
            )

        delegate = (
            await self.session.execute(
                select(PrincipalRow).where(PrincipalRow.id == payload.principal_id)
            )
        ).scalar_one_or_none()
        if delegate is None:
            raise NotFoundError(f"principal {payload.principal_id} not found")
        if delegate.sub == actor.sub:
            raise ValidationProblem(
                "Cannot delegate to yourself.",
                errors=[{"field": "principalId", "msg": "must differ from delegator"}],
            )

        role = (
            await self.session.execute(
                select(Role).where(Role.id == payload.role_id)
            )
        ).scalar_one_or_none()
        if role is None:
            raise NotFoundError(f"role {payload.role_id} not found")
        if role.key not in actor.roles:
            raise ForbiddenError("Cannot delegate a role you do not hold.")

        row = RoleAssignment(
            principal_id=payload.principal_id,
            role_id=payload.role_id,
            gremium_id=payload.gremium_id,
            granted_by=actor.sub,
            delegated_by=actor.sub,
            valid_from=valid_from,
            valid_until=valid_until,
            delegate_voting=payload.delegate_voting,
        )
        self.session.add(row)
        await self.session.flush()
        await audit_record(
            self.session,
            actor=actor.sub,
            action=AuditAction.DELEGATION_GRANT,
            target_type="role_assignment",
            target_id=str(row.id),
            data={
                "principalId": str(payload.principal_id),
                "roleId": str(payload.role_id),
                "gremiumId": str(payload.gremium_id) if payload.gremium_id else None,
                "delegateVoting": payload.delegate_voting,
                "validFrom": start.isoformat(),
                "validUntil": valid_until.isoformat(),
            },
        )
        await self.session.commit()
        return _out(row, now)

    # -------------------------------------------------------------------- list
    async def list(self, actor: Principal) -> list[DelegationOut]:
        """Eigene ausgehende Delegationen; Admins (``admin.roles``) sehen alle."""
        now = datetime.now(UTC)
        stmt = select(RoleAssignment).where(RoleAssignment.delegated_by.is_not(None))
        if not actor.has(_ADMIN_PERM):
            stmt = stmt.where(RoleAssignment.delegated_by == actor.sub)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [_out(r, now) for r in rows]

    # ------------------------------------------------------------------ revoke
    async def revoke(self, delegation_id: UUID, actor: Principal) -> None:
        """Delegation widerrufen (Hard-Delete → sofort wirksam). 404/403."""
        row = (
            await self.session.execute(
                select(RoleAssignment).where(RoleAssignment.id == delegation_id)
            )
        ).scalar_one_or_none()
        if row is None or row.delegated_by is None:
            raise NotFoundError(f"delegation {delegation_id} not found")
        if row.delegated_by != actor.sub and not actor.has(_ADMIN_PERM):
            raise ForbiddenError("Only the delegator (or an admin) may revoke.")
        await self.session.delete(row)
        await audit_record(
            self.session,
            actor=actor.sub,
            action=AuditAction.DELEGATION_REVOKE,
            target_type="role_assignment",
            target_id=str(delegation_id),
            data={"delegatedBy": row.delegated_by},
        )
        await self.session.commit()


def _out(row: RoleAssignment, now: datetime) -> DelegationOut:
    return DelegationOut(
        id=row.id,
        principal_id=row.principal_id,
        role_id=row.role_id,
        gremium_id=row.gremium_id,
        delegated_by=row.delegated_by,
        granted_by=row.granted_by,
        valid_from=row.valid_from,
        valid_until=row.valid_until,
        delegate_voting=row.delegate_voting,
        active=_assignment_valid(row.valid_from, row.valid_until, now),
    )
