"""Pydantic-Schemas der files-API (api.md »files«).

``AttachmentOut`` folgt exakt dem dokumentierten Contract (FE-T-31). ``SignedUrlOut``
liefert die **app-relative, authz-gated** Download-Route (kein direkter Bucket-Zugriff,
security.md §6) — KEINE S3v4-signierte MinIO-URL (#AUD-055). Die Autorisierung erzwingt
die ``/download``-Route unabhängig; ``expiresIn`` ist nur ein FE-Cache-Hinweis.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class AttachmentOut(BaseModel):
    """Anhang-Metadaten (api.md §5 ``AttachmentOut``)."""

    id: UUID
    filename: str
    mime: str
    size: int
    scanned: bool
    is_comparison_offer: bool


class SignedUrlOut(BaseModel):
    """App-relative, authz-gated Download-Route (security.md §6, #AUD-055).

    Die ``url`` ist die ``/api/attachments/{id}/download``-Route — sie trägt KEIN Token
    und KEINE Signatur und läuft NICHT ab; die Autorisierung erzwingt der Endpunkt bei
    jedem Aufruf selbst. ``expiresIn`` ist daher KEINE Sicherheits-/Ablaufgarantie,
    sondern lediglich ein advisory FE-Cache-Hinweis (s).
    """

    url: str
    expiresIn: int  # advisory FE-Cache-Hinweis (s) — KEIN URL-Ablauf
