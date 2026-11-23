"""Run the job of one filing: upload the file, wait for Paperless, set the link.

A job has two steps. The first builds the file and hands it to Paperless, which answers
with a consume task. The second reads that task until Paperless has made the document,
stores the document number and sets the custom field `Plattform` to the address of the
element (§F/integrations/paperless/002519). A failed step counts as one try; the record
ends the job after the last one (§F/integrations/paperless/002523).

`tag_replaced` gives the tag `Ersetzt` to each document that a newer document replaced
(§F/integrations/paperless/002521). The platform changes only documents of its own
record and deletes none (§F/integrations/paperless/002522).

No function here commits. The worker owns the transaction of each job.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.paperless import filings
from app.modules.paperless.client import PaperlessClient, PaperlessError, Upload
from app.modules.paperless.models import PaperlessFiling
from app.modules.paperless_filing.files import BuildError, FileBuilder

logger = logging.getLogger("app.paperless")

#: The name of the custom field with the address of the element.
LINK_FIELD = "Plattform"

#: The name of the tag of a replaced document.
REPLACED_TAG = "Ersetzt"

Outcome = Literal["skipped", "uploaded", "waiting", "filed", "retry", "failed"]


@dataclass(frozen=True, slots=True)
class FilingRunner:
    """Run filing jobs with one client, bound to one session of the worker."""

    session: AsyncSession
    client: PaperlessClient
    builder: FileBuilder

    async def run(self, filing_id: UUID, now: datetime) -> Outcome:
        """Run the next step of one job.

        A job that is not due, or that another worker holds, is skipped.
        """
        filing = await filings.lock_due(self.session, filing_id, now)
        if filing is None:
            return "skipped"
        try:
            if filing.state == "pending":
                return await self._upload(filing, now)
            return await self._finish(filing, now)
        except BuildError as exc:
            return await self._failure(filing, exc.code, now, final=exc.final)
        except PaperlessError as exc:
            return await self._failure(filing, exc.code, now, final=False)

    async def _failure(
        self, filing: PaperlessFiling, error: str, now: datetime, *, final: bool
    ) -> Outcome:
        last = await filings.mark_failure(self.session, filing, error=error, now=now, final=final)
        logger.warning(
            "paperless filing %s failed (kind=%s, try=%s, cause=%s, last=%s)",
            filing.id,
            filing.kind,
            filing.attempts + 1,
            error,
            last,
        )
        return "failed" if last else "retry"

    async def _upload(self, filing: PaperlessFiling, now: datetime) -> Outcome:
        """Build the file and hand it to Paperless."""
        prepared = await self.builder.build(filing)
        document_type = await self.client.ensure("document_types", prepared.document_type)
        tags = (await self.client.ensure("tags", prepared.gremium),) if prepared.gremium else ()
        task_id = await self.client.upload(
            Upload(
                filename=prepared.filename,
                content=prepared.content,
                mime=prepared.mime,
                title=prepared.title,
                created=prepared.created,
                document_type=document_type,
                tags=tags,
            )
        )
        await filings.mark_uploaded(
            self.session,
            filing.id,
            task_id=task_id,
            title=prepared.title,
            link=prepared.link,
            now=now,
        )
        return "uploaded"

    async def _document(self, filing: PaperlessFiling, now: datetime) -> int | Outcome:
        """The document number of an uploaded file, or the outcome while it has none."""
        if filing.document_id is not None:
            return filing.document_id
        state = await self.client.task(filing.task_id or "")
        if state.failed:
            return await self._failure(filing, "rejected", now, final=True)
        if state.document_id is None:
            waited = now - (filing.uploaded_at or now)
            if waited > filings.CONSUME_LIMIT:
                return await self._failure(filing, "consume_timeout", now, final=False)
            await filings.mark_waiting(self.session, filing.id, now)
            return "waiting"
        await filings.mark_document(self.session, filing.id, state.document_id)
        return state.document_id

    async def _finish(self, filing: PaperlessFiling, now: datetime) -> Outcome:
        """Read the consume task, then give the document its link."""
        document = await self._document(filing, now)
        if isinstance(document, str):
            return document
        try:
            if filing.link:
                field = await self.client.ensure("custom_fields", LINK_FIELD)
                await self.client.set_link(document, field, filing.link)
        except PaperlessError as exc:
            # The row keeps its document number, so the next try sets only the link.
            await self.session.refresh(filing)
            return await self._failure(filing, exc.code, now, final=False)
        await filings.mark_filed(self.session, filing, document_id=document, now=now)
        return "filed"

    async def tag_replaced(self, now: datetime) -> int:
        """Give each replaced document the tag `Ersetzt`. Return the number of tags set.

        A failure ends the pass and only logs: the next run of the worker tries again.
        """
        replaced = await filings.replaced_documents(self.session)
        if not replaced:
            return 0
        try:
            tag = await self.client.ensure("tags", REPLACED_TAG)
            for filing_id, document_id in replaced:
                await self.client.add_tag(document_id, tag)
                await filings.mark_replaced(self.session, filing_id, now)
        except PaperlessError as exc:
            logger.warning("paperless tag of replaced documents failed (cause=%s)", exc.code)
            return 0
        return len(replaced)
