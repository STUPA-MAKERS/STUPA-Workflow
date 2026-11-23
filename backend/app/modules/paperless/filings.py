"""The record of the filings: the open jobs, the failed list and the filed documents.

A row of `paperless_filing` is the job of one file. `open_filings` adds a row per file
and skips a file that already has one (§F/integrations/paperless/002520). The worker
reads the due rows and writes each result back. A job tries at most `MAX_TRIES` times
(§F/integrations/paperless/002523); after the last failure the row is `failed` and
shows on the admin page until `Erneut versuchen` (§F/integrations/paperless/002526).

No function here commits. The router and the worker own the transaction.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import case, exists, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.paperless.client import document_url
from app.modules.paperless.models import PaperlessFiling, PaperlessSettings
from app.modules.paperless.schemas import (
    ElementDocumentOut,
    ElementKind,
    FailedFilingOut,
    FiledDocumentOut,
    FilingKind,
)
from app.shared.errors import NotFoundError

#: The most tries of one job (§F/integrations/paperless/002523).
MAX_TRIES = 8

#: The most rows that one run of the worker takes.
BATCH = 20

#: The wait before the second try. Each further try waits two times as long.
FIRST_BACKOFF = timedelta(minutes=1)

#: The longest time Paperless has to read an uploaded file.
CONSUME_LIMIT = timedelta(hours=1)

#: The wait between two reads of the consume task.
POLL_INTERVAL = timedelta(seconds=30)

#: The audit target of each kind of filing.
AUDIT_TARGET: dict[str, str] = {
    "protocol": "protocol",
    "protocol_public": "protocol",
    "application": "application",
    "attachment": "application",
    "plan": "budget_plan",
    "ticket_file": "ticket",
}

#: The kinds whose newer document replaces the document before it
#: (§F/integrations/paperless/002521). An attachment is a file of its own and is filed
#: once.
REPLACING_KINDS = frozenset({"protocol", "protocol_public", "application", "plan"})


@dataclass(frozen=True, slots=True)
class NewFiling:
    """One file to file: the data of a new row."""

    kind: FilingKind
    element_id: UUID
    source_id: UUID
    source_at: datetime
    title: str
    application_id: UUID | None = None
    actor: str | None = None


def backoff(attempts: int) -> timedelta:
    """The wait after the failed try number ``attempts``."""
    return FIRST_BACKOFF * (2 ** max(attempts - 1, 0))


async def open_filings(session: AsyncSession, filings: Sequence[NewFiling]) -> int:
    """Add a job for each file that has none. Return the number of new jobs."""
    if not filings:
        return 0
    added = await session.scalars(
        pg_insert(PaperlessFiling)
        .values(
            [
                {
                    "kind": filing.kind,
                    "element_id": filing.element_id,
                    "source_id": filing.source_id,
                    "source_at": filing.source_at,
                    "title": filing.title,
                    "application_id": filing.application_id,
                    "actor": filing.actor,
                }
                for filing in filings
            ]
        )
        .on_conflict_do_nothing(constraint="uq_paperless_filing_source")
        .returning(PaperlessFiling.id)
    )
    return len(added.all())


async def due_filings(
    session: AsyncSession, now: datetime, kinds: Sequence[str]
) -> tuple[UUID, ...]:
    """The open jobs of these kinds whose next try is due, the longest waiting first."""
    return tuple(
        (
            await session.scalars(
                select(PaperlessFiling.id)
                .where(
                    PaperlessFiling.state.in_(("pending", "uploaded")),
                    PaperlessFiling.due_at <= now,
                    PaperlessFiling.kind.in_(kinds),
                )
                .order_by(PaperlessFiling.due_at, PaperlessFiling.kind, PaperlessFiling.id)
                .limit(BATCH)
            )
        ).all()
    )


async def lock_due(session: AsyncSession, filing_id: UUID, now: datetime) -> PaperlessFiling | None:
    """Lock one due job, so two workers never run the same job at once."""
    return await session.scalar(
        select(PaperlessFiling)
        .where(
            PaperlessFiling.id == filing_id,
            PaperlessFiling.state.in_(("pending", "uploaded")),
            PaperlessFiling.due_at <= now,
        )
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )


async def mark_uploaded(
    session: AsyncSession,
    filing_id: UUID,
    *,
    task_id: str,
    title: str,
    link: str,
    now: datetime,
) -> None:
    """Store the consume task of an uploaded file, with its title and its link."""
    await session.execute(
        update(PaperlessFiling)
        .where(PaperlessFiling.id == filing_id)
        .values(
            state="uploaded",
            task_id=task_id,
            title=title,
            link=link,
            uploaded_at=now,
            due_at=now + POLL_INTERVAL,
            last_error=None,
        )
    )


async def mark_waiting(session: AsyncSession, filing_id: UUID, now: datetime) -> None:
    """Keep an uploaded file open until the next read of its consume task."""
    await session.execute(
        update(PaperlessFiling)
        .where(PaperlessFiling.id == filing_id)
        .values(due_at=now + POLL_INTERVAL)
    )


async def mark_document(session: AsyncSession, filing_id: UUID, document_id: int) -> None:
    """Store the document number that Paperless gave an uploaded file."""
    await session.execute(
        update(PaperlessFiling)
        .where(PaperlessFiling.id == filing_id)
        .values(document_id=document_id)
    )


async def mark_filed(
    session: AsyncSession, filing: PaperlessFiling, *, document_id: int, now: datetime
) -> None:
    """Store the document number and write the audit entry of the filing."""
    await session.execute(
        update(PaperlessFiling)
        .where(PaperlessFiling.id == filing.id)
        .values(state="filed", document_id=document_id, filed_at=now, last_error=None)
    )
    await audit_record(
        session,
        actor=filing.actor,
        action=AuditAction.PAPERLESS_FILED,
        target_type=AUDIT_TARGET[filing.kind],
        target_id=str(filing.element_id),
        data={"kind": filing.kind, "documentId": document_id, "filingId": str(filing.id)},
    )


async def mark_failure(
    session: AsyncSession,
    filing: PaperlessFiling,
    *,
    error: str,
    now: datetime,
    final: bool = False,
) -> bool:
    """Count a failed try. Return whether the job failed for the last time.

    ``final`` ends the job at once, for a failure that a new try cannot repair. A job
    with a document number keeps it and tries only the rest again. Each other job
    starts again with a new upload, because its consume task is over.
    """
    attempts = filing.attempts + 1
    last = final or attempts >= MAX_TRIES
    again = "uploaded" if filing.document_id is not None else "pending"
    await session.execute(
        update(PaperlessFiling)
        .where(PaperlessFiling.id == filing.id)
        .values(
            state="failed" if last else again,
            attempts=attempts,
            last_error=error,
            failed_at=now if last else None,
            due_at=now + backoff(attempts),
            **({} if filing.document_id is not None else {"task_id": None, "uploaded_at": None}),
        )
    )
    return last


async def replaced_documents(session: AsyncSession) -> tuple[tuple[UUID, int], ...]:
    """The filed documents that a newer document replaced and that lack the tag `Ersetzt`.

    A document is replaced when the same element has a filed document of the same kind
    from a later event (§F/integrations/paperless/002521). Each entry is the id of the
    filing and the number of its document.
    """
    newer = aliased(PaperlessFiling)
    rows = await session.execute(
        select(PaperlessFiling.id, PaperlessFiling.document_id)
        .where(
            PaperlessFiling.kind.in_(REPLACING_KINDS),
            PaperlessFiling.state == "filed",
            PaperlessFiling.document_id.is_not(None),
            PaperlessFiling.replaced_at.is_(None),
            exists().where(
                newer.kind == PaperlessFiling.kind,
                newer.element_id == PaperlessFiling.element_id,
                newer.state == "filed",
                newer.source_at > PaperlessFiling.source_at,
            ),
        )
        .order_by(PaperlessFiling.source_at, PaperlessFiling.id)
        .limit(BATCH)
    )
    return tuple(
        (filing_id, document_id) for filing_id, document_id in rows if document_id is not None
    )


async def mark_replaced(session: AsyncSession, filing_id: UUID, now: datetime) -> None:
    """Store that a document has the tag `Ersetzt`."""
    await session.execute(
        update(PaperlessFiling).where(PaperlessFiling.id == filing_id).values(replaced_at=now)
    )


async def failed_filings(session: AsyncSession) -> tuple[FailedFilingOut, ...]:
    """The filings whose job failed for the last time, the newest first."""
    rows = (
        await session.scalars(
            select(PaperlessFiling)
            .where(PaperlessFiling.state == "failed")
            .order_by(PaperlessFiling.failed_at.desc(), PaperlessFiling.id)
        )
    ).all()
    return tuple(
        FailedFilingOut(
            id=row.id,
            kind=row.kind,  # type: ignore[arg-type]
            element_id=row.element_id,
            title=row.title,
            failed_at=row.failed_at,
            error=row.last_error,
        )
        for row in rows
    )


async def retry_filing(session: AsyncSession, filing_id: UUID, now: datetime) -> None:
    """Start a failed job again (`Erneut versuchen`).

    Raises:
        NotFoundError: No failed filing has the id.
    """
    changed = await session.scalars(
        update(PaperlessFiling)
        .where(PaperlessFiling.id == filing_id, PaperlessFiling.state == "failed")
        .values(
            state=case((PaperlessFiling.document_id.is_not(None), "uploaded"), else_="pending"),
            attempts=0,
            due_at=now,
            failed_at=None,
            last_error=None,
        )
        .returning(PaperlessFiling.id)
    )
    if changed.first() is None:
        raise NotFoundError("Unknown failed filing.")


async def _base_url(session: AsyncSession) -> str | None:
    return await session.scalar(select(PaperlessSettings.base_url).where(PaperlessSettings.id == 1))


async def element_document(
    session: AsyncSession, kind: ElementKind, element_id: UUID
) -> ElementDocumentOut:
    """The newest filed document of an element, for the entry `In Paperless öffnen`.

    A protocol links to its internal PDF and an Antrag to its PDF, not to an
    attachment.
    """
    base_url = await _base_url(session)
    document_id = await session.scalar(
        select(PaperlessFiling.document_id)
        .where(
            PaperlessFiling.kind == kind,
            PaperlessFiling.element_id == element_id,
            PaperlessFiling.state == "filed",
        )
        .order_by(PaperlessFiling.source_at.desc())
        .limit(1)
    )
    if base_url is None or document_id is None:
        return ElementDocumentOut()
    return ElementDocumentOut(url=document_url(base_url, document_id), document_id=document_id)


async def filed_for_applications(
    session: AsyncSession, application_ids: Sequence[UUID]
) -> dict[UUID, tuple[FiledDocumentOut, ...]]:
    """The filed documents of each Antrag: its PDFs and its attachments.

    An erasure and the data export name them (§F/administration/privacy/002532,
    §F/administration/privacy/002533).
    """
    if not application_ids:
        return {}
    base_url = await _base_url(session)
    rows = (
        await session.scalars(
            select(PaperlessFiling)
            .where(
                PaperlessFiling.application_id.in_(application_ids),
                PaperlessFiling.state == "filed",
            )
            .order_by(PaperlessFiling.filed_at, PaperlessFiling.id)
        )
    ).all()
    return {
        application_id: tuple(
            FiledDocumentOut(
                document_id=row.document_id,
                title=row.title,
                url=document_url(base_url, row.document_id) if base_url else None,
                filed_at=row.filed_at,
            )
            for row in rows
            if row.application_id == application_id and row.document_id is not None
        )
        for application_id in {row.application_id for row in rows if row.application_id}
    }
