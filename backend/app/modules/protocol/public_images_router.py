"""The image route of the public protocols page.

``GET /api/public/protocols/{protocol_id}/images/{image_id}`` streams an image of a
public protocol without login. The protocol must be visible, and its public Markdown
must refer to the image. Everything else gives 404.

The route is in `protocol` and not in `media`, because it reads the protocol, and
`media` imports no higher module (§S/backend/python/000651). The image answer and its
headers are those of `media.router`.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.deps import DbSession
from app.modules.media.router import ServiceDep, image_response
from app.modules.protocol.public import PublicProtocolService
from app.shared.antiabuse import rate_limit_public_protocol_images
from app.shared.errors import NotFoundError, ProblemDetail

router = APIRouter(prefix="/public", tags=["public-protocols"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}
#: A public protocol can go private again (hold-back, gremium flag), so a shared cache
#: keeps its images for a short time only.
PUBLIC_CACHE = "public, max-age=300"


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Document problem+json for the given error status codes."""
    return dict.fromkeys(codes, _PROBLEM)


def get_public_protocols(session: DbSession) -> PublicProtocolService:
    """Wire the reads of the public protocols page (visibility only, no storage)."""
    return PublicProtocolService(session)


PublicDep = Annotated[PublicProtocolService, Depends(get_public_protocols)]


@router.get(
    "/protocols/{protocol_id}/images/{image_id}",
    response_class=StreamingResponse,
    dependencies=[Depends(rate_limit_public_protocol_images)],
    responses=_errors(404, 422, 429, 503),
)
async def get_public_protocol_image(
    protocol_id: UUID,
    image_id: UUID,
    service: ServiceDep,
    protocols: PublicDep,
) -> StreamingResponse:
    """Stream an image of a public protocol without login.

    404 unless the protocol is public and its public Markdown refers to the image.
    """
    if image_id not in await protocols.public_image_ids(protocol_id):
        raise NotFoundError("image not found")
    return image_response(await service.open(image_id), PUBLIC_CACHE)
