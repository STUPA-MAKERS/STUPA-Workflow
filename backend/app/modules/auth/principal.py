"""Auth-Kern-Typen (leaf, importiert nichts aus `app.deps`) — bricht den Import-Zyklus
deps ↔ auth. `app.deps` re-exportiert `Principal`/`Applicant` für Bestands-Importe."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ApplicantScope = Literal["edit", "view"]


@dataclass(slots=True)
class Principal:
    """OIDC-Mitglied/Admin mit aufgelösten Rollen/Permissions/Gruppen (RBAC)."""

    sub: str
    email: str | None = None
    display_name: str | None = None
    roles: list[str] = field(default_factory=list)
    permissions: set[str] = field(default_factory=set)
    groups: set[str] = field(default_factory=set)

    def has(self, perm: str) -> bool:
        # Admin hat IMMER alle Rechte (#15) — unabhängig von den explizit
        # zugewiesenen Permissions. Einziger RBAC-Chokepoint (require_principal &
        # alle `.has()`-Aufrufe).
        return "admin" in self.roles or perm in self.permissions

    def in_group(self, group: str) -> bool:
        return group in self.groups


@dataclass(slots=True)
class Applicant:
    """Magic-Link-Antragsteller, gebunden an genau eine `application_id` + Scope."""

    application_id: str
    scope: ApplicantScope

    def allows(self, required: ApplicantScope) -> bool:
        """`edit`-Token deckt `view` mit ab; `view`-Token nur `view`."""
        return self.scope == "edit" or self.scope == required
