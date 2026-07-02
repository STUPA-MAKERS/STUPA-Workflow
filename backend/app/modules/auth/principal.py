"""Core auth types (leaf module, imports nothing from `app.deps`) — breaks the
deps <-> auth import cycle. `app.deps` re-exports `Principal`/`Applicant`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ApplicantScope = Literal["edit", "view"]


@dataclass(slots=True)
class Principal:
    """OIDC member/admin with resolved roles/permissions/groups (RBAC)."""

    sub: str
    email: str | None = None
    display_name: str | None = None
    roles: list[str] = field(default_factory=list)
    permissions: set[str] = field(default_factory=set)
    groups: set[str] = field(default_factory=set)
    # OAuth scope cap (MCP): `None` = unscoped (session/cookie, full range); a set
    # = only these permissions are reachable — applies to admins too, so a scoped
    # token cannot bypass the cap via the admin role.
    scope_permissions: frozenset[str] | None = None

    def has(self, perm: str) -> bool:
        # Scope cap first: a permission outside the token scope is unreachable
        # regardless of role/admin bypass.
        if self.scope_permissions is not None and perm not in self.scope_permissions:
            return False
        # Admin always holds all (in-scope) rights, regardless of explicitly
        # assigned permissions. Single RBAC chokepoint.
        return "admin" in self.roles or perm in self.permissions

    def in_group(self, group: str) -> bool:
        return group in self.groups


@dataclass(slots=True)
class Applicant:
    """Magic-link applicant, bound to exactly one `application_id` plus scope."""

    application_id: str
    scope: ApplicantScope

    def allows(self, required: ApplicantScope) -> bool:
        """An `edit` token also covers `view`; a `view` token covers only `view`."""
        return self.scope == "edit" or self.scope == required
