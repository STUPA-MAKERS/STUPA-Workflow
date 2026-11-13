"""The upload of a PDF that a protocol text embeds (spec 000862).

``POST /api/meetings/{meeting_id}/documents`` takes one PDF (multipart field ``file``)
for the protocol of a meeting. Only a person who can write that protocol may upload
(`ProtocolService.authorize_write_meeting`), because only that person can put the
reference into a text. The route caps the body, applies its own rate limit and lets
`MediaService.upload_document` scan, check and store the file (spec 000869).

The route is in `protocol` and not in `media`, because it reads the meeting, and
`media` imports no higher module (§S/backend/python/000651). The download and the
info route of a PDF are in `media.router`.

The upload answers 401 without a principal, 403 without write access, 404 for an
unknown meeting, 413 for a file that is too large or has too many pages, 415 for no
readable, unencrypted PDF, 429 at the rate limit and 503 when the storage is off.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile, status

from app.modules.files.body import read_capped
from app.modules.media.router import ServiceDep as MediaDep
from app.modules.media.schemas import MarkdownDocumentOut
from app.modules.protocol.router import PrincipalDep, ServiceDep
from app.shared.antiabuse import enforce_document_body_cap, rate_limit_media_documents
from app.shared.errors import ProblemDetail

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
    file: Annotated[UploadFile, File()],
) -> MarkdownDocumentOut:
    """Upload one PDF for a text of the protocol of the meeting.

    PDF only (sniffed, not claimed), unencrypted, at most 20 MiB and 100 pages. The
    answer names the canonical path for ``[<name>](<url>)`` and the page count.
    """
    await protocols.authorize_write_meeting(meeting_id, principal)
    data = await read_capped(file, media.max_document_bytes)
    return await media.upload_document(data, file.filename)
