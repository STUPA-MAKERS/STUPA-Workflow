"""Empfänger-Resolver: Regel-`recipients` → konkrete Mail-Adressen (DB).

Empfängertypen (data-model §5.4 + #28-Flow-Actions):

* ``{"kind":"group","ref":"stupa"}``    — Principals mit OIDC-Gruppe `ref`.
* ``{"kind":"role","ref":"manager"}``   — Principals mit aktiver Rollen-Zuweisung `ref`.
* ``{"kind":"gremium","ref":"<id>"}``   — aktuelle Mitglieder des Gremiums `ref`.
* ``{"kind":"applicant"}``              — Antragsteller-Mail des auslösenden Antrags.
* ``{"kind":"email","ref":"a@b.c"}``    — feste, frei eingetragene Adresse.

Ergebnis ist dedupliziert + sortiert; leere Adressen fallen raus.

Zusätzlich: :func:`actionable_principal_emails` — Adressen aller, die am
aktuellen State eines Antrags handeln können (Task-Semantik #64; von
Kommentar-/Task-Mails #4-1/#4-3 genutzt). Seit #task-recipients spiegelt das die
Task-Listen-Semantik: nur wer mindestens einen ``requires_action``-Übergang
tatsächlich feuern kann (Guard erfüllt), bekommt Mail — Admins nicht mehr
bedingungslos.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import GremiumMembership
from app.modules.applications.models import Applicant, Application
from app.modules.auth.models import (
    GroupMapping,
    Principal,
    Role,
    RoleAssignment,
    RolePermission,
)
from app.modules.deadlines.service import flow_deadline_passed
from app.modules.flow.context import build_base_context, with_actor
from app.modules.flow.models import State, Transition
from app.shared.guards import GuardContext, GuardError, eval_guard

# Admin-Rolle = Alle-Rechte-Bypass (#15), zentraler RBAC-Chokepoint in
# ``Principal.has`` (auth/principal.py: ``"admin" in self.roles``). HIER gespiegelt,
# weil die Empfänger-Auflösung mengenbasiert in SQL läuft (nicht über ``has`` pro
# Principal) — der Schlüssel MUSS mit ``Principal.has`` übereinstimmen, daher
# als eine Konstante geführt statt als String-Literal in beiden Resolvern.
ADMIN_ROLE_KEY = "admin"


def _active_assignment_window(now: datetime) -> list[ColumnElement[bool]]:
    """Gültigkeitsfenster einer ``RoleAssignment`` zum Zeitpunkt ``now``."""
    return [
        or_(RoleAssignment.valid_from.is_(None), RoleAssignment.valid_from <= now),
        or_(RoleAssignment.valid_until.is_(None), RoleAssignment.valid_until > now),
    ]


def _permission_conds(
    perm: str, now: datetime, gremium_id: uuid.UUID | None
) -> list[ColumnElement[bool]]:
    """Shared WHERE clauses of the permission-holder queries.

    Single place that mirrors ``Principal.has`` (admin bypass + RolePermission
    join) so every resolver builds the identical candidate set. ``gremium_id``
    gates on globally valid OR gremium-scoped assignments.
    """
    conds: list[ColumnElement[bool]] = [
        Principal.email.is_not(None),
        Principal.active.is_(True),
        *_active_assignment_window(now),
        or_(RolePermission.permission == perm, Role.key == ADMIN_ROLE_KEY),
    ]
    if gremium_id is not None:
        conds.append(
            or_(
                RoleAssignment.gremium_id.is_(None),
                RoleAssignment.gremium_id == gremium_id,
            )
        )
    return conds


def principals_with_permission_stmt(
    perm: str,
    now: datetime,
    *,
    gremium_id: uuid.UUID | None = None,
) -> Select[tuple[str | None]]:
    """E-Mails aktiver Principals, die ``perm`` über eine gültige Rollenzuweisung
    halten — inkl. Admin-Bypass (:data:`ADMIN_ROLE_KEY` zählt immer).

    Baut auf :func:`_permission_conds` auf, damit beide Resolver konsistent mit
    ``Principal.has`` bleiben.
    """
    return (
        select(Principal.email)
        .join(RoleAssignment, RoleAssignment.principal_id == Principal.id)
        .join(Role, Role.id == RoleAssignment.role_id)
        .outerjoin(RolePermission, RolePermission.role_id == Role.id)
        .where(*_permission_conds(perm, now, gremium_id))
        .distinct()
    )


def principal_rows_with_permission_stmt(
    perm: str,
    now: datetime,
    *,
    gremium_id: uuid.UUID | None = None,
) -> Select[tuple[uuid.UUID, str, str | None, list | None]]:
    """Identity rows of the permission holders (same conds as the email stmt).

    Projects ``(id, sub, email, oidc_groups)`` so the caller can resolve the
    per-principal roles/committees needed for guard evaluation. The admin arm
    stays in the seed (mirrors ``Principal.has``) — admins are only *candidates*
    here; a guard still has to fire for them to actually receive mail.
    """
    return (
        select(Principal.id, Principal.sub, Principal.email, Principal.oidc_groups)
        .join(RoleAssignment, RoleAssignment.principal_id == Principal.id)
        .join(Role, Role.id == RoleAssignment.role_id)
        .outerjoin(RolePermission, RolePermission.role_id == Role.id)
        .where(*_permission_conds(perm, now, gremium_id))
        .distinct()
    )


@dataclass(frozen=True, slots=True)
class ActionableCandidate:
    """Permission-holding principal plus the actor facts guards evaluate on."""

    principal_id: uuid.UUID
    sub: str
    email: str
    roles: frozenset[str]
    committees: frozenset[str]


async def _candidates_with_transition_permission(
    session: AsyncSession,
    now: datetime,
    *,
    gremium_id: uuid.UUID | None,
) -> list[ActionableCandidate]:
    """Candidates who may fire transitions at all, with resolved actor facts.

    Roles follow the RBAC resolution (``resolve_principal``): active role
    assignments PLUS GroupMapping-derived roles from the principal's OIDC groups
    (assignment gremium scopes count as group keys). Committees are the active
    GremiumMembership gremium ids. Uses a constant number of batch queries — no
    per-candidate round trips.
    """
    rows = (
        await session.execute(
            principal_rows_with_permission_stmt(
                "application.transition", now, gremium_id=gremium_id
            )
        )
    ).all()
    seeds = [
        (pid, sub, email, {str(g) for g in (groups or [])})
        for pid, sub, email, groups in rows
        if email
    ]
    if not seeds:
        return []
    ids = {pid for pid, _sub, _email, _groups in seeds}

    roles_by_pid: dict[uuid.UUID, set[str]] = {pid: set() for pid in ids}
    groups_by_pid: dict[uuid.UUID, set[str]] = {
        pid: set(groups) for pid, _sub, _email, groups in seeds
    }
    assignment_rows = (
        await session.execute(
            select(RoleAssignment.principal_id, Role.key, RoleAssignment.gremium_id)
            .join(Role, Role.id == RoleAssignment.role_id)
            .where(
                RoleAssignment.principal_id.in_(ids),
                *_active_assignment_window(now),
            )
        )
    ).all()
    for pid, role_key, assignment_gremium in assignment_rows:
        roles_by_pid[pid].add(role_key)
        if assignment_gremium is not None:
            # Gremium scope counts as a group key — parity with resolve_principal.
            groups_by_pid[pid].add(str(assignment_gremium))

    all_groups: set[str] = set().union(*groups_by_pid.values())
    if all_groups:
        mapping_rows = (
            await session.execute(
                select(GroupMapping.oidc_group, Role.key)
                .join(Role, Role.id == GroupMapping.role_id)
                .where(GroupMapping.oidc_group.in_(all_groups))
            )
        ).all()
        mapped_roles: dict[str, set[str]] = {}
        for group, role_key in mapping_rows:
            mapped_roles.setdefault(group, set()).add(role_key)
        for pid, groups in groups_by_pid.items():
            for group in groups:
                roles_by_pid[pid].update(mapped_roles.get(group, ()))

    committees_by_pid: dict[uuid.UUID, set[str]] = {pid: set() for pid in ids}
    membership_rows = (
        await session.execute(
            select(GremiumMembership.principal_id, GremiumMembership.gremium_id).where(
                GremiumMembership.principal_id.in_(ids),
                or_(
                    GremiumMembership.valid_from.is_(None),
                    GremiumMembership.valid_from <= now,
                ),
                or_(
                    GremiumMembership.valid_until.is_(None),
                    GremiumMembership.valid_until > now,
                ),
            )
        )
    ).all()
    for pid, membership_gremium in membership_rows:
        committees_by_pid[pid].add(str(membership_gremium))

    return [
        ActionableCandidate(
            principal_id=pid,
            sub=sub,
            email=email,
            roles=frozenset(roles_by_pid[pid]),
            committees=frozenset(committees_by_pid[pid]),
        )
        for pid, sub, email, _groups in seeds
    ]


def firable_candidates(
    candidates: Sequence[ActionableCandidate],
    transitions: Sequence[Transition],
    base_ctx: GuardContext,
    *,
    created_by: str | None,
) -> list[ActionableCandidate]:
    """Keep the candidates for whom at least one transition guard passes (pure).

    Mirrors ``list_tasks``/``available_transitions``: a candidate counts iff any
    of the given transitions fires under their actor context. A ``GuardError``
    on a single transition counts as not firable (fail-closed) instead of
    breaking the whole dispatch.
    """
    out: list[ActionableCandidate] = []
    for candidate in candidates:
        ctx = with_actor(
            base_ctx,
            roles=candidate.roles,
            committees=candidate.committees,
            is_applicant=created_by is not None and created_by == candidate.sub,
        )
        for transition in transitions:
            try:
                fires = eval_guard(transition.guard, ctx)
            except GuardError:
                continue
            if fires:
                out.append(candidate)
                break
    return out


@dataclass(slots=True)
class RecipientResolver:
    """Löst Empfänger-Spezifikationen gegen die DB auf."""

    session: AsyncSession

    async def resolve(
        self,
        specs: list[dict[str, Any]],
        *,
        application_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> list[str]:
        """Alle Specs auflösen → sortierte, deduplizierte Adressliste."""
        now = now or datetime.now(UTC)
        out: set[str] = set()
        for spec in specs:
            kind = spec.get("kind")
            ref = spec.get("ref")
            if kind == "group" and ref:
                out.update(await self._emails_for_group(str(ref)))
            elif kind == "role" and ref:
                out.update(await self._emails_for_role(str(ref), now))
            elif kind == "gremium" and ref:
                out.update(await self._emails_for_gremium(str(ref), now))
            elif kind == "applicant" and application_id is not None:
                email = await self._applicant_email(application_id)
                if email:
                    out.add(email)
            elif kind == "email" and ref:
                out.add(str(ref).strip())
            elif kind == "permission" and ref:
                out.update(await self._emails_for_permission(str(ref), now))
            # Unbekannte/unvollständige Spec → still ignorieren (Regel bleibt gültig).
        return sorted(e for e in out if e)

    async def _emails_for_group(self, group: str) -> list[str]:
        rows = (
            await self.session.scalars(
                select(Principal.email).where(
                    Principal.oidc_groups.contains([group]),
                    Principal.email.is_not(None),
                )
            )
        ).all()
        return [e for e in rows if e]

    async def _emails_for_role(self, role_key: str, now: datetime) -> list[str]:
        stmt = (
            select(Principal.email)
            .join(RoleAssignment, RoleAssignment.principal_id == Principal.id)
            .join(Role, Role.id == RoleAssignment.role_id)
            .where(
                Role.key == role_key,
                Principal.email.is_not(None),
                or_(RoleAssignment.valid_from.is_(None), RoleAssignment.valid_from <= now),
                or_(
                    RoleAssignment.valid_until.is_(None),
                    RoleAssignment.valid_until > now,
                ),
            )
        )
        rows = (await self.session.scalars(stmt)).all()
        return [e for e in rows if e]

    async def _emails_for_gremium(self, gremium_ref: str, now: datetime) -> list[str]:
        """Mail-Adressen der aktuell (Amtszeit-Fenster) aktiven Gremium-Mitglieder."""
        try:
            gremium_id = uuid.UUID(gremium_ref)
        except (ValueError, AttributeError):
            return []
        stmt = (
            select(Principal.email)
            .join(GremiumMembership, GremiumMembership.principal_id == Principal.id)
            .where(
                GremiumMembership.gremium_id == gremium_id,
                Principal.email.is_not(None),
                or_(
                    GremiumMembership.valid_from.is_(None),
                    GremiumMembership.valid_from <= now,
                ),
                or_(
                    GremiumMembership.valid_until.is_(None),
                    GremiumMembership.valid_until > now,
                ),
            )
        )
        rows = (await self.session.scalars(stmt)).all()
        return [e for e in rows if e]

    async def _emails_for_permission(self, perm: str, now: datetime) -> list[str]:
        """Adressen aller aktiven Principals, die ``perm`` über eine gültige
        Rollenzuweisung halten (``admin``-Rolle zählt immer, Admin-Bypass)."""
        stmt = principals_with_permission_stmt(perm, now)
        rows = (await self.session.scalars(stmt)).all()
        return [e for e in rows if e]

    async def _applicant_email(self, application_id: uuid.UUID) -> str | None:
        # Anonymisierte Anträge haben keine PII-Mail mehr → nicht adressieren.
        return await self.session.scalar(
            select(Applicant.email).where(
                Applicant.application_id == application_id,
                Applicant.anonymized_at.is_(None),
            )
        )


async def actionable_principal_emails(
    session: AsyncSession,
    *,
    application_id: uuid.UUID,
    state: State | None,
) -> list[str]:
    """Addresses of everyone who can act on the application's current state (#64).

    ``vote`` state → members of the voting gremium (``config.gremiumId``).
    Otherwise exactly the principals for whom at least one manual
    ``requires_action`` transition actually fires (guard satisfied) — mirroring
    the task-list semantics (``list_tasks`` → ``available_transitions``).
    Admins are seeded like every other transition-permission holder but only
    receive mail when a guard fires for them too.
    """
    if state is not None and state.kind == "vote":
        cfg = state.config if isinstance(state.config, dict) else {}
        gid = cfg.get("gremiumId")
        if isinstance(gid, str) and gid:
            return await RecipientResolver(session).resolve(
                [{"kind": "gremium", "ref": gid}]
            )
        return []

    app = await session.scalar(
        select(Application).where(Application.id == application_id)
    )
    if app is None or app.current_state_id is None:
        return []
    # Mirror FlowService._outgoing + the list_tasks predicate: manual,
    # non-branch transitions that count as an open task.
    transitions = list(
        (
            await session.scalars(
                select(Transition)
                .where(
                    Transition.flow_version_id == app.flow_version_id,
                    Transition.from_state_id == app.current_state_id,
                    Transition.automatic.is_(False),
                    Transition.branch.is_(None),
                    Transition.requires_action.is_(True),
                )
                .order_by(Transition.order)
            )
        ).all()
    )
    if not transitions:
        return []

    deadline_passed = await flow_deadline_passed(session, application_id)
    base_ctx = await build_base_context(
        session, app, manual=True, deadline_passed=deadline_passed
    )
    candidates = await _candidates_with_transition_permission(
        session, datetime.now(UTC), gremium_id=app.gremium_id
    )
    firable = firable_candidates(
        candidates, transitions, base_ctx, created_by=app.created_by
    )
    return sorted({c.email for c in firable})


async def state_actionable(session: AsyncSession, state: State | None) -> bool:
    """Aufgaben-Definition (#64, geteilt von Task-Mail #4-3 + Reminder-Worker):
    ``vote``-State oder mindestens ein manueller Übergang mit ``requires_action``.
    States ohne solche Übergänge sind reine Durchgangs-/Endstationen — niemand
    "kann handeln", also weder Task-Mail noch Erinnerung (#9)."""
    if state is None:
        return False
    if state.kind == "vote":
        return True
    count = await session.scalar(
        select(func.count())
        .select_from(Transition)
        .where(
            Transition.from_state_id == state.id,
            Transition.automatic.is_(False),
            Transition.requires_action.is_(True),
        )
    )
    return bool(count)
