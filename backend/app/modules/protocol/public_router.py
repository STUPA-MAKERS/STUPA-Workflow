"""Public routes of the protocols page, without login.

The routes serve the public version of the final protocols of the gremien with
`protocols_public`. Every route is read-only, has a rate limit per IP, and
answers 404 for anything that is not public (fail closed). The security
middleware adds `X-Robots-Tag: noindex` to every answer under `/api/public/`.

There is no public meeting route here, by design: a meeting is public only as
the title and the date of a final protocol.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.deps import DbSession
from app.modules.files.storage import ObjectStorage
from app.modules.protocol.public import (
    SEMESTER_PATTERN,
    PublicFilter,
    PublicGremiumOut,
    PublicProtocolDetail,
    PublicProtocolPage,
    PublicProtocolService,
    PublicSemesterOut,
)
from app.shared.antiabuse import rate_limit_public_protocol_pdf, rate_limit_public_protocols
from app.shared.errors import ProblemDetail

router = APIRouter(prefix="/public", tags=["public-protocols"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}
_READ_LIMIT = Depends(rate_limit_public_protocols)
_PDF_LIMIT = Depends(rate_limit_public_protocol_pdf)

DEFAULT_LIMIT = 20
MAX_LIMIT = 50


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def get_public_protocol_service(session: DbSession, request: Request) -> PublicProtocolService:
    storage: ObjectStorage | None = getattr(request.app.state, "object_storage", None)
    return PublicProtocolService(session, storage=storage)


ServiceDep = Annotated[PublicProtocolService, Depends(get_public_protocol_service)]
GremiumQuery = Annotated[list[UUID] | None, Query(alias="gremium", max_length=50)]
SearchQuery = Annotated[str | None, Query(min_length=1, max_length=100)]


def _filter(
    gremium: list[UUID] | None,
    semester: str | None = None,
    year: int | None = None,
    q: str | None = None,
) -> PublicFilter:
    text = q.strip() if q else None
    return PublicFilter(
        gremium_ids=tuple(gremium or ()),
        semester=semester,
        year=year,
        q=text or None,
    )


@router.get(
    "/gremien",
    response_model=list[PublicGremiumOut],
    dependencies=[_READ_LIMIT],
    responses=_errors(429),
)
async def list_public_gremien(service: ServiceDep) -> list[PublicGremiumOut]:
    """List the gremien that publish their protocols and have at least one.

    The answer holds the name, the slug and the number of public protocols. It
    never holds members, roles, the quorum or the mail lists.
    """
    return await service.list_gremien()


@router.get(
    "/protocols",
    response_model=PublicProtocolPage,
    dependencies=[_READ_LIMIT],
    responses=_errors(422, 429),
)
async def list_public_protocols(
    service: ServiceDep,
    gremium: GremiumQuery = None,
    semester: Annotated[str | None, Query(pattern=SEMESTER_PATTERN)] = None,
    year: Annotated[int | None, Query(ge=1900, le=2999)] = None,
    q: SearchQuery = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> PublicProtocolPage:
    """List the public protocols, newest meeting first.

    Filters: one or more gremien (`gremium`, repeatable), a semester (`ws-2026` is
    the winter semester 2026/27, `ss-2026` the summer semester 2026), a calendar
    year, and a search text over the meeting title and the public TOP text.
    """
    return await service.list_protocols(
        _filter(gremium, semester, year, q), limit=limit, offset=offset
    )


@router.get(
    "/protocols/semesters",
    response_model=list[PublicSemesterOut],
    dependencies=[_READ_LIMIT],
    responses=_errors(422, 429),
)
async def list_public_semesters(
    service: ServiceDep,
    gremium: GremiumQuery = None,
    q: SearchQuery = None,
) -> list[PublicSemesterOut]:
    """Count the public protocols per semester, newest semester first."""
    return await service.list_semesters(_filter(gremium, q=q))


@router.get(
    "/protocols/{protocol_id}",
    response_model=PublicProtocolDetail,
    dependencies=[_READ_LIMIT],
    responses=_errors(404, 422, 429),
)
async def get_public_protocol(protocol_id: UUID, service: ServiceDep) -> PublicProtocolDetail:
    """Return the public version of one protocol.

    404 for a protocol that is missing, not final, held back, or of a gremium
    that does not publish its protocols.
    """
    return await service.get_protocol(protocol_id)


@router.get(
    "/protocols/{protocol_id}/pdf",
    response_class=Response,
    dependencies=[_PDF_LIMIT],
    responses=_errors(404, 422, 429, 503),
)
async def get_public_protocol_pdf(protocol_id: UUID, service: ServiceDep) -> Response:
    """Stream the public PDF of one protocol through the API.

    The bytes come from the object storage server-side, never from a presigned
    bucket URL. The internal PDF is never served here.
    """
    data, name = await service.get_pdf(protocol_id)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
