"""API schemas of the protocol module.

The wire form is camelCase through `_CamelModel`. The frontend is built
against `ProtocolOut` exactly: `markdown` plus `status`
(draft/rendering/final), plus `pdfUrl` and `sentAt` after `finalize`. The
status `rendering` means the worker still renders in the background.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _CamelModel(BaseModel):
    """Give JSON camelCase aliases and allow filling fields by name."""

    model_config = ConfigDict(populate_by_name=True)


class ProtocolPatch(_CamelModel):
    """`PATCH /protocols/{id}`: update the Markdown body of a draft."""

    # Deployment-independent cap. It returns a clean 422 instead of an
    # nginx 413 or the pytex cap. 512 kB stays under the nginx limit of 1 MiB
    # and the pytex limit of 4 MiB.
    markdown: str = Field(max_length=512_000)


class ProtocolVotesBody(_CamelModel):
    """`POST /protocols/{id}/votes`: embed votes."""

    vote_ids: list[UUID] = Field(alias="voteIds", min_length=1)


class ProtocolOut(_CamelModel):
    """Meeting minutes, the shape that every protocol endpoint returns."""

    id: UUID
    meeting_id: UUID = Field(alias="meetingId")
    markdown: str
    status: Literal["draft", "rendering", "final"]
    # Result link after `finalize`: a short-lived signed MinIO URL, never a
    # direct bucket link. It stays NULL for a draft and without storage.
    pdf_url: str | None = Field(default=None, alias="pdfUrl")
    # Redacted public variant, set only when an agenda item is non-public.
    public_pdf_url: str | None = Field(default=None, alias="publicPdfUrl")
    sent_at: datetime | None = Field(default=None, alias="sentAt")
