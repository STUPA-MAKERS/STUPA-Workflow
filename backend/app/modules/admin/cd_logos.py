"""Logo policy of the corporate-design (CD) variants.

A CD variant controls the logos of a rendered document and nothing else. It
carries no color and no font. A logo entry is EITHER a vendored logo name
OR an object that an admin uploaded. This module holds the closed value sets and
the upload security contract.

Security contract for an uploaded CD logo in the ``title`` or ``footer`` slot.
The bytes go to the render service only. They never render in the browser as
an image. The allowlist therefore adds
``image/svg+xml`` and ``application/pdf``, which the site branding
(``admin.branding``) refuses on purpose. The server sniffs the magic bytes and
compares them against the declared type. It caps the real byte size. Any route
that serves such an object back MUST force ``Content-Disposition: attachment``
and MUST NOT answer with ``image/svg+xml``, because an SVG is an XSS vector in
the app origin. ``get_invoice_file`` in the budget module hardens the same way.

The ``square`` slot is the exception. The browser shows that logo inline as an
image, so it accepts PNG, JPEG and WebP only (an SVG is an XSS vector in the app
origin). The server reads the pixel size from the header and requires a square
of at least ``SQUARE_LOGO_MIN_PX`` and at most ``SQUARE_LOGO_MAX_PX`` pixels,
because every viewer's browser decodes the image, and a small file can declare
a huge canvas. ``check_square_logo`` holds this policy.

The asset name that ``cd_resolver`` hands to the render service is a plain
file name without a path separator. The service refuses anything else. The
name carries the logo row id, so two uploads of the same original file name
never collide.
"""

from __future__ import annotations

import re
import uuid
from typing import Final, Literal

from app.modules.admin.branding import sniff_raster_image
from app.modules.admin.image_size import raster_dimensions
from app.shared.errors import (
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
    ValidationProblem,
)

#: Logo names that the render service ships (``vendored-logos`` in
#: ``typst/template/protocol.typ``). A vendored entry needs no upload and no object
#: storage.
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

#: Where a logo appears. ``title`` and ``footer`` go into the rendered document.
#: ``square`` is the 1:1 logo that the app shows for a Gremium in the browser. The
#: render path never reads it.
LogoSlot = Literal["title", "footer", "square"]

#: The slots that the render path reads.
RenderSlot = Literal["title", "footer"]
RENDER_SLOTS: Final[tuple[RenderSlot, ...]] = ("title", "footer")

#: The document shape that the variant builds on.
CdBaseVariant = Literal["report", "protocol"]


ALLOWED_CD_LOGO_MIME: Final[frozenset[str]] = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/svg+xml",
        "application/pdf",
    }
)
#: 2 MB, the same cap as a branding logo.
MAX_CD_LOGO_BYTES: Final[int] = 2 * 1024 * 1024

#: The square logo renders in the browser, so it is raster only.
ALLOWED_SQUARE_LOGO_MIME: Final[frozenset[str]] = frozenset(
    {"image/png", "image/jpeg", "image/webp"}
)
#: The smallest edge of a square logo in pixels. A smaller one looks blurred on a
#: high-density screen.
SQUARE_LOGO_MIN_PX: Final[int] = 256
SQUARE_LOGO_MAX_PX: Final[int] = 4096
#: The largest difference between width and height, as a fraction of the longer
#: edge, that still counts as square.
SQUARE_LOGO_TOLERANCE: Final[float] = 0.01

#: Extension per accepted type. The asset name takes the extension from the
#: SNIFFED type, never from the uploaded file name. LaTeX picks its image driver
#: by extension, so a wrong one breaks the render.
_MIME_EXTENSION: Final[dict[str, str]] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "application/pdf": ".pdf",
}

#: Bytes of the head that the SVG sniff reads. An SVG may open with a BOM, an XML
#: declaration, a comment or a DOCTYPE before the root element.
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
    """Build the plain file name under which the render service sees an uploaded logo.

    The name holds no path separator, so the render service resolves it inside the build
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


def check_square_logo(data: bytes) -> str:
    """Apply the upload policy of the square logo and return the sniffed type.

    Raises:
        PayloadTooLargeError: The bytes exceed ``MAX_CD_LOGO_BYTES`` (413,
            ``logo_too_large``).
        UnsupportedMediaTypeError: The bytes are empty or not PNG, JPEG or WebP
            (415, ``logo_type_not_allowed``).
        ValidationProblem: The header gives no pixel size (``logo_unreadable``),
            the image is not square (``logo_not_square``), or an edge is shorter
            than ``SQUARE_LOGO_MIN_PX`` (``logo_too_small``) or an edge is longer
            than ``SQUARE_LOGO_MAX_PX`` (``logo_too_many_px``). All 422.
    """
    if len(data) > MAX_CD_LOGO_BYTES:
        raise PayloadTooLargeError(
            f"Logo exceeds {MAX_CD_LOGO_BYTES} bytes.", code="logo_too_large"
        )
    mime = sniff_raster_image(data)
    if mime is None or mime not in ALLOWED_SQUARE_LOGO_MIME:
        raise UnsupportedMediaTypeError(
            "A square logo must be PNG, JPEG or WebP (checked from the bytes).",
            code="logo_type_not_allowed",
        )
    size = raster_dimensions(data)
    if size is None:
        raise ValidationProblem(
            "The image header gives no pixel size.",
            code="logo_unreadable",
            errors=[{"field": "file", "msg": "unreadable image header"}],
        )
    width, height = size
    if abs(width - height) > SQUARE_LOGO_TOLERANCE * max(width, height):
        raise ValidationProblem(
            f"The logo is {width} x {height} px. A square logo needs a 1:1 aspect ratio.",
            code="logo_not_square",
            errors=[{"field": "file", "msg": f"{width}x{height}"}],
        )
    if min(width, height) < SQUARE_LOGO_MIN_PX:
        raise ValidationProblem(
            f"The logo is {width} x {height} px. A square logo needs at least "
            f"{SQUARE_LOGO_MIN_PX} x {SQUARE_LOGO_MIN_PX} px.",
            code="logo_too_small",
            errors=[{"field": "file", "msg": f"{width}x{height}"}],
        )
    if max(width, height) > SQUARE_LOGO_MAX_PX:
        raise ValidationProblem(
            f"The logo is {width} x {height} px. A square logo can have at most "
            f"{SQUARE_LOGO_MAX_PX} x {SQUARE_LOGO_MAX_PX} px.",
            code="logo_too_many_px",
            errors=[{"field": "file", "msg": f"{width}x{height}"}],
        )
    return mime
