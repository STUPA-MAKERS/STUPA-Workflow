"""Resolve rule ``recipients`` specs to concrete mail addresses from the DB.

Recipient kinds:

``{"kind":"group","ref":"stupa"}``: principals in the OIDC group ``ref``.
``{"kind":"role","ref":"manager"}``: principals with an assignment of role ``ref``.
``{"kind":"gremium","ref":"<id>"}``: current members of Gremium ``ref``.
``{"kind":"email","ref":"a@b.c"}``: one fixed literal address.
``{"kind":"permission","ref":"x.y"}``: active principals that hold the permission.

Three kinds need an application: ``applicant``, ``voteGremium`` and ``budgetGremium``.
The resolver does not read an application. The caller gives it an expander
(`app.modules.applications.mail_data.application_specs`) that turns such a spec into
plain specs. Without an expander these kinds give no address.

The resolver removes duplicates and sorts the result. It drops empty addresses.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import (
    Principal,
    Role,
    RoleAssignment,
    RolePermission,
)
from app.modules.gremien.models import GremiumMembership

#: Admin role key; it bypasses every permission check. It must match ``Principal.has``,
#: and the recipient resolution runs set-based in SQL, not through ``has``, so the key
#: stays one constant.
ADMIN_ROLE_KEY = "admin"


def _permission_conds(perm: str) -> list[ColumnElement[bool]]:
    """Build the shared WHERE clauses of the permission-holder queries.

    This function mirrors ``Principal.has`` in one place. It applies the admin bypass
    and the RolePermission join, so every resolver builds the identical candidate set.
    """
    return [
        Principal.email.is_not(None),
        Principal.active.is_(True),
        or_(RolePermission.permission == perm, Role.key == ADMIN_ROLE_KEY),
    ]


def principals_with_permission_stmt(perm: str) -> Select[str | None]:
    """Select the mails of active principals that hold ``perm``.

    The principal needs a role assignment. The admin bypass always counts
    (``ADMIN_ROLE_KEY``). The statement builds on ``_permission_conds``, so both
    resolvers stay consistent with ``Principal.has``.
    """
    return (
        select(Principal.email)
        .join(RoleAssignment, RoleAssignment.principal_id == Principal.id)
        .join(Role, Role.id == RoleAssignment.role_id)
        .outerjoin(RolePermission, RolePermission.role_id == Role.id)
        .where(*_permission_conds(perm))
        .distinct()
    )


def principal_rows_with_permission_stmt(
    perm: str,
) -> Select[uuid.UUID, str, str | None, list[str] | None]:
    """Select the identity rows of the permission holders.

    The WHERE clauses match the mail statement. The projection
    ``(id, sub, email, oidc_groups)`` lets the caller resolve the per-principal roles
    and committees that guard evaluation needs. The admin arm stays in the seed and
    mirrors ``Principal.has``. Admins are candidates only. A guard must still fire
    before they receive mail.
    """
    return (
        select(Principal.id, Principal.sub, Principal.email, Principal.oidc_groups)
        .join(RoleAssignment, RoleAssignment.principal_id == Principal.id)
        .join(Role, Role.id == RoleAssignment.role_id)
        .outerjoin(RolePermission, RolePermission.role_id == Role.id)
        .where(*_permission_conds(perm))
        .distinct()
    )


#: Turns a spec that needs an application (``applicant``, ``voteGremium``,
#: ``budgetGremium``) into plain specs. `app.modules.applications.mail_data` has it.
type SpecExpander = Callable[[AsyncSession, str, uuid.UUID], Awaitable[list[dict[str, Any]]]]


@dataclass(frozen=True, slots=True)
class RecipientResolver:
    """Resolve recipient specs against the DB."""

    session: AsyncSession
    expand: SpecExpander | None = None

    async def resolve(
        self,
        specs: list[dict[str, Any]],
        *,
        application_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> list[str]:
        """Resolve all specs into a sorted address list without duplicates.

        An unknown or incomplete spec is ignored, so the rule stays valid.
        """
        found = [await self._resolve_spec(spec, application_id) for spec in specs]
        return sorted({e for emails in found for e in emails if e})

    async def _resolve_spec(
        self, spec: dict[str, Any], application_id: uuid.UUID | None
    ) -> list[str]:
        """Return the addresses of one spec; an unknown or incomplete spec gives none."""
        match spec.get("kind"), spec.get("ref"), application_id:
            case "group", ref, _ if ref:
                return await self._emails_for_group(str(ref))
            case "role", ref, _ if ref:
                return await self._emails_for_role(str(ref))
            case "gremium", ref, _ if ref:
                return await self._emails_for_gremium(str(ref))
            case "email", ref, _ if ref:
                return [str(ref).strip()]
            case "permission", ref, _ if ref:
                return await self._emails_for_permission(str(ref))
            case kind, _, app_id if app_id is not None and self.expand is not None:
                plain = await self.expand(self.session, str(kind), app_id)
                found = [await self._resolve_spec(spec, None) for spec in plain]
                return [email for emails in found for email in emails]
            case _:
                return []

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

    async def _emails_for_role(self, role_key: str) -> list[str]:
        stmt = (
            select(Principal.email)
            .join(RoleAssignment, RoleAssignment.principal_id == Principal.id)
            .join(Role, Role.id == RoleAssignment.role_id)
            .where(
                Role.key == role_key,
                Principal.email.is_not(None),
            )
        )
        rows = (await self.session.scalars(stmt)).all()
        return [e for e in rows if e]

    async def _emails_for_gremium(self, gremium_ref: str) -> list[str]:
        """Return the addresses of the gremium members."""
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
            )
        )
        rows = (await self.session.scalars(stmt)).all()
        return [e for e in rows if e]

    async def _emails_for_permission(self, perm: str) -> list[str]:
        """Return the addresses of active principals that hold ``perm``.

        A role assignment must grant the permission. The ``admin`` role always
        counts.
        """
        stmt = principals_with_permission_stmt(perm)
        rows = (await self.session.scalars(stmt)).all()
        return [e for e in rows if e]
