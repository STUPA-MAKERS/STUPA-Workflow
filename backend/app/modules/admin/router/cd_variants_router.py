"""Admin routes of the corporate-design variants and their logos, and the Gremium logo."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Query, Response, UploadFile

from app.deps import DbSession, Principal, require_principal
from app.modules.admin.router.deps import (
    _CD_VARIANT_OPTIONS,
    _CD_VARIANTS,
    CdVariantsAdmin,
    CdVariantServiceDep,
    _enforce_cd_logo_body,
    _errors,
)
from app.modules.admin.schemas import (
    CdVariantCreate,
    CdVariantLogoOut,
    CdVariantLogoReorder,
    CdVariantLogoVendoredCreate,
    CdVariantOptionOut,
    CdVariantOut,
    CdVariantUpdate,
)
from app.modules.admin.service import CdVariantService
from app.modules.admin.service.cd_variants import SquareLogoRef
from app.modules.auth.policy import can_view_gremium
from app.modules.site_config.cd_logos import LogoSlot, sniff_cd_logo
from app.shared.errors import NotFoundError
from app.shared.preview import file_response

router = APIRouter(prefix="/admin", tags=["admin"])
authed_router = APIRouter(tags=["gremien"])


@router.get(
    "/cd-variants",
    response_model=list[CdVariantOut],
    dependencies=[_CD_VARIANTS],
    responses=_errors(401, 403),
)
async def list_cd_variants(service: CdVariantServiceDep) -> list[CdVariantOut]:
    """List the CD variants with their title and footer logos."""
    return await service.list_variants()


@router.post(
    "/cd-variants",
    response_model=CdVariantOut,
    status_code=201,
    responses=_errors(400, 401, 403, 409, 422),
)
async def create_cd_variant(
    payload: CdVariantCreate, service: CdVariantServiceDep, principal: CdVariantsAdmin
) -> CdVariantOut:
    """Create a CD variant. A duplicate key answers 409."""
    return await service.create_variant(payload, principal.sub)


@router.patch(
    "/cd-variants/{variant_id}",
    response_model=CdVariantOut,
    responses=_errors(400, 401, 403, 404, 409, 422),
)
async def update_cd_variant(
    variant_id: UUID,
    payload: CdVariantUpdate,
    service: CdVariantServiceDep,
    principal: CdVariantsAdmin,
) -> CdVariantOut:
    """Patch the name. The key is immutable and a change answers 409."""
    return await service.update_variant(variant_id, payload, principal.sub)


@router.delete(
    "/cd-variants/{variant_id}",
    status_code=204,
    responses=_errors(401, 403, 404, 409),
)
async def delete_cd_variant(
    variant_id: UUID, service: CdVariantServiceDep, principal: CdVariantsAdmin
) -> None:
    """Delete a CD variant. A Gremium that still references it answers 409."""
    await service.delete_variant(variant_id, principal.sub)


@router.post(
    "/cd-variants/{variant_id}/logos",
    response_model=CdVariantLogoOut,
    status_code=201,
    dependencies=[Depends(_enforce_cd_logo_body)],
    responses=_errors(401, 403, 404, 413, 415, 422, 503),
)
async def upload_cd_variant_logo(
    variant_id: UUID,
    service: CdVariantServiceDep,
    principal: CdVariantsAdmin,
    slot: Annotated[LogoSlot, Form()],
    file: Annotated[UploadFile, File()],
) -> CdVariantLogoOut:
    """Upload a logo file into the object storage and append it to the slot.

    The server decides the type from the magic bytes. PNG, JPEG, WebP, SVG and
    PDF pass. SVG and PDF pass here, and only here, because these bytes reach
    the render service and never the browser. The slot ``square`` is the
    exception: PNG, JPEG or WebP only, square, at least 256 x 256 px. It replaces
    the square logo that the variant holds already.
    """
    data = await file.read()
    return await service.upload_logo(
        variant_id, data, slot=slot, filename=file.filename, actor=principal.sub
    )


@router.post(
    "/cd-variants/{variant_id}/logos/vendored",
    response_model=CdVariantLogoOut,
    status_code=201,
    responses=_errors(400, 401, 403, 404, 422),
    deprecated=True,
)
async def add_cd_variant_vendored_logo(
    variant_id: UUID,
    payload: CdVariantLogoVendoredCreate,
    service: CdVariantServiceDep,
    principal: CdVariantsAdmin,
) -> CdVariantLogoOut:
    """Append a logo that the render service ships. No upload and no object storage involved.

    Deprecated: the admin UI offers only the upload, and the worker job
    `migrate_builtin_cd_logos` turns a vendored row into an upload at its next
    start. The slot ``square`` answers 422.
    """
    return await service.add_vendored_logo(variant_id, payload, principal.sub)


@router.put(
    "/cd-variants/{variant_id}/logos/order",
    response_model=list[CdVariantLogoOut],
    responses=_errors(400, 401, 403, 404, 422),
)
async def reorder_cd_variant_logos(
    variant_id: UUID,
    payload: CdVariantLogoReorder,
    service: CdVariantServiceDep,
    principal: CdVariantsAdmin,
) -> list[CdVariantLogoOut]:
    """Set the order inside one slot. The list must name every logo of that slot."""
    return await service.reorder_logos(variant_id, payload, principal.sub)


@router.get(
    "/cd-variant-logos/{logo_id}/file",
    dependencies=[_CD_VARIANTS],
    responses=_errors(401, 403, 404, 503),
    response_class=Response,
)
async def get_cd_variant_logo_file(
    logo_id: UUID,
    service: CdVariantServiceDep,
    inline: Annotated[bool, Query()] = False,
) -> Response:
    """Stream an uploaded logo back from the server.

    Hardening: the route does NOT echo the stored ``mime``. A stored SVG would
    otherwise render inline in the app origin and execute script. The route
    therefore forces ``application/octet-stream`` plus ``Content-Disposition:
    attachment``, the same rule as ``get_invoice_file`` in the budget module.
    ``?inline=true`` gives a PDF or raster logo as the sandboxed preview of the file
    viewer, with the type sniffed from the bytes (spec 001083). An SVG stays a download.
    """
    data, name = await service.logo_file_bytes(logo_id)
    return file_response(
        data,
        name=name,
        mime=sniff_cd_logo(data) or "application/octet-stream",
        inline=inline,
        fallback_mime="application/octet-stream",
    )


def _etag_matches(if_none_match: str | None, etag: str) -> bool:
    """Tell if an ``If-None-Match`` header names ``etag`` or the wildcard."""
    if not if_none_match:
        return False
    tags = [tag.strip().removeprefix("W/") for tag in if_none_match.split(",")]
    return "*" in tags or etag in tags


async def _square_logo_response(
    ref: SquareLogoRef, service: CdVariantService, if_none_match: str | None
) -> Response:
    """Answer a square logo inline, or 304 when the client holds the same bytes.

    The type is the sniffed raster type of the row, never SVG (`SquareLogoRef`).
    ``nosniff`` stops the browser from guessing another type, and ``private``
    keeps a shared cache from storing a logo that needs a login.
    """
    headers = {
        "ETag": ref.etag,
        "Cache-Control": "private, max-age=3600",
        "X-Content-Type-Options": "nosniff",
    }
    if _etag_matches(if_none_match, ref.etag):
        return Response(status_code=304, headers=headers)
    data = await service.square_logo_bytes(ref)
    return Response(content=data, media_type=ref.mime, headers=headers)


@router.get(
    "/cd-variant-logos/{logo_id}/square",
    dependencies=[_CD_VARIANTS],
    responses=_errors(401, 403, 404, 503),
    response_class=Response,
)
async def get_cd_variant_square_logo(
    logo_id: UUID,
    service: CdVariantServiceDep,
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    """Stream a square logo inline, for the thumbnail on the admin page.

    Only a square row answers. Any other logo answers 404, because a title or footer
    logo can be an SVG, which must never render in the app origin.
    """
    ref = await service.admin_square_logo(logo_id)
    return await _square_logo_response(ref, service, if_none_match)


@router.delete(
    "/cd-variant-logos/{logo_id}",
    status_code=204,
    responses=_errors(401, 403, 404),
)
async def delete_cd_variant_logo(
    logo_id: UUID, service: CdVariantServiceDep, principal: CdVariantsAdmin
) -> None:
    """Delete a logo entry. An uploaded object goes with it."""
    await service.delete_logo(logo_id, principal.sub)


@authed_router.get(
    "/cd-variants",
    response_model=list[CdVariantOptionOut],
    dependencies=[_CD_VARIANT_OPTIONS],
    responses=_errors(401, 403),
)
async def list_cd_variant_options(service: CdVariantServiceDep) -> list[CdVariantOptionOut]:
    """Slim CD-variant list (id, key, name) as the source of the Gremium dropdown."""
    return await service.list_variant_options()


@authed_router.get(
    "/committees/{gremium_id}/logo",
    responses=_errors(401, 404, 503),
    response_class=Response,
)
async def get_gremium_logo(
    gremium_id: UUID,
    session: DbSession,
    service: CdVariantServiceDep,
    principal: Annotated[Principal, Depends(require_principal())],
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    """Stream the square logo of the CD variant of a Gremium, inline.

    The API streams the bytes itself and never hands out a presigned URL. A
    member of the Gremium, a holder of ``gremium.view_all`` and an admin may read
    it. Everyone else gets 404, the same answer as for a Gremium without a logo,
    so the route does not tell which Gremien exist.
    """
    if not await can_view_gremium(session, principal, gremium_id):
        raise NotFoundError(f"gremium {gremium_id} has no logo")
    ref = await service.gremium_square_logo(gremium_id)
    return await _square_logo_response(ref, service, if_none_match)
