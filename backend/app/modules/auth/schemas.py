"""Pydantic schemas for the auth module."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.shared.altcha import AltchaSolutionStr


class MagicLinkRequest(BaseModel):
    """Body of `POST /auth/magic-link`. The response is always 202 to block enumeration."""

    email: EmailStr
    application_id: UUID | None = None
    # ALTCHA proof-of-work solution. The schema checks only the structure, so a
    # malformed value gives 422. `require_altcha` runs the cryptographic check.
    # Without a secret (dev and test) only the structural check remains.
    altcha: AltchaSolutionStr | None = None


class MagicLinkVerifyRequest(BaseModel):
    token: str = Field(min_length=1)


class MagicLinkVerifyOut(BaseModel):
    """Result of a magic-link verify.

    The applicant session travels only in the HttpOnly cookie, never in the body.
    JavaScript cannot read the token, which protects against XSS.
    """

    application_id: UUID
    scope: Literal["edit", "view"]


class LogoutOut(BaseModel):
    """Result of an RP-initiated logout.

    With OIDC, `logout_url` ends the Keycloak SSO session. The frontend must redirect
    the browser there. A purely local logout gives `null`.
    """

    logout_url: str | None = None


class GremiumRef(BaseModel):
    """Slim Gremium reference for the "my Gremien" view."""

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
    # Gremien the principal is a member of (valid role assignment). This is the base of
    # the user-facing "my Gremien" view.
    gremien: list[GremiumRef] = []
    # Gremien the principal MANAGES through a gremium role (`session.manage`). The
    # frontend uses this to show "create meeting" without global `meeting.manage`.
    session_manage_gremien: list[UUID] = []
    # True if at least one cost center has a Gremium of the principal as visibility
    # root. The frontend uses this to show the budget tab without a global `budget.*`
    # permission.
    has_scoped_budget_view: bool = False
    # True if the principal is in at least one substitute pool. The frontend uses this
    # to show the meeting timeline to pool substitutes. The live channel still needs a
    # concrete delegation.
    in_substitute_pool: bool = False
