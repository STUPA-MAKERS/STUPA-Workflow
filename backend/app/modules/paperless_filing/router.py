"""The routes of the Paperless integration.

`admin_router` (`/admin/paperless`) serves the admin page behind `admin.paperless`: the
connection with its switches, the connection test, the failed filings and the action
`Bestehende Dokumente ablegen` (§F/integrations/paperless/002511, 002526, 002530).
`router` (`/paperless`) serves the entry `In Paperless öffnen` behind `paperless.use`
(§F/integrations/paperless/002524, 002525) and, behind the same permission, the state
and the search of the insert from Paperless (§F/integrations/paperless/002527, 002529,
002534). The copy of a picked document is a route of the protocol
(`protocol.documents_router`), because it needs the write right of the Sitzung.

No route here files a document: a write opens jobs, and the worker runs them
(§F/integrations/paperless/002523).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import DbSession, Principal, require_principal
from app.modules.paperless import filings
from app.modules.paperless.client import PaperlessError
from app.modules.paperless.connection import (
    Connection,
    Part,
    get_connection_service,
    insert_on,
    part_since,
)
from app.modules.paperless.models import PaperlessSettings
from app.modules.paperless.schemas import (
    BackfillOut,
    ConnectionIn,
    ConnectionOut,
    ConnectionTestOut,
    DocumentHitOut,
    ElementDocumentOut,
    ElementKind,
    FailedFilingOut,
    InsertStateOut,
)
from app.modules.paperless_filing.sources import backfill_filings
from app.shared.errors import NotFoundError, ProblemDetail, ServiceUnavailableError

router = APIRouter(prefix="/paperless", tags=["paperless"])
admin_router = APIRouter(prefix="/admin/paperless", tags=["paperless"])

__all__ = ["admin_router", "get_connection_service", "router"]

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}
_ERRORS: dict[int | str, dict[str, Any]] = {401: _PROBLEM, 403: _PROBLEM}

PaperlessAdmin = Annotated[Principal, Depends(require_principal("admin.paperless"))]
PaperlessUser = Annotated[Principal, Depends(require_principal("paperless.use"))]

#: The part of the integration that files the document of each kind of element.
_PART: dict[ElementKind, Part] = {
    "protocol": "protocols",
    "application": "applications",
    "plan": "plans",
}

#: The most rounds of one backfill. Each round opens the jobs of one scan.
_BACKFILL_ROUNDS = 200


@admin_router.get("", responses=_ERRORS)
async def read_paperless_connection(
    _admin: PaperlessAdmin, connection: Connection
) -> ConnectionOut:
    """Read the Paperless connection and its switches, without the token."""
    out = await connection.read()
    await connection.session.commit()
    return out


@admin_router.put("", responses={**_ERRORS, 422: _PROBLEM})
async def save_paperless_connection(
    data: ConnectionIn, admin: PaperlessAdmin, connection: Connection
) -> ConnectionOut:
    """Save the Paperless connection and its switches.

    The host of the address must be in the deploy setting `PAPERLESS_HOST_ALLOWLIST`
    (422 `paperless_host_not_allowed`).
    """
    out = await connection.save(data, actor=admin.sub, now=datetime.now(UTC))
    await connection.session.commit()
    return out


@admin_router.post("/test", responses=_ERRORS)
async def test_paperless_connection(
    _admin: PaperlessAdmin, connection: Connection
) -> ConnectionTestOut:
    """Call Paperless with the stored connection and tell the result."""
    out = await connection.test()
    await connection.session.commit()
    return out


@admin_router.get("/failed-filings", responses=_ERRORS)
async def list_failed_paperless_filings(
    _admin: PaperlessAdmin, db: DbSession
) -> list[FailedFilingOut]:
    """List the filings whose job failed for the last time."""
    return list(await filings.failed_filings(db))


@admin_router.post(
    "/failed-filings/{filing_id}/retry",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_ERRORS, 404: _PROBLEM},
)
async def retry_paperless_filing(
    filing_id: UUID, _admin: PaperlessAdmin, db: DbSession
) -> Response:
    """Start the job of a failed filing again (`Erneut versuchen`)."""
    await filings.retry_filing(db, filing_id, datetime.now(UTC))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _backfill(session: AsyncSession, row: PaperlessSettings, actor: str, rounds: int) -> int:
    """Open the jobs of the elements without a document, one scan per round."""
    opened = await filings.open_filings(session, await backfill_filings(session, row, actor))
    if opened == 0 or rounds <= 1:
        return opened
    return opened + await _backfill(session, row, actor, rounds - 1)


@admin_router.post("/backfill", responses=_ERRORS)
async def backfill_paperless(admin: PaperlessAdmin, connection: Connection) -> BackfillOut:
    """Start a job for each final document that has none (`Bestehende Dokumente ablegen`).

    The action covers only the parts whose switch is on.
    """
    row = await connection.row()
    started = await _backfill(connection.session, row, admin.sub, _BACKFILL_ROUNDS)
    await connection.session.commit()
    return BackfillOut(started=started)


@router.get("/documents/{kind}/{element_id}", responses=_ERRORS)
async def read_paperless_document(
    kind: ElementKind, element_id: UUID, _user: PaperlessUser, connection: Connection
) -> ElementDocumentOut:
    """Read the address of the filed document of an element.

    The answer has no address while the element has no filed document or the part of
    the integration is off (§F/integrations/paperless/002512).
    """
    row = await connection.row()
    on = part_since(row, _PART[kind]) is not None
    out = (
        await filings.element_document(connection.session, kind, element_id)
        if on
        else ElementDocumentOut()
    )
    await connection.session.commit()
    return out


@router.get("/insert", responses=_ERRORS)
async def read_paperless_insert(_user: PaperlessUser, connection: Connection) -> InsertStateOut:
    """Tell whether the part `Aus Paperless einfügen` is on."""
    row = await connection.row()
    await connection.session.commit()
    return InsertStateOut(enabled=insert_on(row))


@router.get("/search", responses={**_ERRORS, 404: _PROBLEM, 503: _PROBLEM})
async def search_paperless(
    _user: PaperlessUser,
    connection: Connection,
    q: Annotated[str, Query(max_length=200)] = "",
) -> list[DocumentHitOut]:
    """Search the documents of Paperless by title and content, at most 20 hits.

    An empty query answers the documents that Paperless added last. The answer is 404
    while the part is off, and 503 `paperless_unavailable` when Paperless does not
    answer within 5 seconds or answers with an error
    (§F/integrations/paperless/002529).
    """
    row = await connection.row()
    client = await connection.client() if insert_on(row) else None
    await connection.session.commit()
    if client is None:
        raise NotFoundError("The insert from Paperless is off.")
    try:
        hits = await client.search(q)
    except PaperlessError as exc:
        raise ServiceUnavailableError(
            "Paperless does not answer.", code="paperless_unavailable"
        ) from exc
    return [
        DocumentHitOut(
            document_id=hit.document_id,
            title=hit.title,
            document_type=hit.document_type,
            created=hit.created,
        )
        for hit in hits
    ]
