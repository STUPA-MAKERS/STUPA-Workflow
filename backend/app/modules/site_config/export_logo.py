"""The export logo of the branding: the one logo of every exported PDF (spec 000891).

The Antrag PDF and the PDF of a Haushaltsplan, also as an Anlage of a protocol, carry
this logo and no other. The meeting protocol keeps the design of its Gremium and does
not read it. Without an export logo the render gets empty logo lists, because the render
service puts its built-in default logos in when a list is missing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.site_config.branding import BrandingAsset
from app.modules.site_config.models import SiteConfigVersion

#: The extension of the asset file name per image type. The render service takes the
#: type of an asset from its name.
_EXTENSIONS: Final[dict[str, str]] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}


@dataclass(frozen=True, slots=True)
class ExportLogo:
    """The export logo as a render asset.

    Attributes:
        name: The plain asset file name, for example ``export-logo.png``.
        data: The bytes of the image.
    """

    name: str
    data: bytes


def export_logo_of(raw: object) -> ExportLogo | None:
    """Read a stored export logo; anything that is not a valid inline image gives ``None``."""
    if not isinstance(raw, dict):
        return None
    try:
        asset = BrandingAsset.model_validate(raw)
    except ValidationError:
        return None
    data = asset.inline_bytes()
    ext = _EXTENSIONS.get(asset.mime)
    return ExportLogo(name=f"export-logo.{ext}", data=data) if data and ext else None


async def active_export_logo(session: AsyncSession) -> ExportLogo | None:
    """Return the export logo of the active site configuration, or ``None``.

    The read selects only the export logo, because the branding holds the other inline
    logos too.
    """
    raw = (
        await session.scalars(
            select(SiteConfigVersion.branding["logos"]["export"]).where(
                SiteConfigVersion.active.is_(True)
            )
        )
    ).first()
    return export_logo_of(raw)


def export_render_config(logo: ExportLogo | None, *, footer: bool) -> dict[str, list[str]]:
    """Return the logo keys of a render `config`: the export logo or nothing.

    Both keys are always set, so the render service adds no default logo.

    Args:
        logo: The export logo, or ``None``.
        footer: ``True`` puts the logo in the footer of each page (the Antrag), ``False``
            at the top of the first page (the Haushaltsplan).
    """
    names = [logo.name] if logo else []
    return {"logos": [] if footer else names, "footer_logos": names if footer else []}


def export_render_assets(logo: ExportLogo | None) -> dict[str, bytes] | None:
    """Return the render assets of the export logo, or ``None`` without one."""
    return {logo.name: logo.data} if logo else None
