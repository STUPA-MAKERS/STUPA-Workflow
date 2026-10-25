"""Pydantic schemas of the files API.

``AttachmentOut`` follows the documented contract exactly. ``SignedUrlOut`` returns the
app-relative download route that the authorization layer gates. It is NOT an S3v4-signed
MinIO URL and it gives no direct bucket access. The ``/download`` route checks
authorization on its own. ``expiresIn`` is only a cache hint for the frontend.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    from app.modules.files.models import Attachment

#: The most files one chat message binds.
MAX_MESSAGE_ATTACHMENTS = 5

#: The scan state of a file on the wire. ``scanning`` while ClamAV runs, ``clean``
#: when the file downloads, ``quarantined`` after a finding or a removal.
ScanState = Literal["scanning", "clean", "quarantined"]


class AttachmentOut(BaseModel):
    """Attachment metadata."""

    id: UUID
    filename: str
    mime: str
    size: int
    scanned: bool


class DraftAttachmentOut(AttachmentOut):
    """201 response of ``POST /apply/attachments``.

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


class MessageAttachmentOut(BaseModel):
    """The file of a chat message, with its scan state."""

    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    filename: str
    mime: str
    size: int
    scan_state: ScanState = Field(serialization_alias="scanState")


def message_attachment_out(row: Attachment) -> MessageAttachmentOut:
    """Map an attachment row to its wire form.

    ``scanned`` false gives ``scanning``. A clean scan with an object gives ``clean``.
    Anything else (a finding, or a removed object) gives ``quarantined``.
    """
    if not row.scanned:
        state: ScanState = "scanning"
    elif row.scan_result == "clean" and row.storage_key is not None:
        state = "clean"
    else:
        state = "quarantined"
    return MessageAttachmentOut(
        id=row.id, filename=row.filename, mime=row.mime, size=row.size, scan_state=state
    )


class MessageFilesIn(BaseModel):
    """The files of a message create: draft ids of ``POST /apply/attachments``.

    A subclass has a ``body``. The body may be empty only with at least one file.
    ``draftToken`` is required with ``attachmentIds``; the service checks it, so the
    error names the field ``draftToken``.
    """

    attachment_ids: list[UUID] = Field(
        default_factory=list, alias="attachmentIds", max_length=MAX_MESSAGE_ATTACHMENTS
    )
    draft_token: str | None = Field(default=None, alias="draftToken", max_length=128)

    @model_validator(mode="after")
    def _body_or_files(self) -> MessageFilesIn:
        body = getattr(self, "body", "")
        if isinstance(body, str) and not body.strip() and not self.attachment_ids:
            raise ValueError("A message needs a text or at least one file.")
        return self
