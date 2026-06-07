"""Delegation-Service (T-45, R1.5) — Sicherheitskern.

Anlegen/Auflisten/Widerrufen zeitbegrenzter Selbst-Delegationen. Eine Delegation ist
ein ``role_assignment`` mit gesetztem ``delegated_by`` (= ``sub`` des Delegierenden);
der RBAC-Resolver (T-10) zählt sie im Gültigkeitsfenster automatisch mit, ein Widerruf
(Hard-Delete der Zeile) wirkt daher **sofort**. Jede Delegation/jeder Widerruf wird
auditiert (T-23).

**Invariante: »nie mehr delegieren als man selbst direkt hält«** (serverseitig
erzwungen, security-review #95):

* **Keine Re-Delegation/Ketten:** delegierbar ist nur eine **direkt** gehaltene Rolle
  (``role_assignment`` mit ``delegated_by IS NULL``) — nicht eine selbst nur per
  Delegation erhaltene. Damit gibt es keine A→B→C-Kette (sonst 403).
* **Zeitliche Klammer:** ``valid_until`` der Delegation wird auf das Ende der eigenen
  zugrundeliegenden Berechtigung geklammert (``min``); ist die eigene unbefristet,
  gilt der Wunsch. Eine Delegation kann nie länger laufen als das eigene Recht.
* **Gremium-Scope:** der angefragte ``gremium_id``-Scope muss durch ein direkt
  gehaltenes Assignment gedeckt sein (global deckt alles), sonst 403.

**Stimmrecht (exklusiv, Transfer ≠ Duplikat).** :func:`voting_delegation_check`
liefert dem Voting-Modul (T-15) ein zwei-seitiges Verdikt: wer sein Stimmrecht
abgegeben hat **und** wer nur über eine *nicht*-stimmberechtigende Delegation in die
``eligible_group`` käme, darf nicht abstimmen (fail-closed); wer eine Stimm-Delegation
ausübt, wird auditiert (``DELEGATION_USE``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.models import GroupMapping, Role, RoleAssignment
from app.modules.auth.models import Principal as PrincipalRow
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


def _window_active(now: datetime):  # noqa: ANN202 — SQLAlchemy-ColumnElement
    """SQL: Assignment-Fenster zum Zeitpunkt ``now`` aktiv."""
    return and_(
        or_(RoleAssignment.valid_from.is_(None), RoleAssignment.valid_from <= now),
        or_(RoleAssignment.valid_until.is_(None), RoleAssignment.valid_until >= now),
    )


async def _independently_eligible(
    session: AsyncSession, sub: str, scope: str | None, now: datetime
) -> bool:
    """Ist ``sub`` **unabhängig von Delegationen** in der ``eligible_group``?

    Quellen (wie der Resolver, aber ohne ``delegated_by``-Zeilen): OIDC-Gruppe direkt,
    ein **direkt** gehaltenes Assignment im Gremium ``scope``, oder ein group-mapping
    (eigene OIDC-Gruppe → Gremium ``scope``). Trennt einen legitimen Eigen-Wähler von
    einem reinen Delegations-Empfänger (security-review #95, false-positive-Fix).
    """
    row = (
        await session.execute(
            select(PrincipalRow.id, PrincipalRow.oidc_groups).where(PrincipalRow.sub == sub)
        )
    ).first()
    if row is None:
        return False
    pid, raw_groups = row
    oidc = {str(g) for g in (raw_groups or [])}
    if scope is not None and scope in oidc:
        return True
    if scope is None:
        return False
    try:
        gid = UUID(scope)
    except ValueError:
        return False
    direct = (
        await session.execute(
            select(RoleAssignment.id)
            .where(
                RoleAssignment.principal_id == pid,
                RoleAssignment.delegated_by.is_(None),
                RoleAssignment.gremium_id == gid,
                _window_active(now),
            )
            .limit(1)
        )
    ).first()
    if direct is not None:
        return True
    if not oidc:
        return False
    mapped = (
        await session.execute(
            select(GroupMapping.id)
            .where(GroupMapping.gremium_id == gid, GroupMapping.oidc_group.in_(oidc))
            .limit(1)
        )
    ).first()
    return mapped is not None


async def voting_delegation_check(
    session: AsyncSession, sub: str, scope: str | None, now: datetime
) -> tuple[bool, bool]:
    """Zwei-seitiges Stimmrecht-Verdikt für ``sub`` im ``scope`` → ``(blocked, exercised)``.

    Erste Query (Sub-Select für die principal-id) klassifiziert die aktiven, scope-
    passenden Delegations-Zeilen; ``blocked`` hat Vorrang (fail-closed):

    * ``delegated_by == sub`` & ``delegate_voting`` → der Aufrufer hat sein Stimmrecht
      abgegeben → **blocked** (kein Doppel: nur der Empfänger stimmt).
    * Empfänger-Zeile & ``delegate_voting`` → der Aufrufer **übt** ein delegiertes
      Stimmrecht aus → ``exercised`` (Nutzungs-Audit).
    * Empfänger-Zeile & **nicht** ``delegate_voting`` → nur dann **blocked**, wenn der
      Aufrufer **nicht eigenständig** stimmberechtigt ist (sonst stimmt er auf sein
      eigenes direktes Recht; die nicht-Stimm-Delegation verleiht kein Stimmrecht).
      Diese Eigenständigkeits-Probe läuft nur in diesem schmalen Fall — der Normal-
      Wähler-Pfad bleibt bei genau einer Query.
    """
    pid_subq = select(PrincipalRow.id).where(PrincipalRow.sub == sub).scalar_subquery()
    rows = (
        await session.execute(
            select(RoleAssignment.delegated_by, RoleAssignment.delegate_voting).where(
                RoleAssignment.delegated_by.is_not(None),
                or_(
                    RoleAssignment.delegated_by == sub,
                    RoleAssignment.principal_id == pid_subq,
                ),
                _window_active(now),
                _scope_clause(scope),
            )
        )
    ).all()

    gave_voting_away = False
    recipient_voting = False
    recipient_nonvoting = False
    for delegated_by, delegate_voting in rows:
        if delegated_by == sub:
            if delegate_voting:
                gave_voting_away = True
        elif delegate_voting:
            recipient_voting = True
        else:
            recipient_nonvoting = True

    if gave_voting_away:
        return True, False
    if recipient_voting:
        return False, True
    if recipient_nonvoting and not await _independently_eligible(session, sub, scope, now):
        return True, False
    return False, False


class DelegationService:
    """An eine ``AsyncSession`` + ``Settings`` gebundener Delegations-Service."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def _direct_holdings(
        self, principal_id: UUID, role_id: UUID, now: datetime
    ) -> list[tuple[UUID | None, datetime | None]]:
        """Aktive, **direkt** (nicht delegiert) gehaltene Assignments der Rolle.

        Liefert ``(gremium_id, valid_until)`` je aktiver Zeile mit ``delegated_by IS
        NULL`` — Basis für »nie mehr als man hält« (Scope + Zeitklammer).
        """
        rows = (
            await self.session.execute(
                select(
                    RoleAssignment.gremium_id,
                    RoleAssignment.valid_from,
                    RoleAssignment.valid_until,
                ).where(
                    RoleAssignment.principal_id == principal_id,
                    RoleAssignment.role_id == role_id,
                    RoleAssignment.delegated_by.is_(None),
                )
            )
        ).all()
        return [
            (gremium_id, valid_until)
            for gremium_id, valid_from, valid_until in rows
            if _assignment_valid(valid_from, valid_until, now)
        ]

    # ------------------------------------------------------------------ create
    async def create(self, payload: DelegationCreate, actor: Principal) -> DelegationOut:
        """Delegation anlegen. 422 (Config/Fenster/Selbst), 403 (Recht/Scope nicht
        direkt gehalten), 404 (Empfänger/Rolle unbekannt)."""
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
            await self.session.execute(select(Role).where(Role.id == payload.role_id))
        ).scalar_one_or_none()
        if role is None:
            raise NotFoundError(f"role {payload.role_id} not found")

        # »Nie mehr als man hält«: nur direkt (nicht-delegiert) gehaltene Rechte sind
        # delegierbar → keine Re-Delegation/Ketten.
        me = (
            await self.session.execute(
                select(PrincipalRow).where(PrincipalRow.sub == actor.sub)
            )
        ).scalar_one_or_none()
        if me is None:
            raise ForbiddenError("Delegator principal not found.")
        holdings = await self._direct_holdings(me.id, payload.role_id, now)
        if not holdings:
            raise ForbiddenError(
                "You may only delegate a role you hold directly (not via delegation)."
            )

        # Scope-Deckung: globale Holdings (gremium_id is None) decken jeden Scope;
        # gremien-scoped Holdings nur den eigenen Scope.
        covering = [
            (gremium_id, until)
            for gremium_id, until in holdings
            if gremium_id is None or gremium_id == payload.gremium_id
        ]
        if not covering:
            raise ForbiddenError("Requested gremium scope exceeds your own holdings.")

        # Zeitklammer: nie länger als das eigene (deckende) Recht. None = unbefristet.
        if any(until is None for _, until in covering):
            allowed_until: datetime | None = None
        else:
            allowed_until = max(until for _, until in covering if until is not None)
        effective_until = (
            valid_until if allowed_until is None else min(valid_until, allowed_until)
        )
        if effective_until <= now:
            raise ValidationProblem(
                "Delegation window already elapsed.",
                errors=[{"field": "validUntil", "msg": "must lie in the future"}],
            )

        row = RoleAssignment(
            principal_id=payload.principal_id,
            role_id=payload.role_id,
            gremium_id=payload.gremium_id,
            granted_by=actor.sub,
            delegated_by=actor.sub,
            valid_from=valid_from,
            valid_until=effective_until,
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
                "validUntil": effective_until.isoformat(),
                "clamped": allowed_until is not None and effective_until < valid_until,
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
