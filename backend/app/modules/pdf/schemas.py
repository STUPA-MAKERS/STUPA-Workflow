"""Pydantic-Schemas der pdf-API (api.md »pdf«).

``JobOut`` folgt dem dokumentierten Job-Contract: Status + (bei Erfolg) eine
kurzlebige, signierte Ergebnis-URL (``resultUrl``); nie ein direkter Bucket-Link
(security.md §6). ``error`` ist eine pfadfreie Kurzkennung (kein Stacktrace-Leak).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class JobOut(BaseModel):
    """Render-Job-Status (api.md »pdf«: pending/running/done/failed + Ergebnis-Link)."""

    id: UUID
    kind: str
    status: str
    applicationId: UUID | None = None
    resultUrl: str | None = None  # signierte MinIO-URL, nur bei status="done"
    nextcloudPath: str | None = None
    error: str | None = None
