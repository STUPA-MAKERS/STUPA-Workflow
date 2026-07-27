"""Core auth types.

This is a leaf module. It imports nothing from `app.deps`, which breaks the import cycle
between `app.deps` and this package. `app.deps` re-exports `Principal` and `Applicant`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ApplicantScope = Literal["edit", "view"]


@dataclass(slots=True)
class Principal:
    """An OIDC member or admin with resolved RBAC roles, permissions and groups."""

    sub: str
    email: str | None = None
    display_name: str | None = None
    roles: list[str] = field(default_factory=list)
    permissions: set[str] = field(default_factory=set)
    groups: set[str] = field(default_factory=set)
    # OAuth scope cap for MCP. `None` marks an unscoped session cookie with the full
    # range. A set makes only these permissions reachable. The cap also applies to an
    # admin, so a scoped token cannot bypass it through the admin role.
    scope_permissions: frozenset[str] | None = None

    def has(self, perm: str) -> bool:
        # Check the scope cap first. A permission outside the token scope stays
        # unreachable, whatever the role or the admin bypass says.
        if self.scope_permissions is not None and perm not in self.scope_permissions:
            return False
        # An admin holds every in-scope right, whatever the explicitly assigned
        # permissions are. This is the single RBAC chokepoint.
        return "admin" in self.roles or perm in self.permissions

    def in_group(self, group: str) -> bool:
        return group in self.groups


@dataclass(slots=True)
class Applicant:
    """Magic-link applicant, bound to exactly one `application_id` plus scope."""

    application_id: str
    scope: ApplicantScope

    def allows(self, required: ApplicantScope) -> bool:
        """Check whether the scope of this token covers the required scope.

        An `edit` token also covers `view`. A `view` token covers only `view`.
        """
        return self.scope == "edit" or self.scope == required
