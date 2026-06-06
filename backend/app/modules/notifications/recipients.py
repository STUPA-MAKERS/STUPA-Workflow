"""Empfänger-Resolver: Regel-`recipients` → konkrete Mail-Adressen (DB).

Empfängertypen (data-model §5.4):

* ``{"kind":"group","ref":"stupa"}``  — Principals mit OIDC-Gruppe `ref`.
* ``{"kind":"role","ref":"manager"}`` — Principals mit aktiver Rollen-Zuweisung `ref`.
* ``{"kind":"applicant"}``            — Antragsteller-Mail des auslösenden Antrags.

Ergebnis ist dedupliziert + sortiert; leere/anonymisierte Adressen fallen raus.
Anonymisierte Applicants (email NULL) → kein Versand (DSGVO).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Applicant
from app.modules.auth.models import Principal, Role, RoleAssignment


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
            elif kind == "applicant" and application_id is not None:
                email = await self._applicant_email(application_id)
                if email:
                    out.add(email)
            # Unbekannte/unvollständige Spec → still ignorieren (Regel bleibt gültig).
        return sorted(out)

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

    async def _applicant_email(self, application_id: uuid.UUID) -> str | None:
        return await self.session.scalar(
            select(Applicant.email).where(
                Applicant.application_id == application_id,
                Applicant.anonymized_at.is_(None),
            )
        )
