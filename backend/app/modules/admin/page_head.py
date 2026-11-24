"""The page head of the app shell, filled from the active branding.

A link preview (messenger, chat, search engine) reads the HTML of a page and runs no
script, so a title that Angular sets at runtime never reaches it
(§ F/administration/admin/001090). The web server includes this fragment into
``index.html`` with an SSI subrequest (``deploy/web/nginx.conf``), so every page load
gets the title, the description, the app name of iOS, the icons and the Open Graph and
Twitter tags of the active branding. ``index.html`` holds the built-in tags as the stub,
and the service worker keeps the unchanged build file.

Every value goes through ``html.escape``: the app name and the description are admin
text, and the fragment is raw HTML in the head.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from app.modules.site_config.brand_images import (
    PREVIEW_SIZE,
    favicon_file,
    has_icon_mark,
    mark_bytes,
)
from app.modules.site_config.branding import Branding
from app.modules.site_config.names import (
    DEFAULT_APP_NAME,
    DEFAULT_APP_SHORT_NAME,
    app_name,
    app_short_name,
)
from app.shared.i18n import I18nMap, resolve_i18n

__all__ = [
    "DEFAULT_APP_NAME",
    "DEFAULT_APP_SHORT_NAME",
    "DEFAULT_DESCRIPTION",
    "app_name",
    "app_short_name",
    "description",
    "render_page_head",
]

#: The built-in description. It names no platform, so it fits every branding.
DEFAULT_DESCRIPTION: I18nMap = {
    "de": "Anträge, Abstimmungen, Sitzungen, Protokolle und Haushalt an einem Ort.",
    "en": "Applications, votes, meetings, minutes and budget in one place.",
}

#: The language of the page head: ``index.html`` is ``lang="de"``.
HEAD_LANG = "de"

#: The paths of the branded images (``admin.router.branding_router``).
PREVIEW_PATH = "/api/branding/preview.png"
FAVICON_PATH = "/api/branding/favicon"
APPLE_ICON_PATH = "/api/branding/icons/icon-180x180.png"

#: The built-in images of the frontend build (``frontend/public``).
BUILTIN_PREVIEW_PATH = "/icons/icon-512x512.png"
BUILTIN_FAVICON_PATH = "/favicon.ico"
BUILTIN_MARK_PATH = "/assets/logos/stupa-mark.svg"
BUILTIN_APPLE_ICON_PATH = "/apple-touch-icon.png"


def _text(value: I18nMap, lang: str) -> str:
    filled = {code: " ".join(text.split()) for code, text in value.items() if text.strip()}
    return resolve_i18n(filled, lang) or ""


def description(branding: Branding, lang: str = HEAD_LANG) -> str:
    """Return the description of the branding for ``lang``, or the built-in text."""
    return _text(branding.description, lang) or _text(DEFAULT_DESCRIPTION, lang)


@dataclass(frozen=True, slots=True)
class HeadImages:
    """The image URLs of the head: absolute for the preview, paths for the icons.

    ``icons`` holds the ``(type, href)`` pairs of the ``rel="icon"`` links.
    """

    preview: str
    icons: tuple[tuple[str, str], ...]
    apple_icon: str


def head_images(branding: Branding, base_url: str, version: int) -> HeadImages:
    """Return the image URLs of the head; ``?v=`` changes with every branding save.

    The built-in preview is the 512 px app icon, so the preview is a 512 px PNG either
    way.
    """
    base = base_url.rstrip("/")
    query = f"?v={version}"
    favicon = favicon_file(branding)
    return HeadImages(
        preview=(
            f"{base}{PREVIEW_PATH}{query}"
            if mark_bytes(branding) is not None
            else f"{base}{BUILTIN_PREVIEW_PATH}"
        ),
        icons=(
            ((favicon.mime, f"{FAVICON_PATH}{query}"),)
            if favicon is not None
            else (("image/svg+xml", BUILTIN_MARK_PATH), ("image/x-icon", BUILTIN_FAVICON_PATH))
        ),
        apple_icon=(
            f"{APPLE_ICON_PATH}{query}" if has_icon_mark(branding) else BUILTIN_APPLE_ICON_PATH
        ),
    )


def render_page_head(branding: Branding, *, base_url: str, version: int) -> str:
    """Render the branded tags of the page head as an HTML fragment."""
    name = escape(app_name(branding))
    short = escape(app_short_name(branding))
    text = escape(description(branding))
    images = head_images(branding, base_url, version)
    preview = escape(images.preview)
    lines = [
        f"<title>{name}</title>",
        f'<meta name="description" content="{text}" />',
        f'<meta name="application-name" content="{name}" />',
        f'<meta name="apple-mobile-web-app-title" content="{short}" />',
        *(
            f'<link rel="icon" type="{escape(kind)}" href="{escape(href)}" />'
            for kind, href in images.icons
        ),
        f'<link rel="apple-touch-icon" sizes="180x180" href="{escape(images.apple_icon)}" />',
        '<meta property="og:type" content="website" />',
        f'<meta property="og:site_name" content="{name}" />',
        f'<meta property="og:title" content="{name}" />',
        f'<meta property="og:description" content="{text}" />',
        '<meta property="og:locale" content="de_DE" />',
        f'<meta property="og:image" content="{preview}" />',
        '<meta property="og:image:type" content="image/png" />',
        f'<meta property="og:image:width" content="{PREVIEW_SIZE}" />',
        f'<meta property="og:image:height" content="{PREVIEW_SIZE}" />',
        f'<meta property="og:image:alt" content="{name}" />',
        '<meta name="twitter:card" content="summary" />',
        f'<meta name="twitter:title" content="{name}" />',
        f'<meta name="twitter:description" content="{text}" />',
        f'<meta name="twitter:image" content="{preview}" />',
    ]
    return "\n".join(lines) + "\n"
