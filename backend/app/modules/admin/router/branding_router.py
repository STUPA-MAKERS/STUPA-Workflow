"""Public auth-free routes of the branding: site config, manifest, page head, icons."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.deps import SettingsDep
from app.modules.admin.router.deps import SiteServiceDep
from app.modules.admin.schemas import PublicSiteConfigOut
from app.modules.admin.site_config_service import ManifestScheme
from app.modules.site_config.brand_images import (
    ICON_SIZES,
    MASKABLE_SIZES,
    IconPurpose,
    favicon_file,
    icon_png,
    preview_png,
)
from app.shared.errors import NotFoundError

public_router = APIRouter(tags=["admin"])


@public_router.get("/site-config", response_model=PublicSiteConfigOut)
async def get_public_site_config(
    service: SiteServiceDep, response: Response
) -> PublicSiteConfigOut:
    """Read the active branding config without auth (logo URLs, footer, texts)."""
    response.headers["Cache-Control"] = "public, max-age=300"
    return await service.public()


@public_router.get("/manifest.webmanifest", include_in_schema=False)
async def get_manifest(
    service: SiteServiceDep,
    scheme: Annotated[ManifestScheme, Query()] = "light",
) -> Response:
    """Serve the PWA manifest from the active branding (application/manifest+json).

    The route is auth-free. The edge proxy maps the browser-linked
    ``/manifest.webmanifest`` here, so name and short_name follow the configured app
    name. ``scheme=dark`` gives the dark bar colours; the frontend links it while the
    dark theme is in effect. ``scheme=contrast`` gives black bars for "Hoher Kontrast".
    """
    import json

    body = json.dumps(await service.manifest(scheme), ensure_ascii=False)
    return Response(
        content=body,
        media_type="application/manifest+json",
        headers={"Cache-Control": "public, max-age=300"},
    )


#: The cache time of the branded head and images. A link carries ``?v=<version>``, so a
#: save shows at once on the next page load; the 5 minutes cover a bare URL.
_BRAND_CACHE = "public, max-age=300"


#: The file names of the app icon route: ``icon-<n>x<n>.png`` and
#: ``icon-maskable-<n>x<n>.png`` for the sizes of ``brand_images``.
_ICON_NAMES: dict[str, tuple[int, IconPurpose]] = {
    **{f"icon-{n}x{n}.png": (n, "any") for n in ICON_SIZES},
    **{f"icon-maskable-{n}x{n}.png": (n, "maskable") for n in MASKABLE_SIZES},
}


@public_router.get("/page-head", include_in_schema=False)
async def get_page_head(service: SiteServiceDep, settings: SettingsDep) -> Response:
    """Serve the branded tags of the page head as an HTML fragment.

    The web server includes the fragment into ``index.html`` with an SSI subrequest, so a
    link preview reads the name, the description and the image of the active branding
    (§ F/administration/admin/001090). The route is auth-free like the manifest.
    """
    return Response(
        content=await service.page_head(settings.public_base_url),
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-cache"},
    )


def _png_response(data: bytes | None) -> Response:
    if data is None:
        raise NotFoundError("Kein Bild im Branding.", code="branding_image_missing")
    return Response(content=data, media_type="image/png", headers={"Cache-Control": _BRAND_CACHE})


@public_router.get("/branding/preview.png", include_in_schema=False)
async def get_branding_preview(service: SiteServiceDep) -> Response:
    """Serve the link preview image: the Bildmarke, else the Wortmarke, on a square.

    Answers 404 without an inline mark; the page head then links the built-in icon.
    """
    branding, _ = await service.branding_and_version()
    return _png_response(await asyncio.to_thread(preview_png, branding))


@public_router.get("/branding/icons/{name}", include_in_schema=False)
async def get_branding_icon(name: str, service: SiteServiceDep) -> Response:
    """Serve an app icon from the Bildmarke (§ F/administration/admin/001092).

    Answers 404 for an unknown file name or without an inline Bildmarke.
    """
    size = _ICON_NAMES.get(name)
    if size is None:
        raise NotFoundError("Unbekanntes Icon.", code="branding_image_missing")
    branding, _ = await service.branding_and_version()
    return _png_response(await asyncio.to_thread(icon_png, branding, *size))


@public_router.get("/branding/favicon", include_in_schema=False)
async def get_branding_favicon(service: SiteServiceDep) -> Response:
    """Serve the uploaded favicon as stored; 404 without an inline one."""
    branding, _ = await service.branding_and_version()
    favicon = favicon_file(branding)
    if favicon is None:
        raise NotFoundError("Kein Favicon im Branding.", code="branding_image_missing")
    return Response(
        content=favicon.data,
        media_type=favicon.mime,
        headers={"Cache-Control": _BRAND_CACHE, "X-Content-Type-Options": "nosniff"},
    )
