"""Pydantic schemas for the pdf API.

``JobOut`` follows the job contract: status + (on success) a short-lived signed result
URL (``resultUrl``), never a direct bucket link. ``error`` is a path-free short code
(no stacktrace leak).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class JobOut(BaseModel):
    """Render-job status (pending/running/done/failed + result link)."""

    id: UUID
    kind: str
    status: str
    applicationId: UUID | None = None
    resultUrl: str | None = None  # signed MinIO URL, only when status="done"
    error: str | None = None
