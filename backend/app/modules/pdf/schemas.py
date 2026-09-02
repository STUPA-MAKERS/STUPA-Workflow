"""Pydantic schemas for the pdf API.

``JobOut`` follows the job contract: status + (on success) an app-relative download
route (``resultUrl``), never a bucket link. ``error`` is a path-free short code
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
    resultUrl: str | None = None  # /api/jobs/{id}/download, only when status="done"
    error: str | None = None
