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

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _CamelModel(BaseModel):
    """Give JSON camelCase aliases and allow filling fields by name."""

    model_config = ConfigDict(populate_by_name=True)


class ProtocolPatch(_CamelModel):
    """`PATCH /protocols/{id}`: update the Markdown body or the publication.

    `markdown` updates the body of a draft. `publicWithheld` holds back the
    protocol from the public protocols page, or releases it again. It needs the
    right to finalize and works also on a final protocol. The body must carry at
    least one of the two fields.
    """

    # Deployment-independent cap. It returns a clean 422 instead of an
    # nginx 413 or the render cap. 512 kB stays under the nginx limit of 1 MiB
    # and the typst limit of 32 MiB.
    markdown: str | None = Field(default=None, max_length=512_000)
    public_withheld: bool | None = Field(default=None, alias="publicWithheld")

    @model_validator(mode="after")
    def _one_field(self) -> ProtocolPatch:
        if self.markdown is None and self.public_withheld is None:
            raise ValueError("send markdown or publicWithheld")
        return self


class ProtocolFinalizeBody(_CamelModel):
    """`POST /protocols/{id}/finalize`: the optional finalize options."""

    # Hold back this protocol from the public protocols page.
    public_withheld: bool = Field(default=False, alias="publicWithheld")


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
    # The protocol is held back from the public protocols page.
    public_withheld: bool = Field(default=False, alias="publicWithheld")
    # The gremium publishes its final protocols. The editor then shows the notice
    # that the public TOPs become public.
    gremium_protocols_public: bool = Field(default=False, alias="gremiumProtocolsPublic")
