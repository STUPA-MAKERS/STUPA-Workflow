"""Pydantic-Schemas der files-API (api.md »files«).

``AttachmentOut`` folgt exakt dem dokumentierten Contract (FE-T-31). ``SignedUrlOut``
liefert die kurzlebige MinIO-URL + Restlaufzeit (security.md §6: kein direkter Bucket-
Zugriff).
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
    """Kurzlebige, signierte Download-URL (security.md §6)."""

    url: str
    expiresIn: int  # Restlaufzeit in Sekunden
