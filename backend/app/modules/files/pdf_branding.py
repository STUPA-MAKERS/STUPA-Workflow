"""The PDF branding: the export logo and the footer graphic (specs 000891, 000892).

The export logo is the one logo of the Antrag PDF and of the PDF of a Haushaltsplan,
also as an Anlage of a protocol. The meeting protocol keeps the logos of its Gremium.
The footer graphic is the graphic at the foot of each page of every PDF that has one:
the Antrag and the protocol.

Each slot is a row of ``pdf_asset``. A row names either an object in the storage (an
upload) or a built-in graphic of the render service (``STUPA``, ``Skyline``). No row
means no graphic. The migration seeds the built-in STUPA logo and the Skyline.

The render always gets the logo lists and ``footer_graphic``, because the render
service puts its own defaults in when a key is missing. The bytes go to the render
service only, so SVG and PDF are allowed (the policy of ``site_config.cd_logos``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from sqlalchemy import select

from app.modules.files.storage import StorageError
from app.modules.site_config.models import PdfAsset as PdfAssetRow
from app.shared.errors import ServiceUnavailableError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.files.storage import ObjectStorage

#: A slot of the PDF branding.
PdfSlot = Literal["logo", "footer"]

#: The built-in graphic that the migration seeds, by slot. The render service knows them.
BUILTIN: Final[dict[str, str]] = {"logo": "STUPA", "footer": "Skyline"}

#: The base of the asset file name per slot.
_BASE: Final[dict[str, str]] = {"logo": "export-logo", "footer": "footer-graphic"}

#: The extension of the asset file name per sniffed type. The render service takes the
#: type of an asset from its name.
_EXTENSIONS: Final[dict[str, str]] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/svg+xml": "svg",
    "application/pdf": "pdf",
}


@dataclass(frozen=True, slots=True)
class RenderGraphic:
    """One graphic of the PDF branding as the render service names it.

    Attributes:
        name: The asset file name (``export-logo.svg``) or the built-in name (``STUPA``).
        data: The bytes of an upload, or ``None`` for a built-in graphic.
    """

    name: str
    data: bytes | None = None


@dataclass(frozen=True, slots=True)
class PdfBranding:
    """The export logo and the footer graphic; ``None`` where the slot is empty."""

    logo: RenderGraphic | None = None
    footer: RenderGraphic | None = None


def asset_name(slot: str, mime: str) -> str | None:
    """Return the asset file name for a slot and a sniffed type, or ``None``."""
    ext = _EXTENSIONS.get(mime)
    return f"{_BASE[slot]}.{ext}" if ext else None


async def _graphic(row: PdfAssetRow, storage: ObjectStorage | None) -> RenderGraphic | None:
    if row.builtin is not None:
        return RenderGraphic(row.builtin)
    name = asset_name(row.slot, row.mime or "")
    if name is None or row.object_key is None:
        return None
    if storage is None:
        raise ServiceUnavailableError("Object storage unavailable.")
    try:
        data = await storage.get(row.object_key)
    except StorageError as exc:
        raise ServiceUnavailableError("Could not read the PDF branding.") from exc
    return RenderGraphic(name, data)


async def active_pdf_branding(session: AsyncSession, storage: ObjectStorage | None) -> PdfBranding:
    """Return the export logo and the footer graphic.

    Raises:
        ServiceUnavailableError: An upload is set but the storage is off or cannot read
            it (503), because a PDF without it would look valid.
    """
    rows = {row.slot: row for row in (await session.scalars(select(PdfAssetRow))).all()}
    logo = rows.get("logo")
    footer = rows.get("footer")
    return PdfBranding(
        logo=await _graphic(logo, storage) if logo is not None else None,
        footer=await _graphic(footer, storage) if footer is not None else None,
    )


def export_render_config(branding: PdfBranding, *, footer: bool) -> dict[str, object]:
    """Return the branding keys of a render `config`: the export logo and the graphic.

    Every key is always set, so the render service adds no default.

    Args:
        branding: The PDF branding.
        footer: ``True`` puts the logo in the footer of each page (the Antrag), ``False``
            at the top of the first page (the Haushaltsplan).
    """
    names = [branding.logo.name] if branding.logo else []
    return {
        "logos": [] if footer else names,
        "footer_logos": names if footer else [],
        **footer_render_config(branding),
    }


def footer_render_config(branding: PdfBranding) -> dict[str, object]:
    """Return the `footer_graphic` key: the graphic, or empty for none."""
    return {"footer_graphic": branding.footer.name if branding.footer else ""}


def _assets(*graphics: RenderGraphic | None) -> dict[str, bytes]:
    return {g.name: g.data for g in graphics if g is not None and g.data is not None}


def export_render_assets(branding: PdfBranding) -> dict[str, bytes] | None:
    """Return the uploaded logo and footer graphic as render assets, or ``None``."""
    return _assets(branding.logo, branding.footer) or None


def footer_render_assets(branding: PdfBranding) -> dict[str, bytes]:
    """Return the uploaded footer graphic as a render asset, or nothing."""
    return _assets(branding.footer)
