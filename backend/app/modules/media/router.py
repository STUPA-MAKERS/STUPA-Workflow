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
reachable only with its id.

The route of the images of a public protocol is in `protocol.public_images_router`,
because it reads the protocol, and `media` imports no higher module
(§S/backend/python/000651).

Every image answer is inline, ``nosniff`` and carries ``default-src 'none'; sandbox``,
so a browser that opens the URL directly runs nothing. The stored type is one of four
raster types; SVG never reaches the store. The security middleware sets its defaults
with ``setdefault``, so the headers here win.

The upload answers 401 without a principal, 403 for a token without a write scope, 413
for a body that is too large, 415 for no accepted image, 429 at the rate limit and 503
when the storage is off.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from fastapi.responses import StreamingResponse

from app.deps import DbSession, SettingsDep, get_current_applicant, get_current_principal
from app.modules.auth.oauth import SCOPES
from app.modules.auth.principal import Applicant, Principal
from app.modules.files.body import read_capped
from app.modules.files.storage import ObjectStorage
from app.modules.media.schemas import MarkdownImageOut
from app.modules.media.service import ImageStream, MediaService
from app.shared.antiabuse import (
    enforce_media_body_cap,
    rate_limit_media_images,
)
from app.shared.errors import ForbiddenError, ProblemDetail, UnauthorizedError

router = APIRouter(tags=["media"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}

#: The CSP of an image answer: no active content, also when opened directly.
IMAGE_CSP = "default-src 'none'; sandbox"
_PRIVATE_CACHE = "private, max-age=31536000, immutable"

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
    return dict.fromkeys(codes, _PROBLEM)


def get_media_service(session: DbSession, request: Request, settings: SettingsDep) -> MediaService:
    """Wire the service with the optional object storage from the app state."""
    storage: ObjectStorage | None = getattr(request.app.state, "object_storage", None)
    return MediaService(
        session,
        storage=storage,
        max_bytes=settings.markdown_image_max_bytes,
        settings=settings,
    )


ServiceDep = Annotated[MediaService, Depends(get_media_service)]


def image_response(image: ImageStream, cache_control: str) -> StreamingResponse:
    """Build the inline, sandboxed streaming answer of one image."""
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
    data = await read_capped(file, service.max_bytes)
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
    return image_response(await service.open(image_id), _PRIVATE_CACHE)
