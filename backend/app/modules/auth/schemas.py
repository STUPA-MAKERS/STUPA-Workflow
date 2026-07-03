"""Pydantic schemas for the auth module."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.shared.altcha import AltchaSolutionStr


class MagicLinkRequest(BaseModel):
    """`POST /auth/magic-link` — anti-enumeration: the response is always 202."""

    email: EmailStr
    application_id: UUID | None = None
    # ALTCHA PoW solution. Structurally validated by the schema (malformed -> 422);
    # cryptographic verification runs via `require_altcha`. Without a secret
    # (dev/test) only the structural check remains.
    altcha: AltchaSolutionStr | None = None


class MagicLinkVerifyRequest(BaseModel):
    token: str = Field(min_length=1)


class MagicLinkVerifyOut(BaseModel):
    """Applicant session travels only in the HttpOnly cookie, never in the body —
    no token reachable from JS (XSS protection)."""

    application_id: UUID
    scope: Literal["edit", "view"]


class LogoutOut(BaseModel):
    """RP-initiated logout: `logout_url` (if OIDC) ends the Keycloak SSO session;
    the frontend redirects the browser there. `null` for a purely local logout."""

    logout_url: str | None = None


class GremiumRef(BaseModel):
    """Slim gremium reference for the "my gremien" view."""

    id: UUID
    name: str
    slug: str


class MeOut(BaseModel):
    sub: str
    email: str | None = None
    display_name: str | None = None
    roles: list[str]
    permissions: list[str]
    groups: list[str]
    # Gremien the principal is a member of (valid role assignment) — basis of
    # the user-facing "my gremien" view.
    gremien: list[GremiumRef] = []
    # Gremien the principal MANAGES via their gremium role (``session.manage``) —
    # frontend gating for "create meeting" without global ``meeting.manage``.
    session_manage_gremien: list[UUID] = []
    # At least one cost centre has a member gremium as visibility root —
    # frontend gating of the budget tab without a global ``budget.*`` permission.
    has_scoped_budget_view: bool = False
    # Principal is in at least one substitute pool — frontend gating so pool
    # substitutes see the meeting timeline (live channel needs a concrete delegation).
    in_substitute_pool: bool = False
