"""API-Schemata des Protokoll-Moduls (T-22, api.md »protocol«).

Wire-Form ist camelCase (T-12 ``_CamelModel``); das FE (T-33/#51) ist exakt gegen
``ProtocolOut`` gebaut: ``markdown`` + ``status`` (draft/final) + ``pdfUrl``/``sentAt``
nach ``finalize``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _CamelModel(BaseModel):
    """camelCase-Aliase im JSON; Felder per Name befüllbar."""

    model_config = ConfigDict(populate_by_name=True)


class ProtocolPatch(_CamelModel):
    """``PATCH /protocols/{id}`` — Markdown-Body aktualisieren (Entwurf)."""

    markdown: str


class ProtocolVotesBody(_CamelModel):
    """``POST /protocols/{id}/votes`` — Abstimmungen einbetten."""

    vote_ids: list[UUID] = Field(alias="voteIds", min_length=1)


class ProtocolOut(_CamelModel):
    """Sitzungsprotokoll (alle Protokoll-Endpunkte liefern diese Form)."""

    id: UUID
    meeting_id: UUID = Field(alias="meetingId")
    markdown: str
    status: Literal["draft", "final"]
    # Ergebnis-Link nach ``finalize`` (kurzlebige, signierte MinIO-URL; nie ein
    # direkter Bucket-Link — security.md §6). NULL solange Entwurf / ohne Storage.
    pdf_url: str | None = Field(default=None, alias="pdfUrl")
    sent_at: datetime | None = Field(default=None, alias="sentAt")
