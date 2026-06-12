"""Pydantic-Schemata des auth-Moduls (api.md §1/§5)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.shared.altcha import AltchaSolutionStr


class MagicLinkRequest(BaseModel):
    """`POST /auth/magic-link` — Anti-Enumeration: Antwort immer 202."""

    email: EmailStr
    application_id: UUID | None = None
    # Altcha-Solution (PoW). Strukturell schon im Schema validiert (malformt → 422,
    # `AltchaSolutionStr`); die kryptografische Verifikation läuft zusätzlich via
    # `require_altcha` (security.md §7, Issue #23). Ohne Secret (Dev/Test) bleibt nur die
    # Strukturprüfung — ein malformtes Payload wird trotzdem abgelehnt.
    altcha: AltchaSolutionStr | None = None


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


class GremiumRef(BaseModel):
    """Schlankes Gremium-Referenzobjekt für die »Meine Gremien«-Ansicht (#5)."""

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
    # Gremien, in denen der Principal über eine (gültige) Rollenzuweisung Mitglied
    # ist — Basis der nutzerseitigen »Meine Gremien«-Ansicht (#5).
    gremien: list[GremiumRef] = []
    # Gremien, die der Principal über seine Gremium-Rolle VERWALTET
    # (``session.manage``, z. B. vorstand/manager) — Basis fürs FE-Gating
    # »Sitzung anlegen« ohne globale ``meeting.manage``-Permission.
    session_manage_gremien: list[UUID] = []
    # Mindestens eine Kostenstelle ist einem Mitglieds-Gremium des Principals als
    # Sichtbarkeits-Root zugeordnet (#budget-scope) — FE-Gating des Budget-Tabs
    # ohne globale ``budget.*``-Permission.
    has_scoped_budget_view: bool = False
