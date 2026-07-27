"""Pydantic schemas of the files API.

``AttachmentOut`` follows the documented contract exactly. ``SignedUrlOut`` returns the
app-relative download route that the authorization layer gates. It is NOT an S3v4-signed
MinIO URL and it gives no direct bucket access. The ``/download`` route checks
authorization on its own. ``expiresIn`` is only a cache hint for the frontend.
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
    """App-relative download route that the authorization layer gates.

    ``url`` is the ``/api/attachments/{id}/download`` route. It carries no token and no
    signature and it does not expire. The endpoint checks authorization on every call.
    ``expiresIn`` is therefore no security or expiry guarantee. It is only an advisory
    cache hint for the frontend, in seconds.
    """

    url: str
    expiresIn: int  # advisory cache hint in seconds, not a URL expiry
