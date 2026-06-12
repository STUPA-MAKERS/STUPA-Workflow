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
Kommentar-/Task-Mails #4-1/#4-3 genutzt).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import GremiumMembership
from app.modules.applications.models import Applicant
from app.modules.auth.models import Principal, Role, RoleAssignment, RolePermission
from app.modules.flow.models import State, Transition


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
                    RoleAssignment.valid_until >= now,
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

    async def _applicant_email(self, application_id: uuid.UUID) -> str | None:
        return await self.session.scalar(
            select(Applicant.email).where(
                Applicant.application_id == application_id,
            )
        )


async def actionable_principal_emails(
    session: AsyncSession,
    *,
    state: State | None,
    gremium_id: uuid.UUID | None,
) -> list[str]:
    """Adressen aller, die am aktuellen State handeln können (Task-Semantik #64).

    ``vote``-State → Mitglieder des abstimmenden Gremiums (``config.gremiumId``);
    sonst Principals mit aktiver Rollenzuweisung, deren Rolle
    ``application.transition`` trägt (global oder im Antrags-Gremium) — die
    ``admin``-Rolle zählt immer (Admin-Bypass hat alle Rechte)."""
    if state is not None and state.kind == "vote":
        cfg = state.config if isinstance(state.config, dict) else {}
        gid = cfg.get("gremiumId")
        if isinstance(gid, str) and gid:
            return await RecipientResolver(session).resolve(
                [{"kind": "gremium", "ref": gid}]
            )
        return []

    now = datetime.now(UTC)
    stmt = (
        select(Principal.email)
        .join(RoleAssignment, RoleAssignment.principal_id == Principal.id)
        .join(Role, Role.id == RoleAssignment.role_id)
        .outerjoin(RolePermission, RolePermission.role_id == Role.id)
        .where(
            Principal.email.is_not(None),
            Principal.active.is_(True),
            or_(
                RoleAssignment.valid_from.is_(None),
                RoleAssignment.valid_from <= now,
            ),
            or_(
                RoleAssignment.valid_until.is_(None),
                RoleAssignment.valid_until > now,
            ),
            or_(
                RoleAssignment.gremium_id.is_(None),
                RoleAssignment.gremium_id == gremium_id,
            ),
            or_(
                RolePermission.permission == "application.transition",
                Role.key == "admin",
            ),
        )
        .distinct()
    )
    rows = (await session.scalars(stmt)).all()
    return sorted({e for e in rows if e})


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
