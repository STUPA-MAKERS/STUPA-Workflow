"""Pydantic-Schemata des auth-Moduls (api.md §1/§5)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class MagicLinkRequest(BaseModel):
    """`POST /auth/magic-link` — Anti-Enumeration: Antwort immer 202."""

    email: EmailStr
    application_id: UUID | None = None
    # Altcha-Solution (PoW). Serverseitig verifiziert via `require_altcha` (security.md §7,
    # Issue #23); ohne konfiguriertes Secret (Dev/Test) wird das Feld nur durchgereicht.
    altcha: str | None = None


class MagicLinkVerifyRequest(BaseModel):
    token: str = Field(min_length=1)


class MagicLinkVerifyOut(BaseModel):
    """Applicant-Session wird **ausschließlich** über das HttpOnly-Cookie geführt
    (nicht im Body) — kein Token im JS greifbar (XSS-Schutz, security.md §1)."""

    application_id: UUID
    scope: Literal["edit", "view"]


class LogoutOut(BaseModel):
    """RP-Initiated Logout: `logout_url` (falls OIDC) zum Beenden der Keycloak-SSO-
    Session; das FE leitet den Browser dorthin weiter. `null` bei reinem Local-Logout."""

    logout_url: str | None = None


class MeOut(BaseModel):
    sub: str
    email: str | None = None
    display_name: str | None = None
    roles: list[str]
    permissions: list[str]
    groups: list[str]
