"""The export logo of the branding: the one logo of every exported PDF (spec 000891).

The Antrag PDF and the PDF of a Haushaltsplan, also as an Anlage of a protocol, carry
this logo and no other. The meeting protocol keeps the design of its Gremium and does
not read it. Without an export logo the render gets empty logo lists, because the render
service puts its built-in default logos in when a list is missing.

The admin uploads the logo on the branding page (``admin.service.export_logo``). The row
``export_logo`` names the object in the storage; the bytes go to the render service only,
so SVG and PDF are allowed (the policy of ``site_config.cd_logos``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from sqlalchemy import select

from app.modules.files.storage import StorageError
from app.modules.site_config.models import ExportLogo as ExportLogoRow
from app.shared.errors import ServiceUnavailableError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.files.storage import ObjectStorage

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
class ExportLogo:
    """The export logo as a render asset.

    Attributes:
        name: The plain asset file name, for example ``export-logo.svg``.
        data: The bytes of the file.
    """

    name: str
    data: bytes


def asset_name(mime: str) -> str | None:
    """Return the asset file name for a sniffed type, or ``None`` for any other type."""
    ext = _EXTENSIONS.get(mime)
    return f"export-logo.{ext}" if ext else None


async def active_export_logo(
    session: AsyncSession, storage: ObjectStorage | None
) -> ExportLogo | None:
    """Return the export logo, or ``None`` when there is none.

    Raises:
        ServiceUnavailableError: A logo is set but the storage is off or cannot read
            it (503), because a PDF without the logo would look valid.
    """
    row = (await session.scalars(select(ExportLogoRow))).first()
    name = asset_name(row.mime) if row is not None else None
    if row is None or name is None:
        return None
    if storage is None:
        raise ServiceUnavailableError("Object storage unavailable.")
    try:
        data = await storage.get(row.object_key)
    except StorageError as exc:
        raise ServiceUnavailableError("Could not read the export logo.") from exc
    return ExportLogo(name=name, data=data)


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
