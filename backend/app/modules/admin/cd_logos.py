"""Logo policy of the corporate-design (CD) variants: closed value sets and upload policy.

A logo entry is either a vendored pytex logo name or an uploaded object. The
uploaded bytes reach the LaTeX renderer only, so ``application/pdf`` is allowed
here although site branding refuses it; a route that serves such an object back
MUST force ``Content-Disposition: attachment``. SVG stays out: the renderer
hands it to an unsandboxed, un-timed inkscape/rsvg-convert subprocess, and it is
an XSS vector in the app origin.
"""

from __future__ import annotations

import re
import uuid
from typing import Final, Literal

from app.modules.admin.branding import sniff_raster_image

# Logo names that pytex ships (``pytex_hsrtreport.logos.KNOWN_LOGOS``).
VendoredLogoName = Literal[
    "HSRT",
    "INF",
    "ASTA",
    "STUPA",
    "ECHO",
    "MAKERS",
    "MAKERS-RAlign",
    "MAKERS-Icon",
    "Skyline",
]
VENDORED_LOGO_NAMES: Final[tuple[VendoredLogoName, ...]] = (
    "HSRT",
    "INF",
    "ASTA",
    "STUPA",
    "ECHO",
    "MAKERS",
    "MAKERS-RAlign",
    "MAKERS-Icon",
    "Skyline",
)

LogoSlot = Literal["title", "footer"]
LOGO_SLOTS: Final[tuple[LogoSlot, ...]] = ("title", "footer")

CdBaseVariant = Literal["report", "protocol"]
CD_BASE_VARIANTS: Final[tuple[CdBaseVariant, ...]] = ("report", "protocol")

ALLOWED_CD_LOGO_MIME: Final[frozenset[str]] = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/webp",
        "application/pdf",
    }
)
MAX_CD_LOGO_BYTES: Final[int] = 2 * 1024 * 1024  # 2 MB
# Under the pytex asset budget (16 files, 4 MiB), whose 413 is not retryable.
MAX_CD_LOGOS_PER_VARIANT: Final[int] = 8
MAX_CD_LOGO_TOTAL_BYTES: Final[int] = 3 * 1024 * 1024

# LaTeX picks its image driver by extension, so it must follow the sniffed type.
_MIME_EXTENSION: Final[dict[str, str]] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}

_ASSET_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]")
_ASSET_STEM_MAX: Final[int] = 60


def sniff_cd_logo(data: bytes) -> str | None:
    """Sniff the type of an uploaded CD logo from its magic bytes.

    Returns:
        The sniffed MIME type, or ``None`` when the bytes are not one of the
        accepted types. ICO and SVG are not accepted here.
    """
    raster = sniff_raster_image(data)
    if raster is not None:
        return raster if raster in ALLOWED_CD_LOGO_MIME else None
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def asset_file_name(logo_id: uuid.UUID, file_name: str | None, mime: str) -> str:
    """Build the plain file name under which pytex sees an uploaded logo.

    The name holds no path separator, because pytex refuses one, and the row id
    prefix keeps two uploads of the same original name apart.
    """
    base = (file_name or "").replace("\\", "/").rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0] if "." in base else base
    safe = _ASSET_UNSAFE_RE.sub("_", stem).strip("._-")[:_ASSET_STEM_MAX] or "logo"
    return f"{logo_id.hex}-{safe}{_MIME_EXTENSION.get(mime, '.bin')}"
