"""Logo policy of the corporate-design (CD) variants.

A CD variant controls the logos of a rendered document and nothing else. It
carries no color and no font. A logo entry is EITHER a vendored pytex logo name
OR an object that an admin uploaded. This module holds the closed value sets and
the upload security contract.

Security contract for an uploaded CD logo. The bytes go to the LaTeX renderer
only. They never render in the browser as an image. The allowlist therefore adds
``image/svg+xml`` and ``application/pdf``, which the site branding
(``admin.branding``) refuses on purpose. The server sniffs the magic bytes and
compares them against the declared type. It caps the real byte size. Any route
that serves such an object back MUST force ``Content-Disposition: attachment``
and MUST NOT answer with ``image/svg+xml``, because an SVG is an XSS vector in
the app origin. ``get_invoice_file`` in the budget module hardens the same way.

The asset name that ``cd_resolver`` hands to pytex is a plain file name without
a path separator. pytex refuses anything else. The name carries the logo row id,
so two uploads of the same original file name never collide.
"""

from __future__ import annotations

import re
import uuid
from typing import Final, Literal

from app.modules.admin.branding import sniff_raster_image

# --- closed value sets ----------------------------------------------------

# Logo names that pytex ships (``pytex_hsrtreport.logos.KNOWN_LOGOS``). A
# vendored entry needs no upload and no object storage.
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

# Where a logo appears: on the title page or in the page footer.
LogoSlot = Literal["title", "footer"]
LOGO_SLOTS: Final[tuple[LogoSlot, ...]] = ("title", "footer")

# The pytex document shape that the variant builds on.
CdBaseVariant = Literal["report", "protocol"]
CD_BASE_VARIANTS: Final[tuple[CdBaseVariant, ...]] = ("report", "protocol")

# --- upload policy --------------------------------------------------------

ALLOWED_CD_LOGO_MIME: Final[frozenset[str]] = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/svg+xml",
        "application/pdf",
    }
)
MAX_CD_LOGO_BYTES: Final[int] = 2 * 1024 * 1024  # 2 MB, same cap as a branding logo

# Extension per accepted type. The asset name takes the extension from the
# SNIFFED type, never from the uploaded file name. LaTeX picks its image driver
# by extension, so a wrong one breaks the render.
_MIME_EXTENSION: Final[dict[str, str]] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "application/pdf": ".pdf",
}

# Bytes of the head that the SVG sniff reads. An SVG may open with a BOM, an XML
# declaration, a comment or a DOCTYPE before the root element.
_SVG_HEAD_BYTES: Final[int] = 1024
_SVG_LEADING = b"\xef\xbb\xbf \t\r\n"

_ASSET_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]")
_ASSET_STEM_MAX: Final[int] = 60


def _looks_like_svg(data: bytes) -> bool:
    """Tell whether the head of ``data`` opens an SVG document."""
    head = data[:_SVG_HEAD_BYTES].lstrip(_SVG_LEADING)
    if not head.startswith(b"<"):
        return False
    return b"<svg" in head.lower()


def sniff_cd_logo(data: bytes) -> str | None:
    """Sniff the type of an uploaded CD logo from its magic bytes.

    Returns:
        The sniffed MIME type, or ``None`` when the bytes are not one of the
        accepted types. ICO is not accepted here, although the branding sniffer
        recognizes it.
    """
    raster = sniff_raster_image(data)
    if raster is not None:
        return raster if raster in ALLOWED_CD_LOGO_MIME else None
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if _looks_like_svg(data):
        return "image/svg+xml"
    return None


def asset_file_name(logo_id: uuid.UUID, file_name: str | None, mime: str) -> str:
    """Build the plain file name under which pytex sees an uploaded logo.

    The name holds no path separator, so pytex resolves it inside the build
    directory. The row id prefix makes it unique, so two uploads of the same
    original name never collide inside one variant.

    Args:
        logo_id: Id of the ``cd_variant_logo`` row.
        file_name: The original upload name. It is only a readability hint.
        mime: The sniffed type. It decides the extension.
    """
    base = (file_name or "").replace("\\", "/").rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0] if "." in base else base
    safe = _ASSET_UNSAFE_RE.sub("_", stem).strip("._-")[:_ASSET_STEM_MAX] or "logo"
    return f"{logo_id.hex}-{safe}{_MIME_EXTENSION.get(mime, '.bin')}"
