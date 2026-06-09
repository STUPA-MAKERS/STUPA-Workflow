"""Render-Pipeline (T-20, flows §6) — Markdown → pytex → MinIO.

Worker-seitige Orchestrierung eines ``render_job``: Status auf ``running`` setzen, das
Antrags-Dokument laden (DB), Markdown bauen (DB-frei), pytex ``/render`` rufen, das PDF
in MinIO ablegen (``storage_key``), dann ``done``. Die Infra-Abhängigkeiten
(pytex/Storage) werden injiziert — fehlt MinIO, bleibt der Job ``pending``
(DEV/Contract-CI, kein Crash).

Fehler-Disziplin (security.md §2): ``error`` trägt nur eine **pfadfreie Kurzkennung**.
Transiente Fehler (pytex 5xx/Transport, Storage) → :class:`RenderRetry`
(Worker-Retry); dauerhafte (pytex 4xx) → Job sofort ``failed``.
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
    """Transienter Render-Fehler → Worker soll erneut versuchen."""


def _storage_key(application_id: UUID | None, job_id: UUID) -> str:
    """Deterministischer MinIO-Key (eigener ``pdf/``-Präfix, getrennt von Anhängen)."""
    app_part = str(application_id) if application_id is not None else "unknown"
    return f"pdf/{app_part}/{job_id}.pdf"


@dataclass(slots=True)
class RenderPipeline:
    """Render einen ``render_job`` end-to-end. Deps werden injiziert (Worker-Wiring)."""

    sessionmaker: async_sessionmaker[AsyncSession]
    pytex: PytexClient
    storage: ObjectStorage | None

    async def run(self, job_id: UUID) -> str:
        """Job rendern. Rückgabe: done/failed/skipped/gone. Transient → ``RenderRetry``."""
        if self.storage is None:
            # Ohne Object-Storage gibt es keinen Ablageort → Job bleibt pending (DEV).
            logger.warning("render skipped (job=%s) — object storage not configured", job_id)
            return "skipped"

        async with self.sessionmaker() as session:
            job = await session.get(RenderJob, job_id)
            if job is None:
                logger.info("render target %s gone — skipped", job_id)
                return "gone"
            if job.status == "done":
                return "done"  # idempotent: bereits gerendert
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
        """Job dauerhaft auf ``failed`` setzen (pfadfreie Kurzkennung)."""
        job.status = "failed"
        job.error = code
        job.touch_finished(datetime.now(UTC))
        await session.commit()
        return "failed"

    async def mark_failed(self, job_id: UUID, code: str) -> None:
        """Job nach erschöpften Retries dauerhaft auf ``failed`` setzen (Worker-Dead-Pfad)."""
        async with self.sessionmaker() as session:
            job = await session.get(RenderJob, job_id)
            if job is None:
                return
            job.status = "failed"
            job.error = code
            job.touch_finished(datetime.now(UTC))
            await session.commit()
