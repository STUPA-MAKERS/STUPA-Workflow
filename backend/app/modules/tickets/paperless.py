"""The action `In Paperless ablegen` on a file of a ticket.

A person with the work right in the Bereich and the permission `paperless.use` files a
clean file of a ticket while the Paperless connection is on
(§F/integrations/ticket-mail/002742). The action only opens a job: the worker cron
`process_paperless_filings` uploads the file (§F/integrations/paperless/002523). The
job has the kind `ticket_file`, the ticket as its element and the attachment as its
source, so a file has at most one document.

No function here commits. The router owns the transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.files.models import Attachment
from app.modules.paperless.client import document_url
from app.modules.paperless.filings import NewFiling, open_filings, retry_filing
from app.modules.paperless.models import PaperlessFiling, PaperlessSettings
from app.modules.site_config.features import Feature, feature_on
from app.modules.tickets.models import Ticket, TicketNote
from app.modules.tickets.numbers import format_number
from app.modules.tickets.schemas import TicketPaperless, TicketPaperlessFile
from app.shared.errors import ConflictError, NotFoundError

#: The kind of the filing of a ticket file.
FILING_KIND: Literal["ticket_file"] = "ticket_file"
#: The permission of the action and of the entry `In Paperless öffnen`.
PAPERLESS_USE = "paperless.use"
#: The problem code while the feature or the connection is off.
PAPERLESS_OFF = "paperless_off"
#: The problem code of a file without a clean scan.
FILE_NOT_CLEAN = "file_not_clean"

FileState = Literal["none", "pending", "filed", "failed"]


async def connection_of(session: AsyncSession) -> PaperlessSettings | None:
    """Return the Paperless connection while the feature and the connection are on."""
    if not await feature_on(session, Feature.PAPERLESS):
        return None
    row = await session.get(PaperlessSettings, 1)
    return row if row is not None and row.base_url and row.token else None


async def _files(session: AsyncSession, ticket_id: uuid.UUID) -> Sequence[Attachment]:
    """Return the files of a ticket: of the report and of each message that is not deleted."""
    notes = select(TicketNote.id).where(
        TicketNote.ticket_id == ticket_id, TicketNote.deleted_at.is_(None)
    )
    return (
        await session.scalars(
            select(Attachment)
            .where(or_(Attachment.ticket_id == ticket_id, Attachment.ticket_note_id.in_(notes)))
            .order_by(Attachment.created_at, Attachment.id)
        )
    ).all()


def _is_clean(file: Attachment) -> bool:
    return file.scanned and file.scan_result == "clean"


def _state(filing: PaperlessFiling | None) -> FileState:
    if filing is None:
        return "none"
    return "pending" if filing.state == "uploaded" else filing.state  # type: ignore[return-value]


def _out(
    file: Attachment, filing: PaperlessFiling | None, base_url: str | None
) -> TicketPaperlessFile:
    filed = filing is not None and filing.state == "filed" and filing.document_id is not None
    return TicketPaperlessFile(
        id=file.id,
        filename=file.filename,
        state=_state(filing),
        url=(
            document_url(base_url, filing.document_id)
            if filed and base_url and filing is not None and filing.document_id is not None
            else None
        ),
    )


async def _filings(
    session: AsyncSession, file_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, PaperlessFiling]:
    if not file_ids:
        return {}
    rows = await session.scalars(
        select(PaperlessFiling).where(
            PaperlessFiling.kind == FILING_KIND, PaperlessFiling.source_id.in_(file_ids)
        )
    )
    return {row.source_id: row for row in rows.all()}


async def paperless_of(session: AsyncSession, ticket: Ticket) -> TicketPaperless | None:
    """Return the clean files of a ticket with the state of their filing.

    The answer is None while the feature or the connection is off, and for an anonymized
    ticket, whose files are gone.
    """
    connection = await connection_of(session)
    if connection is None or ticket.anonymized_at is not None:
        return None
    files = [file for file in await _files(session, ticket.id) if _is_clean(file)]
    filings = await _filings(session, [file.id for file in files])
    return TicketPaperless(
        files=tuple(_out(file, filings.get(file.id), connection.base_url) for file in files)
    )


async def file_in_paperless(
    session: AsyncSession, ticket: Ticket, attachment_id: uuid.UUID, *, actor: str
) -> TicketPaperlessFile:
    """Open the job that files one file of a ticket; a failed job starts again.

    Raises:
        ConflictError: The feature or the connection is off (``paperless_off``), or the
            file has no clean scan (``file_not_clean``).
        NotFoundError: The ticket has no such file.
    """
    connection = await connection_of(session)
    if connection is None:
        raise ConflictError("The Paperless connection is off.", code=PAPERLESS_OFF)
    file = next(
        (file for file in await _files(session, ticket.id) if file.id == attachment_id), None
    )
    if file is None:
        raise NotFoundError("The ticket has no such file.")
    if not _is_clean(file):
        raise ConflictError("Only a clean file can be filed.", code=FILE_NOT_CLEAN)
    before = (await _filings(session, [file.id])).get(file.id)
    if before is not None and before.state == "failed":
        await retry_filing(session, before.id, datetime.now(UTC))
        await session.refresh(before)
    elif before is None:
        await open_filings(
            session,
            [
                NewFiling(
                    kind=FILING_KIND,
                    element_id=ticket.id,
                    source_id=file.id,
                    source_at=file.created_at,
                    title=f"{format_number(ticket.number)} – {file.filename}",
                    actor=actor,
                )
            ],
        )
    after = before or (await _filings(session, [file.id])).get(file.id)
    return _out(file, after, connection.base_url)
