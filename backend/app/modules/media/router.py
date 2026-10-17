"""Media API router: the images of the Markdown texts.

``POST /api/media/images`` takes one image (multipart field ``file``) from a principal.
An applicant and an anonymous caller get 401. The route caps the body, applies its own
rate limit, cleans the image (``MediaService.upload``) and answers the canonical path.
The rate limit applies to an OAuth token (MCP) too. A token also needs a write scope
that edits a Markdown text with images (``UPLOAD_SCOPES``), else it gets 403: a
``read`` token has no text to put an image into.

``GET /api/media/images/{id}`` streams one image to any session: a principal or a
magic-link applicant. The id is a random uuid4, so it is unguessable on top of the
session check. The image of a protocol that an applicant cannot read is therefore
reachable only with its id, the same as with a share link.

``GET /api/public/protocols/{protocol_id}/images/{image_id}`` streams an image of a
public protocol without login. The protocol must be visible, and its public Markdown
must refer to the image. Everything else gives 404.

Every image answer is inline, ``nosniff`` and carries ``default-src 'none'; sandbox``,
so a browser that opens the URL directly runs nothing. The stored type is one of four
raster types; SVG never reaches the store. The security middleware sets its defaults
with ``setdefault``, so the headers here win.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from fastapi.responses import StreamingResponse

from app.deps import DbSession, SettingsDep, get_current_applicant, get_current_principal
from app.modules.auth.oauth import SCOPES
from app.modules.auth.principal import Applicant, Principal
from app.modules.files.router import _read_capped  # pyright: ignore[reportPrivateUsage]
from app.modules.files.storage import ObjectStorage
from app.modules.media.schemas import MarkdownImageOut
from app.modules.media.service import ImageStream, MediaService
from app.modules.protocol.public import PublicProtocolService
from app.shared.antiabuse import (
    enforce_media_body_cap,
    rate_limit_media_images,
    rate_limit_public_protocol_images,
)
from app.shared.errors import ForbiddenError, NotFoundError, ProblemDetail, UnauthorizedError

router = APIRouter(tags=["media"])
public_router = APIRouter(prefix="/public", tags=["public-protocols"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}

#: The CSP of an image answer: no active content, also when opened directly.
IMAGE_CSP = "default-src 'none'; sandbox"
_PRIVATE_CACHE = "private, max-age=31536000, immutable"
# A public protocol can go private again (hold-back, gremium flag), so a shared cache
# keeps its images for a short time only.
_PUBLIC_CACHE = "public, max-age=300"

#: The OAuth scopes whose texts take images: protocol TOPs, to-do cards and their
#: comments, ticket notes, application comments.
UPLOAD_SCOPES: tuple[str, ...] = (
    "meetings:write",
    "todos:write",
    "tickets:write",
    "applications:write",
)
_UPLOAD_PERMISSIONS: frozenset[str] = frozenset().union(*(SCOPES[s] for s in UPLOAD_SCOPES))


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def get_media_service(session: DbSession, request: Request, settings: SettingsDep) -> MediaService:
    """Wire the service with the optional object storage from the app state."""
    storage: ObjectStorage | None = getattr(request.app.state, "object_storage", None)
    return MediaService(session, storage=storage, max_bytes=settings.markdown_image_max_bytes)


def get_public_protocols(session: DbSession) -> PublicProtocolService:
    """Wire the reads of the public protocols page (visibility only, no storage)."""
    return PublicProtocolService(session)


ServiceDep = Annotated[MediaService, Depends(get_media_service)]
PublicDep = Annotated[PublicProtocolService, Depends(get_public_protocols)]


def _image_response(image: ImageStream, cache_control: str) -> StreamingResponse:
    headers = {
        "Content-Disposition": "inline",
        "Content-Length": str(image.size),
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": IMAGE_CSP,
        "Cache-Control": cache_control,
    }
    return StreamingResponse(image.stream, media_type=image.mime, headers=headers)


@router.post(
    "/media/images",
    response_model=MarkdownImageOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_media_body_cap), Depends(rate_limit_media_images)],
    # 401 no principal, 403 token without a write scope, 413 too large, 415 no
    # accepted image, 429 rate limit, 503 storage off.
    responses=_errors(401, 403, 413, 415, 429, 503),
)
async def upload_image(
    service: ServiceDep,
    principal: Annotated[Principal | None, Depends(get_current_principal)],
    file: Annotated[UploadFile, File()],
) -> MarkdownImageOut:
    """Upload one image for a Markdown text.

    PNG, JPEG, GIF and WEBP only (sniffed, not claimed). The service strips the
    metadata, scales the longest side down to 2400 px and encodes the image again
    in its format. The answer names the canonical path for ``![alt](<url>)``.
    """
    if principal is None:
        raise UnauthorizedError("Authentication required.")
    scope = principal.scope_permissions
    if scope is not None and not (scope & _UPLOAD_PERMISSIONS):
        raise ForbiddenError("The token has no write scope for a text with images.")
    data = await _read_capped(file, service.max_bytes)
    return await service.upload(data)


@router.get(
    "/media/images/{image_id}",
    response_class=StreamingResponse,
    responses=_errors(401, 404, 503),
)
async def get_image(
    image_id: UUID,
    service: ServiceDep,
    principal: Annotated[Principal | None, Depends(get_current_principal)],
    applicant: Annotated[Applicant | None, Depends(get_current_applicant)],
) -> StreamingResponse:
    """Stream one image to a principal or a magic-link applicant."""
    if principal is None and applicant is None:
        raise UnauthorizedError("Authentication required.")
    return _image_response(await service.open(image_id), _PRIVATE_CACHE)


@public_router.get(
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
    return _image_response(await service.open(image_id), _PUBLIC_CACHE)
