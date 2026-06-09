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
    """Lesezugriff: Principal mit ``application.read``, ``view``-Antragsteller oder
    eingeloggte:r Ersteller:in des eigenen Antrags (#24)."""
    return await _resolve_with_creator(
        db, application_id, principal, applicant, perm=READ_PERMISSION, scope="view"
    )


async def require_app_edit(
    application_id: UUID,
    db: DbSession,
    principal: Annotated[Principal | None, Depends(get_current_principal)],
    applicant: Annotated[Applicant | None, Depends(get_current_applicant)],
) -> Access:
    """Schreibzugriff: Principal mit ``application.manage``, ``edit``-Antragsteller oder
    eingeloggte:r Ersteller:in des eigenen Antrags (#24).

    Der Edit-Lock (``state.editAllowed``) wird **zusätzlich** im Service geprüft (409),
    unabhängig von der Identität."""
    return await _resolve_with_creator(
        db, application_id, principal, applicant, perm=MANAGE_PERMISSION, scope="edit"
    )
