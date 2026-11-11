"""Pydantic schemas for the auth module."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal
from uuid import UUID

from pydantic import EmailStr, Field

from app.shared.altcha import AltchaSolutionStr
from app.shared.schemas import FrozenModel


class MagicLinkRequest(FrozenModel, frozen=True):
    """Body of `POST /auth/magic-link`. The response is always 202 to block enumeration."""

    email: EmailStr
    application_id: UUID | None = None
    #: ALTCHA proof-of-work solution. The schema checks only the structure, so a
    #: malformed value gives 422. `require_altcha` runs the cryptographic check.
    #: Without a secret (dev and test) only the structural check remains.
    altcha: AltchaSolutionStr | None = None


class EmailLoginRequest(FrozenModel, frozen=True):
    """Body of `POST /auth/email-login`. The response is always 202 to block enumeration."""

    email: EmailStr
    #: ALTCHA proof-of-work solution; `require_altcha` runs the cryptographic check.
    altcha: AltchaSolutionStr | None = None


class MagicLinkVerifyRequest(FrozenModel, frozen=True):
    """Body of the magic-link verify: the token from the URL fragment."""

    token: str = Field(min_length=1)


class MagicLinkVerifyOut(FrozenModel, frozen=True):
    """Result of a magic-link verify.

    The applicant session travels only in the HttpOnly cookie, never in the body.
    JavaScript cannot read the token, which protects against XSS.
    """

    application_id: UUID
    #: Always `edit`: the applicant session has no scope, and each action checks the
    #: current state of the application.
    scope: Literal["edit"] = "edit"


class LogoutOut(FrozenModel, frozen=True):
    """Result of an RP-initiated logout.

    With OIDC, `logout_url` ends the SSO session at the IdP. The frontend must redirect
    the browser there. A purely local logout gives `null`.
    """

    logout_url: str | None = None


class GremiumRef(FrozenModel, frozen=True):
    """Slim Gremium reference for the "my Gremien" view."""

    id: UUID
    name: str
    slug: str


class MeOut(FrozenModel, frozen=True):
    """The logged-in principal with its roles, permissions and Gremium links."""

    sub: str
    email: str | None = None
    display_name: str | None = None
    roles: tuple[str, ...]
    permissions: tuple[str, ...]
    groups: tuple[str, ...]
    #: Gremien the principal is a member of (valid role assignment). This is the base of
    #: the user-facing "my Gremien" view.
    gremien: tuple[GremiumRef, ...] = ()
    #: Gremien the principal MANAGES through a gremium role (`session.manage`). The
    #: frontend uses this to show "create meeting". The OAuth scope caps the list.
    session_manage_gremien: tuple[UUID, ...] = ()
    #: Gremium id to the gremium permissions of the active role of the principal in
    #: that gremium. The OAuth scope caps the lists: a key outside the token scope does
    #: not show. The frontend gates the meeting pages on it. This is UX only; the
    #: server checks every call.
    gremium_permissions: Mapping[UUID, tuple[str, ...]] = {}
    #: True if at least one cost center has a Gremium of the principal as visibility
    #: root. The frontend uses this to show the budget tab without a global `budget.*`
    #: permission.
    has_scoped_budget_view: bool = False
    #: True if the principal is in at least one substitute pool. The frontend uses this
    #: to show the meeting timeline to pool substitutes. The live channel still needs a
    #: concrete delegation.
    in_substitute_pool: bool = False
    #: True if the principal reported at least one ticket that is not anonymized. The
    #: frontend uses this to show the tab "Tickets" without `ticket.manage`.
    has_reported_tickets: bool = False
