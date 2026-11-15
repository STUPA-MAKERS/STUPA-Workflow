"""The branding of a mail: the name, the logo, the accent and the footer of the platform.

Every mail takes these values from the active branding of ``/admin/branding``, and the
frame (`layout`) shows them. The mail and the app then name and show the same platform.

The logo goes into the mail as an inline PNG part (§ F/collaboration/notifications/000999).
A mail client blocks a remote image and removes a ``data:`` image, so only an inline part
shows without a click. Not every client shows WebP or ICO, so Pillow re-encodes the logo
as PNG. A logo that the branding holds only as a URL counts as no logo, because the
server never fetches a branding URL.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.colours import DEFAULT_ACCENT, normalize_accent
from app.modules.site_config.branding import Branding, BrandingAsset
from app.modules.site_config.reads import active_branding
from app.settings import Settings
from app.shared.i18n import I18nMap, resolve_i18n

logger = logging.getLogger("app.mail")

#: The content id of the logo part; the frame shows it as ``cid:brand-logo``.
LOGO_CID = "brand-logo"
#: The height of the logo in the head of the mail, in CSS pixels.
LOGO_SHOWN_HEIGHT = 40
#: The widest logo in the head of the mail, in CSS pixels.
LOGO_SHOWN_WIDTH = 240
#: The PNG holds three device pixels per CSS pixel at most.
LOGO_MAX_HEIGHT = LOGO_SHOWN_HEIGHT * 3
LOGO_MAX_WIDTH = LOGO_SHOWN_WIDTH * 3

LogoKind = Literal["wordmark", "imagemark"]


@dataclass(frozen=True, slots=True)
class MailLogo:
    """The logo of the mail head: the PNG bytes and the size that the head shows."""

    png: bytes
    kind: LogoKind
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class MailLegalLink:
    """A legal link of the footer; ``url`` is http(s) or a path of the platform."""

    label: I18nMap
    url: str


@dataclass(frozen=True, slots=True)
class MailBrand:
    """What a mail shows of the branding."""

    name: str
    logo: MailLogo | None = None
    accent: str = DEFAULT_ACCENT
    footer_text: I18nMap = field(default_factory=dict)
    copyright: I18nMap = field(default_factory=dict)
    legal_links: tuple[MailLegalLink, ...] = ()


def brand_text(value: I18nMap, lang: str) -> str:
    """Return the text of ``value`` for ``lang`` along the fallback chain, or ``""``.

    A blank entry counts as no entry, so an empty English field shows the German text.
    """
    filled = {code: text.strip() for code, text in value.items() if text.strip()}
    return resolve_i18n(filled, lang) or ""


def _shown_size(width: int, height: int) -> tuple[int, int]:
    """Return the size in the head: at most 40 px high and 240 px wide, never enlarged."""
    scale = min(LOGO_SHOWN_HEIGHT / height, LOGO_SHOWN_WIDTH / width, 1.0)
    return max(1, round(width * scale)), max(1, round(height * scale))


def _png(data: bytes) -> tuple[bytes, int, int] | None:
    """Re-encode image bytes as a PNG of at most 120 px height; None for no image."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as source:
            rgba = source.convert("RGBA")
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        logger.warning("branding logo is not usable in mails: %s", type(exc).__name__)
        return None
    scale = min(LOGO_MAX_HEIGHT / rgba.height, LOGO_MAX_WIDTH / rgba.width, 1.0)
    size = (max(1, round(rgba.width * scale)), max(1, round(rgba.height * scale)))
    scaled = rgba if size == rgba.size else rgba.resize(size, Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    scaled.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue(), scaled.width, scaled.height


def _logo_of(asset: BrandingAsset | None, kind: LogoKind) -> MailLogo | None:
    """Return the mail logo of a branding asset; None without inline image bytes."""
    data = asset.inline_bytes() if asset is not None else None
    encoded = _png(data) if data is not None else None
    if encoded is None:
        return None
    png, width, height = encoded
    shown_width, shown_height = _shown_size(width, height)
    return MailLogo(png=png, kind=kind, width=shown_width, height=shown_height)


def mail_logo(branding: Branding) -> MailLogo | None:
    """Return the logo of the mail head: the Wortmarke, else the Bildmarke, else None."""
    return _logo_of(branding.logos.get("wordmark"), "wordmark") or _logo_of(
        branding.logos.get("imagemark"), "imagemark"
    )


def _mail_url(url: str) -> bool:
    """Return whether a legal link works in a mail: http(s), or a path of the platform."""
    low = url.strip().lower()
    return low.startswith(("https://", "http://")) or (
        low.startswith("/") and not low.startswith("//")
    )


def mail_brand(branding: Branding, settings: Settings) -> MailBrand:
    """Build the mail brand from a branding.

    The name is the app name of the branding. An empty app name gives the sender name of
    the server settings (§ F/collaboration/notifications/000998). A legal link without a
    label or with a URL that a mail cannot open is left out.
    """
    return MailBrand(
        name=" ".join(branding.app_name.split()) or settings.mail_from_name,
        logo=mail_logo(branding),
        accent=normalize_accent(branding.accent_color),
        footer_text=branding.freetexts.email_footer,
        copyright=branding.copyright,
        legal_links=tuple(
            MailLegalLink(label=link.label, url=link.url.strip())
            for link in branding.legal_links
            if _mail_url(link.url) and any(text.strip() for text in link.label.values())
        ),
    )


async def load_mail_brand(session: AsyncSession, settings: Settings) -> MailBrand:
    """Read the active branding and build the mail brand from it."""
    return mail_brand(await active_branding(session), settings)
