"""DI-Stubs (deps.py).

Skelett-Layer für die echten Auth-/Scope-Resolver aus T-10. Hier nur Typen +
Contract: `require_principal(*perms)` (401/403), `require_applicant(scope)` (401/410),
`get_session` (DB). Reale OIDC-/Magic-Link-Auflösung folgt in T-10.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Literal

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.shared.errors import ForbiddenError, UnauthorizedError

DbSession = Annotated[AsyncSession, Depends(get_session)]

ApplicantScope = Literal["edit", "view"]


@dataclass(slots=True)
class Principal:
    """OIDC-Mitglied/Admin (auth-Modul liefert reale Instanz, T-10)."""

    sub: str
    roles: list[str] = field(default_factory=list)
    permissions: set[str] = field(default_factory=set)
    groups: set[str] = field(default_factory=set)

    def has(self, perm: str) -> bool:
        return perm in self.permissions


@dataclass(slots=True)
class Applicant:
    """Magic-Link-Antragsteller, gebunden an genau eine application_id (T-10)."""

    application_id: str
    scope: ApplicantScope


def get_current_principal() -> Principal | None:
    """Stub: Session-Auflösung folgt in T-10 → aktuell keine Principal."""
    return None


def get_current_applicant() -> Applicant | None:
    """Stub: Magic-Link-Token-Auflösung folgt in T-10 → aktuell keiner."""
    return None


def require_principal(*perms: str) -> Callable[..., Principal]:
    """Dependency-Factory: 401 ohne Session, 403 bei fehlender Permission."""

    def dependency(
        principal: Annotated[Principal | None, Depends(get_current_principal)],
    ) -> Principal:
        if principal is None:
            raise UnauthorizedError("Authentication required.")
        missing = [p for p in perms if not principal.has(p)]
        if missing:
            raise ForbiddenError(f"Missing permission(s): {', '.join(missing)}")
        return principal

    return dependency


def require_applicant(scope: ApplicantScope = "view") -> Callable[..., Applicant]:
    """Dependency-Factory: 401 ohne gültigen Magic-Link-Scope (Detailprüfung T-10)."""

    def dependency(
        applicant: Annotated[Applicant | None, Depends(get_current_applicant)],
    ) -> Applicant:
        if applicant is None:
            raise UnauthorizedError("Valid magic-link required.")
        return applicant

    return dependency
