"""Zugriffsauflösung für Antrags-Endpunkte (T-12, api.md §1/§3).

Antrags-Routen sind ``A/P``: erreichbar entweder vom **Principal** (Session +
Permission) **oder** vom **Antragsteller** (Magic-Link-Token, auf genau eine
``application_id`` + Scope gebunden). Diese Dependencies vereinen beide Identitäten
zu einem :class:`Access`-Objekt und erzwingen 401 (keine Identität) / 403 (Identität
ohne ausreichendes Recht).

Sichtbarkeit interner Kommentare hängt allein an :attr:`Access.can_see_internal`
(nur Principal) — der Antragsteller sieht ausschließlich ``public`` (api.md §3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import DbSession, get_current_applicant, get_current_principal
from app.modules.applications.models import Application
from app.modules.auth.principal import Applicant, ApplicantScope, Principal
from app.shared.errors import ForbiddenError, UnauthorizedError

READ_PERMISSION = "application.read"
MANAGE_PERMISSION = "application.manage"
# Globale Sonderrechte (#app-read-all / #app-edit-any): jeden Antrag lesen bzw. in
# jedem Flow-State bearbeiten (Letzteres hebt zusätzlich den State-Edit-Lock im
# Service auf).
READ_ALL_PERMISSION = "application.read_all"
EDIT_ANY_PERMISSION = "application.edit_any"


@dataclass(slots=True)
class Access:
    """Aufgelöster Zugriff auf genau einen Antrag (Principal **oder** Applicant)."""

    application_id: UUID
    principal: Principal | None
    applicant: Applicant | None

    @property
    def can_see_internal(self) -> bool:
        """Nur Principals sehen interne Kommentare/PII; Antragsteller nie."""
        return self.principal is not None

    @property
    def is_owning_applicant(self) -> bool:
        """Magic-Link-Antragsteller des eigenen Antrags (kein Principal).

        Nur dieser Zugriff darf eine **unbestätigte** Gast-Einreichung
        (``email_confirmed_at IS NULL``) per Item-Route lesen — Principals/Gremium
        nicht, spiegelnd zur unsichtbaren Listen-Semantik (#AUD-032)."""
        return self.applicant is not None

    @property
    def author_kind(self) -> str:
        return "principal" if self.principal is not None else "applicant"

    @property
    def actor(self) -> str:
        """Audit-Akteur: Principal-``sub`` bzw. ``'applicant'``."""
        return self.principal.sub if self.principal is not None else "applicant"


def resolve_access(
    application_id: UUID,
    principal: Principal | None,
    applicant: Applicant | None,
    *,
    perm: str,
    scope: ApplicantScope,
) -> Access:
    """Principal-Permission **oder** Applicant-Scope gegen den Antrag prüfen.

    Öffentlich, damit angrenzende Module (z. B. files/T-13, deren Pfad nur die
    ``attachment_id`` trägt) denselben A/P-Zugriffspfad nutzen, statt ihn zu duplizieren."""
    if principal is not None:
        if principal.has(perm):
            return Access(application_id, principal, None)
        raise ForbiddenError(f"Missing permission: {perm}")
    if applicant is not None:
        if str(applicant.application_id) == str(application_id) and applicant.allows(
            scope
        ):
            return Access(application_id, None, applicant)
        raise ForbiddenError("Magic-link does not grant access to this application.")
    raise UnauthorizedError("Authentication required.")


async def _is_creator(db: AsyncSession, application_id: UUID, principal: Principal) -> bool:
    """Ist dieser Principal der/die eingeloggte Ersteller:in des Antrags (#24)?"""
    created_by = await db.scalar(
        select(Application.created_by).where(Application.id == application_id)
    )
    return created_by is not None and created_by == principal.sub


async def _committee_can_read(
    db: AsyncSession, application_id: UUID, principal: Principal
) -> bool:
    """Gremium-Mitglied darf den Antrag **lesen** (#committee-read) — rein lesend,
    keine Schreib-/Transitionsrechte. Wahr, wenn der Antrag

    * in einer Kostenstelle (Knoten ODER Vorfahre) liegt, deren ``view_gremium_id``
      einem seiner Gremien zugeordnet ist (#budget-scope), **oder**
    * aktuell in einem ``vote``-State steht, dessen ``config.gremiumId`` einem seiner
      Gremien gehört, **oder**
    * in einer Sitzung eines seiner Gremien (ab)gestimmt wurde/steht (Bestand,
      #vote-read, ``vote → meeting.gremium_id``).

    Spiegelt die SQL-Sammelvariante ``ApplicationsService._committee_read_clauses``
    (Anträge-Liste): beide MÜSSEN dieselben Pfade abdecken, damit ein gelisteter
    Antrag auch in der Detailansicht öffenbar ist (und umgekehrt)."""
    from app.modules.admin.gremium_roles import gremium_member_ids

    gremien = await gremium_member_ids(db, principal.sub)
    if not gremien:
        return False

    # (a) Kostenstelle (Knoten/Vorfahre) mit Sicht-Gremium — kanonische Ahnen-Logik
    #     des Budget-Baums wiederverwendet (statt die Prefix-Query zu duplizieren).
    budget_id = await db.scalar(
        select(Application.budget_id).where(Application.id == application_id)
    )
    if budget_id is not None:
        from app.modules.budget.tree_service import BudgetTreeService

        if await BudgetTreeService(db).can_view_node(budget_id, gremien):
            return True

    # (b) Aktueller ``vote``-State für eines der Gremien (``config.gremiumId``). JSONB
    #     in Python ausgewertet (dialekt-neutral, wie ``ApplicationsService.list_tasks``).
    from app.modules.flow.models import State

    row = (
        await db.execute(
            select(State.kind, State.config)
            .join(Application, Application.current_state_id == State.id)
            .where(Application.id == application_id)
        )
    ).first()
    if row is not None and row.kind == "vote":
        cfg = row.config if isinstance(row.config, dict) else {}
        gid = cfg.get("gremiumId")
        if isinstance(gid, str) and gid and UUID(gid) in gremien:
            return True

    # (c) Bestand: in einer Sitzung eines Mitglieds-Gremiums abgestimmt (#vote-read).
    from app.modules.livevote.models import Meeting
    from app.modules.voting.models import Vote

    voted = await db.scalar(
        select(Vote.id)
        .join(Meeting, Meeting.id == Vote.meeting_id)
        .where(Vote.application_id == application_id, Meeting.gremium_id.in_(gremien))
        .limit(1)
    )
    return voted is not None


async def _resolve_with_creator(
    db: AsyncSession,
    application_id: UUID,
    principal: Principal | None,
    applicant: Applicant | None,
    *,
    perm: str,
    scope: ApplicantScope,
) -> Access:
    """Wie :func:`resolve_access`, lässt aber den eingeloggten Ersteller (created_by ==
    principal.sub) auch ohne ``perm`` zu — für den eigenen Antrag (#24)."""
    try:
        return resolve_access(application_id, principal, applicant, perm=perm, scope=scope)
    except ForbiddenError:
        if principal is not None and await _is_creator(db, application_id, principal):
            return Access(application_id, principal, None)
        raise


async def require_app_read(
    application_id: UUID,
    db: DbSession,
    principal: Annotated[Principal | None, Depends(get_current_principal)],
    applicant: Annotated[Applicant | None, Depends(get_current_applicant)],
) -> Access:
    """Lesezugriff: Principal mit ``application.read``, ``view``-Antragsteller,
    eingeloggte:r Ersteller:in (#24) **oder** Gremium-Mitglied im Lesescope
    (#committee-read, nur lesend): Antrag in einer Sicht-Kostenstelle des Gremiums,
    in einem ``vote``-State für das Gremium oder darin (ab)gestimmt.

    ``application.read_all`` (#app-read-all) gewährt globalen Lesezugriff unabhängig
    von Gremium/Eigentum."""
    if principal is not None and principal.has(READ_ALL_PERMISSION):
        return Access(application_id, principal, None)
    try:
        return await _resolve_with_creator(
            db, application_id, principal, applicant, perm=READ_PERMISSION, scope="view"
        )
    except ForbiddenError:
        if principal is not None and await _committee_can_read(
            db, application_id, principal
        ):
            return Access(application_id, principal, None)
        raise


async def require_app_edit(
    application_id: UUID,
    db: DbSession,
    principal: Annotated[Principal | None, Depends(get_current_principal)],
    applicant: Annotated[Applicant | None, Depends(get_current_applicant)],
) -> Access:
    """Schreibzugriff: Principal mit ``application.manage``, ``edit``-Antragsteller oder
    eingeloggte:r Ersteller:in des eigenen Antrags (#24).

    Der Edit-Lock (``state.editAllowed``) wird **zusätzlich** im Service geprüft (409),
    unabhängig von der Identität. ``application.edit_any`` (#app-edit-any) gewährt
    Schreibzugriff und hebt den State-Lock im Service auf."""
    if principal is not None and principal.has(EDIT_ANY_PERMISSION):
        return Access(application_id, principal, None)
    return await _resolve_with_creator(
        db, application_id, principal, applicant, perm=MANAGE_PERMISSION, scope="edit"
    )
