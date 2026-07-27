"""Render pipeline — Markdown → pytex → MinIO.

The worker orchestrates a ``render_job`` in these steps:

1. Set the status to ``running``.
2. Load the application document from the DB.
3. Build the Markdown without the DB.
4. Call pytex ``/render``.
5. Store the PDF in MinIO under ``storage_key``.
6. Set the status to ``done``.

The caller injects the infra dependencies pytex and storage. Without MinIO the job
stays ``pending`` (dev and contract CI) and nothing crashes.

Error discipline: ``error`` holds only a path-free short code. A transient failure
(pytex 5xx or transport, storage) raises ``RenderRetry`` and the worker retries. A
permanent failure (pytex 4xx) sets the job to ``failed`` at once.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.files.storage import ObjectStorage, StorageError
from app.modules.pdf.markdown import build_application_markdown
from app.modules.pdf.models import RenderJob
from app.modules.pdf.pytex_client import PytexClient, PytexError
from app.modules.pdf.service import PdfService

logger = logging.getLogger("app.pdf")


class RenderRetry(RuntimeError):
    """Transient render failure → the worker should retry."""


def _storage_key(application_id: UUID | None, job_id: UUID) -> str:
    """Deterministic MinIO key (own ``pdf/`` prefix, separate from attachments)."""
    app_part = str(application_id) if application_id is not None else "unknown"
    return f"pdf/{app_part}/{job_id}.pdf"


@dataclass(slots=True)
class RenderPipeline:
    """Render a ``render_job`` end-to-end. The worker wiring injects the dependencies."""

    sessionmaker: async_sessionmaker[AsyncSession]
    pytex: PytexClient
    storage: ObjectStorage | None

    async def run(self, job_id: UUID) -> str:
        """Render the job.

        Returns:
            One of ``done``, ``failed``, ``skipped`` or ``gone``.

        Raises:
            RenderRetry: The failure is transient, so the worker must retry.
        """
        if self.storage is None:
            # Without object storage there is nowhere to put the PDF, so the job stays
            # pending. This happens in dev and contract CI.
            logger.warning("render skipped (job=%s) — object storage not configured", job_id)
            return "skipped"

        async with self.sessionmaker() as session:
            job = await session.get(RenderJob, job_id)
            if job is None:
                logger.info("render target %s gone — skipped", job_id)
                return "gone"
            if job.status == "done":
                return "done"  # idempotent: already rendered
            if job.application_id is None:
                return await self._fail(session, job, "no_application")

            job.status = "running"
            await session.commit()

            try:
                pdf = await self._render(session, job)
            except PytexError as exc:
                if exc.retryable:
                    raise RenderRetry(str(exc)) from exc
                return await self._fail(session, job, "render_error")

            key = _storage_key(job.application_id, job.id)
            try:
                await self.storage.put(key, pdf, "application/pdf")
            except StorageError as exc:
                raise RenderRetry(str(exc)) from exc

            job.storage_key = key
            job.status = "done"
            job.error = None
            job.touch_finished(datetime.now(UTC))
            await session.commit()
            return "done"

    async def _render(self, session: AsyncSession, job: RenderJob) -> bytes:
        assert job.application_id is not None
        doc = await PdfService(session).load_application_doc(job.application_id)
        markdown = build_application_markdown(doc)
        return await self.pytex.render_pdf(markdown, variant=doc.variant)

    async def _fail(self, session: AsyncSession, job: RenderJob, code: str) -> str:
        """Set the job permanently to ``failed`` (path-free short code)."""
        job.status = "failed"
        job.error = code
        job.touch_finished(datetime.now(UTC))
        await session.commit()
        return "failed"

    async def mark_failed(self, job_id: UUID, code: str) -> None:
        """Permanently fail the job after retries are exhausted (worker dead-letter)."""
        async with self.sessionmaker() as session:
            job = await session.get(RenderJob, job_id)
            if job is None:
                return
            job.status = "failed"
            job.error = code
            job.touch_finished(datetime.now(UTC))
            await session.commit()
