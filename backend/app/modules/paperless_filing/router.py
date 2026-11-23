"""The routes of the Paperless integration.

`admin_router` (`/admin/paperless`) serves the admin page behind `admin.paperless`: the
connection with its switches, the connection test, the failed filings and the action
`Bestehende Dokumente ablegen` (§F/integrations/paperless/002511, 002526, 002530).
`router` (`/paperless`) serves the entry `In Paperless öffnen` behind `paperless.use`
(§F/integrations/paperless/002524, 002525).

No route here files a document: a write opens jobs, and the worker runs them
(§F/integrations/paperless/002523).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import DbSession, Principal, SettingsDep, require_principal
from app.modules.paperless import filings
from app.modules.paperless.connection import ConnectionService, Part, part_since
from app.modules.paperless.models import PaperlessSettings
from app.modules.paperless.schemas import (
    BackfillOut,
    ConnectionIn,
    ConnectionOut,
    ConnectionTestOut,
    ElementDocumentOut,
    ElementKind,
    FailedFilingOut,
)
from app.modules.paperless_filing.sources import backfill_filings
from app.shared.errors import ProblemDetail

router = APIRouter(prefix="/paperless", tags=["paperless"])
admin_router = APIRouter(prefix="/admin/paperless", tags=["paperless"])

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


def get_connection_service(db: DbSession, settings: SettingsDep) -> ConnectionService:
    """Build the connection service of the request."""
    return ConnectionService(db, settings)


Connection = Annotated[ConnectionService, Depends(get_connection_service)]


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
