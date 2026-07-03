"""API schemas of the protocol module.

Wire form is camelCase (``_CamelModel``); the frontend is built exactly against
``ProtocolOut``: ``markdown`` + ``status`` (draft/rendering/final) +
``pdfUrl``/``sentAt`` after ``finalize`` (``rendering`` = worker renders in the
background).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _CamelModel(BaseModel):
    """camelCase aliases in JSON; fields fillable by name."""

    model_config = ConfigDict(populate_by_name=True)


class ProtocolPatch(_CamelModel):
    """``PATCH /protocols/{id}`` — update the Markdown body (draft)."""

    # Deployment-independent cap (clean 422 instead of nginx-413/pytex cap):
    # 512 kB sits comfortably under the nginx 1 MiB and pytex 4 MiB limits.
    markdown: str = Field(max_length=512_000)


class ProtocolVotesBody(_CamelModel):
    """``POST /protocols/{id}/votes`` — embed votes."""

    vote_ids: list[UUID] = Field(alias="voteIds", min_length=1)


class ProtocolOut(_CamelModel):
    """Meeting minutes (all protocol endpoints return this shape)."""

    id: UUID
    meeting_id: UUID = Field(alias="meetingId")
    markdown: str
    status: Literal["draft", "rendering", "final"]
    # Result link after ``finalize``: short-lived signed MinIO URL, never a
    # direct bucket link. NULL while draft / without storage.
    pdf_url: str | None = Field(default=None, alias="pdfUrl")
    # Redacted public variant — only set when an agenda item is non-public.
    public_pdf_url: str | None = Field(default=None, alias="publicPdfUrl")
    sent_at: datetime | None = Field(default=None, alias="sentAt")
