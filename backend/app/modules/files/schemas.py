"""Pydantic schemas of the files API.

``AttachmentOut`` follows the documented contract exactly. ``SignedUrlOut`` returns the
app-relative, authz-gated download route (no direct bucket access) — NOT an S3v4-signed
MinIO URL. The ``/download`` route enforces authorization independently; ``expiresIn`` is
only a frontend cache hint.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class AttachmentOut(BaseModel):
    """Attachment metadata."""

    id: UUID
    filename: str
    mime: str
    size: int
    scanned: bool
    is_comparison_offer: bool


class SignedUrlOut(BaseModel):
    """App-relative, authz-gated download route.

    ``url`` is the ``/api/attachments/{id}/download`` route — it carries no token and no
    signature and does not expire; the endpoint enforces authorization on every call.
    ``expiresIn`` is therefore not a security/expiry guarantee, only an advisory frontend
    cache hint (seconds).
    """

    url: str
    expiresIn: int  # advisory frontend cache hint (s) — not a URL expiry
