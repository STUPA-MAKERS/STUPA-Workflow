"""The upload of a PDF that a protocol text embeds (spec 000862).

``POST /api/meetings/{meeting_id}/documents`` takes one PDF (multipart field ``file``)
for the protocol of a meeting. Only a person who can write that protocol may upload
(`ProtocolService.authorize_write_meeting`), because only that person can put the
reference into a text. The route caps the body, applies its own rate limit and lets
`MediaService.upload_document` scan, check and store the file (spec 000869). The route
commits, so the service never does (000474).

``GET /api/media/documents/{id}`` streams one embedded PDF, as a download or with
``?inline=true`` as the framable preview of the file viewer, and ``GET
/api/media/documents/{id}/info`` answers its name and page count. Both answer only a
person who can read the Sitzung of the PDF (§NF/security/files/000979). An applicant
session, a person without that right and a PDF without a Sitzung get 404, the same
answer as for an unknown id, so the answer does not tell that the PDF exists. The id
alone is no protection: a text, a mail or a browser history can show it.

The routes are in `protocol` and not in `media`, because they read the meeting, and
`media` imports no higher module (§S/backend/python/000651).

The upload answers 401 without a principal, 403 without write access, 404 for an
unknown meeting, 413 for a file that is too large or has too many pages, 415 for no
readable, unencrypted PDF, 429 at the rate limit and 503 when the storage is off.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import StreamingResponse

from app.deps import DbSession, get_current_applicant, get_current_principal
from app.modules.auth.principal import Applicant, Principal
from app.modules.files.body import read_capped
from app.modules.media.router import ServiceDep as MediaDep
from app.modules.media.router import document_response
from app.modules.media.schemas import MarkdownDocumentOut
from app.modules.protocol.router import PrincipalDep, ServiceDep
from app.shared.antiabuse import enforce_document_body_cap, rate_limit_media_documents
from app.shared.errors import ForbiddenError, NotFoundError, ProblemDetail, UnauthorizedError

router = APIRouter(tags=["protocol"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return dict.fromkeys(codes, _PROBLEM)


@router.post(
    "/meetings/{meeting_id}/documents",
    response_model=MarkdownDocumentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_document_body_cap), Depends(rate_limit_media_documents)],
    responses=_errors(401, 403, 404, 413, 415, 429, 503),
)
async def upload_document(
    meeting_id: UUID,
    protocols: ServiceDep,
    media: MediaDep,
    principal: PrincipalDep,
    session: DbSession,
    file: Annotated[UploadFile, File()],
) -> MarkdownDocumentOut:
    """Upload one PDF for a text of the protocol of the meeting.

    PDF only (sniffed, not claimed), unencrypted, at most 20 MiB and 100 pages. The
    answer names the canonical path for ``[<name>](<url>)`` and the page count.
    """
    await protocols.authorize_write_meeting(meeting_id, principal)
    data = await read_capped(file, media.max_document_bytes)
    out = await media.upload_document(data, file.filename, meeting_id)
    await session.commit()
    return out


#: A PDF never changes under its id, so the browser of the reader keeps it.
_PRIVATE_CACHE = "private, max-age=31536000, immutable"


async def require_document_reader(
    document_id: UUID,
    protocols: ServiceDep,
    media: MediaDep,
    principal: Annotated[Principal | None, Depends(get_current_principal)],
    applicant: Annotated[Applicant | None, Depends(get_current_applicant)],
) -> UUID:
    """Let only a reader of the Sitzung of the PDF pass (§NF/security/files/000979).

    Raises:
        UnauthorizedError: The request has no session (401).
        NotFoundError: The id is unknown, the PDF has no Sitzung, or the session cannot
            read the Sitzung (404). An applicant session never can.
    """
    if principal is None and applicant is None:
        raise UnauthorizedError("Authentication required.")
    meeting_id = await media.document_meeting(document_id)
    if principal is None or meeting_id is None:
        raise NotFoundError("document not found")
    try:
        await protocols.authorize_read_meeting(meeting_id, principal)
    except (ForbiddenError, NotFoundError) as exc:
        raise NotFoundError("document not found") from exc
    return document_id


ReadableDocument = Annotated[UUID, Depends(require_document_reader)]


@router.get(
    "/media/documents/{document_id}",
    response_class=StreamingResponse,
    responses=_errors(401, 404, 503),
)
async def get_document(
    document_id: ReadableDocument,
    media: MediaDep,
    inline: Annotated[bool, Query()] = False,
) -> StreamingResponse:
    """Stream one embedded PDF to a person who can read its Sitzung.

    ``?inline=true`` answers the framable preview of the file viewer, else a download.
    """
    document = await media.open_document(document_id)
    return document_response(document, inline=inline, cache_control=_PRIVATE_CACHE)


@router.get(
    "/media/documents/{document_id}/info",
    response_model=MarkdownDocumentOut,
    responses=_errors(401, 404),
)
async def get_document_info(document_id: ReadableDocument, media: MediaDep) -> MarkdownDocumentOut:
    """Return the file name, size and page count of one embedded PDF for its badge."""
    return await media.document_info(document_id)
