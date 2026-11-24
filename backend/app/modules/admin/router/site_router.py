"""Admin routes of the site config, the PDF assets, Hilfe & Tickets and the feature switches."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile

from app.deps import require_principal
from app.modules.admin.router.deps import (
    _SITE,
    FeaturesAdmin,
    PdfBrandingServiceDep,
    SiteAdmin,
    SiteServiceDep,
    _enforce_cd_logo_body,
    _errors,
)
from app.modules.admin.schemas import HelpTicketsSettings, PdfAssetOut, SiteConfigOut
from app.modules.files.pdf_branding import PdfSlot
from app.modules.site_config.branding import Branding
from app.modules.site_config.cd_logos import sniff_cd_logo
from app.modules.site_config.features import FeatureSwitches
from app.shared.preview import file_response

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get(
    "/site-config",
    response_model=SiteConfigOut,
    dependencies=[_SITE],
    responses=_errors(401, 403),
)
async def get_site_config(service: SiteServiceDep) -> SiteConfigOut:
    """Read the active branding config and its version."""
    return await service.get()


@router.put(
    "/site-config",
    response_model=SiteConfigOut,
    responses=_errors(400, 401, 403, 422),
)
async def put_site_config(
    payload: Branding, service: SiteServiceDep, principal: SiteAdmin
) -> SiteConfigOut:
    """Save the branding as the new active version (version bump, audited).

    A logo must be an image. Inline SVG is not allowed. An invalid payload gives 422.
    """
    return await service.save(payload, principal.sub)


@router.get(
    "/pdf-assets/{slot}",
    response_model=PdfAssetOut | None,
    dependencies=[_SITE],
    responses=_errors(401, 403, 422),
)
async def get_pdf_asset(slot: PdfSlot, service: PdfBrandingServiceDep) -> PdfAssetOut | None:
    """Read a graphic of the PDF branding, or `null` when the slot is empty.

    `logo` is the export logo (spec 000891), `footer` the footer graphic (spec 000892).
    """
    return await service.get(slot)


@router.put(
    "/pdf-assets/{slot}",
    response_model=PdfAssetOut,
    dependencies=[Depends(_enforce_cd_logo_body)],
    responses=_errors(401, 403, 413, 415, 422, 503),
)
async def put_pdf_asset(
    slot: PdfSlot,
    service: PdfBrandingServiceDep,
    principal: SiteAdmin,
    file: Annotated[UploadFile, File()],
) -> PdfAssetOut:
    """Upload a graphic of the PDF branding.

    The server decides the type from the magic bytes: PNG, JPEG, WebP, SVG or PDF. SVG
    and PDF pass, because these bytes reach the render service and never the browser.
    """
    data = await file.read()
    out, old_key = await service.upload(slot, data, filename=file.filename, actor=principal.sub)
    await service.session.commit()
    await service.remove_object(old_key)
    return out


@router.post(
    "/pdf-assets/{slot}/default",
    response_model=PdfAssetOut,
    responses=_errors(401, 403, 422),
)
async def reset_pdf_asset(
    slot: PdfSlot, service: PdfBrandingServiceDep, principal: SiteAdmin
) -> PdfAssetOut:
    """Set the built-in graphic of the slot again: the STUPA logo or the Skyline."""
    out, old_key = await service.reset(slot, principal.sub)
    await service.session.commit()
    await service.remove_object(old_key)
    return out


@router.delete("/pdf-assets/{slot}", status_code=204, responses=_errors(401, 403, 404, 422))
async def delete_pdf_asset(
    slot: PdfSlot, service: PdfBrandingServiceDep, principal: SiteAdmin
) -> None:
    """Empty the slot; the PDFs then carry no graphic there."""
    key = await service.delete(slot, principal.sub)
    await service.session.commit()
    await service.remove_object(key)


@router.get(
    "/pdf-assets/{slot}/file",
    dependencies=[_SITE],
    responses=_errors(401, 403, 404, 422, 503),
)
async def get_pdf_asset_file(
    slot: PdfSlot,
    service: PdfBrandingServiceDep,
    inline: Annotated[bool, Query()] = False,
) -> Response:
    """Download the upload of the slot, always as an attachment.

    Hardening: the route does not echo the stored type, because a stored SVG would
    render inline in the app origin and run script. ``?inline=true`` gives a PDF or
    raster upload as the sandboxed preview of the file viewer, with the type sniffed
    from the bytes (spec 001083). An SVG stays a download.
    """
    data, name = await service.file_bytes(slot)
    return file_response(
        data,
        name=name,
        mime=sniff_cd_logo(data) or "application/octet-stream",
        inline=inline,
        fallback_mime="application/octet-stream",
    )


@router.get(
    "/help-tickets",
    response_model=HelpTicketsSettings,
    dependencies=[_SITE],
    responses=_errors(401, 403),
)
async def get_help_tickets(service: SiteServiceDep) -> HelpTicketsSettings:
    """Read the help and ticket settings of the active branding."""
    return await service.help_tickets()


@router.put(
    "/help-tickets",
    response_model=HelpTicketsSettings,
    responses=_errors(401, 403, 422),
)
async def put_help_tickets(
    payload: HelpTicketsSettings, service: SiteServiceDep, principal: SiteAdmin
) -> HelpTicketsSettings:
    """Save the help and ticket settings as a new active site-config version.

    A ``wikiUrl`` that is not http(s) or a ``retentionMonths`` out of 1..120 gives
    422. An open branding draft keeps its other changes and takes the new values.
    """
    return await service.put_help_tickets(payload, principal.sub)


@router.get(
    "/features",
    response_model=FeatureSwitches,
    dependencies=[Depends(require_principal("admin.features"))],
    responses=_errors(401, 403),
)
async def get_features(service: SiteServiceDep) -> FeatureSwitches:
    """Read the stored feature switches of the active site configuration."""
    return await service.features()


@router.put(
    "/features",
    response_model=FeatureSwitches,
    responses=_errors(401, 403, 409, 422),
)
async def put_features(
    payload: FeatureSwitches, service: SiteServiceDep, principal: FeaturesAdmin
) -> FeatureSwitches:
    """Save the feature switches as a new active site-config version.

    A switch that goes off while the active flow or an Antragsart uses the feature
    gives 409 ``feature_in_use``; ``errors`` names each use. An unknown feature key
    gives 422.
    """
    saved = await service.put_features(payload, principal.sub)
    await service.session.commit()
    return saved
