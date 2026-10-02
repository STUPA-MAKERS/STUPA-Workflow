"""Pydantic schemas of the files API.

``AttachmentOut`` follows the documented contract exactly. ``SignedUrlOut`` returns the
app-relative download route that the authorization layer gates. It is NOT an S3v4-signed
MinIO URL and it gives no direct bucket access. The ``/download`` route checks
authorization on its own. ``expiresIn`` is only a cache hint for the frontend.
"""

from __future__ import annotations

from datetime import datetime
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


class DraftAttachmentOut(AttachmentOut):
    """201 response of ``POST /apply/attachments`` (Z4).

    ``draftToken`` is the token of the draft. The first upload issues it, every later
    upload echoes it. The wizard sends it with each further upload, with a delete and
    with the submit. ``draftExpiresAt`` is the end of all drafts of the token.
    """

    draftToken: str
    draftExpiresAt: datetime


class SignedUrlOut(BaseModel):
    """App-relative download route that the authorization layer gates.

    ``url`` is the ``/api/attachments/{id}/download`` route. It carries no token and no
    signature and it does not expire. The endpoint checks authorization on every call.
    ``expiresIn`` is therefore no security or expiry guarantee. It is only an advisory
    cache hint for the frontend, in seconds.
    """

    url: str
    expiresIn: int  # advisory cache hint in seconds, not a URL expiry
