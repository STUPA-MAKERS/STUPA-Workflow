"""Pydantic-Schemata des auth-Moduls (api.md §1/§5)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class MagicLinkRequest(BaseModel):
    """`POST /auth/magic-link` — Anti-Enumeration: Antwort immer 202."""

    email: EmailStr
    application_id: UUID | None = None
    # Altcha-Solution (PoW). Verifikation kommt mit dem Captcha-Task — Feld hier
    # bereits im Contract, damit das FE stabil bleibt.
    altcha: str | None = None


class MagicLinkVerifyRequest(BaseModel):
    token: str = Field(min_length=1)


class MagicLinkVerifyOut(BaseModel):
    application_id: UUID
    scope: Literal["edit", "view"]
    token: str  # Applicant-Session-Token (Bearer/`?t=`), zusätzlich als Cookie gesetzt


class MeOut(BaseModel):
    sub: str
    email: str | None = None
    display_name: str | None = None
    roles: list[str]
    permissions: list[str]
    groups: list[str]
