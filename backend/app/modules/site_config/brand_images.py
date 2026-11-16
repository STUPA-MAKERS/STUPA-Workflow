"""The images that the platform derives from the branding logos.

The link preview, the app icons and the favicon of the page head come from the logos of
``/admin/branding`` (§ F/administration/admin/001091, 001092). The preview shows the
Bildmarke, else the Wortmarke; an app icon shows the Bildmarke only. A logo is an inline data
URL; a logo behind an http(s) URL counts as no logo, because the server never fetches a
branding URL.

A preview image and an app icon are square PNGs: the mark sits in the middle of a white
square with a margin. A messenger crops a preview to a square or a circle, and Android
cuts a maskable icon to a circle that keeps only the inner 80 %, so the margin keeps the
mark whole. White, because a launcher and a messenger show the icon on any background
and a transparent area turns black on iOS.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Literal

from app.modules.site_config.branding import Branding, BrandingAsset

logger = logging.getLogger("app.branding")

#: The side of the link preview image in pixels. WhatsApp, Signal and Slack show a
#: square preview; 512 px is sharp there and stays far below their size caps.
PREVIEW_SIZE = 512

#: The margin around the mark, as a share of the side. ``any`` icons and the preview keep
#: a thin margin; a maskable icon keeps the mark in the inner 80 % circle of Android.
MARGIN_ANY = 0.08
MARGIN_MASKABLE = 0.2

#: The icon sizes of the manifest and the iOS home screen icon (180 px).
ICON_SIZES: tuple[int, ...] = (72, 96, 128, 144, 152, 180, 192, 384, 512)
MASKABLE_SIZES: tuple[int, ...] = (192, 512)

IconPurpose = Literal["any", "maskable"]

_WHITE = (255, 255, 255, 255)


@dataclass(frozen=True, slots=True)
class BrandFile:
    """The bytes and the media type of a branding image."""

    data: bytes
    mime: str


def _inline(asset: BrandingAsset | None) -> bytes | None:
    return asset.inline_bytes() if asset is not None else None


def mark_bytes(branding: Branding) -> bytes | None:
    """Return the bytes of the mark: the Bildmarke, else the Wortmarke, else None."""
    return _inline(branding.logos.get("imagemark")) or _inline(branding.logos.get("wordmark"))


def icon_mark_bytes(branding: Branding) -> bytes | None:
    """Return the bytes of the app icon mark: the Bildmarke only, else None.

    A Wortmarke is too wide for an icon: on a square of 48 px its type is unreadable.
    """
    return _inline(branding.logos.get("imagemark"))


def has_icon_mark(branding: Branding) -> bool:
    """Return whether the branding holds an inline Bildmarke for the app icons."""
    return icon_mark_bytes(branding) is not None


def favicon_file(branding: Branding) -> BrandFile | None:
    """Return the uploaded favicon as it was stored, or None without an inline one."""
    asset = branding.logos.get("favicon")
    data = _inline(asset)
    if asset is None or data is None:
        return None
    return BrandFile(data=data, mime=asset.mime)


def square_png(data: bytes, size: int, *, margin: float) -> bytes | None:
    """Put an image in the middle of a white ``size`` square and encode it as PNG.

    The image keeps its aspect ratio and is scaled up or down to fill the square inside
    the margin. Returns None for bytes that Pillow cannot read.
    """
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as source:
            source.seek(0)
            mark = source.convert("RGBA")
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        logger.warning("branding logo is not usable as an image: %s", type(exc).__name__)
        return None
    inner = max(1, round(size * (1 - 2 * margin)))
    scale = min(inner / mark.width, inner / mark.height)
    fitted = mark.resize(
        (max(1, round(mark.width * scale)), max(1, round(mark.height * scale))),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGBA", (size, size), _WHITE)
    canvas.alpha_composite(fitted, ((size - fitted.width) // 2, (size - fitted.height) // 2))
    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def preview_png(branding: Branding) -> bytes | None:
    """Return the link preview image of the branding, or None without a mark."""
    data = mark_bytes(branding)
    return square_png(data, PREVIEW_SIZE, margin=MARGIN_ANY) if data is not None else None


def icon_png(branding: Branding, size: int, purpose: IconPurpose = "any") -> bytes | None:
    """Return an app icon of the branding, or None without a Bildmarke."""
    data = icon_mark_bytes(branding)
    if data is None:
        return None
    return square_png(data, size, margin=MARGIN_MASKABLE if purpose == "maskable" else MARGIN_ANY)
