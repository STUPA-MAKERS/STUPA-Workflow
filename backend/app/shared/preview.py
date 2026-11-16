"""The sandboxed inline preview of a served file (spec 001083).

The SPA shows a PDF or a raster image in the file viewer of the kit: an image in an
``<img>``, a PDF in an ``<iframe>`` of the same origin. A route that serves such a file
accepts ``?inline=true``. Only then the answer is ``inline`` and may be framed, and only
by ``'self'``. The default API set (``X-Frame-Options: DENY``, ``frame-ancestors 'none'``)
would block the frame. ``sandbox`` puts the document in a unique origin without
scripts, so a PDF polyglot cannot run in the origin of the app (000264). The built-in PDF
viewers of Firefox and Chromium still render with this policy.

``SecurityHeadersMiddleware`` sets its defaults with ``setdefault``, so these headers win.
nginx must list a framable route in its download location (``deploy/web/nginx.conf``),
because its server-level ``X-Frame-Options: DENY`` would block the frame too.
"""

from __future__ import annotations

from typing import Final, Literal

from fastapi.responses import Response

from app.shared.filenames import content_disposition

#: Types the viewer shows and the preview may serve inline: PDF and raster images. HTML,
#: SVG and XML never appear here, so there is no stored-XSS vector.
INLINE_MIMES: Final[frozenset[str]] = frozenset(
    {"application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp"}
)

#: CSP of an inline preview answer.
PREVIEW_CSP: Final[str] = (
    "default-src 'none'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'; sandbox"
)

#: The headers that let the SPA frame the preview.
PREVIEW_HEADERS: Final[dict[str, str]] = {
    "Content-Security-Policy": PREVIEW_CSP,
    "X-Frame-Options": "SAMEORIGIN",
}


def file_response(
    data: bytes,
    *,
    name: str,
    mime: str,
    inline: bool,
    disposition: Literal["attachment", "inline"] = "attachment",
    fallback_mime: str | None = None,
    extra: dict[str, str] | None = None,
) -> Response:
    """Answer a file, as the sandboxed preview when ``inline`` asks for it.

    Args:
        data: The bytes of the file.
        name: The display name of the file.
        mime: The type of the file, sniffed or fixed by the server, never from the client.
        inline: The caller sent ``?inline=true``.
        disposition: The disposition of the answer without the preview.
        fallback_mime: The media type of the answer without the preview, when it differs
            from ``mime`` (``application/octet-stream`` for a logo).
        extra: Further headers, for example ``Cache-Control``.

    Returns:
        The preview (``inline`` plus ``PREVIEW_HEADERS``) when ``inline`` is set and
        ``mime`` is in ``INLINE_MIMES``, else the answer as before.
    """
    preview = inline and mime in INLINE_MIMES
    kind: Literal["attachment", "inline"] = "inline" if preview else disposition
    headers = {
        **(extra or {}),
        "Content-Disposition": content_disposition(kind, name),
        **(PREVIEW_HEADERS if preview else {}),
    }
    media_type = mime if preview else (fallback_mime or mime)
    return Response(content=data, media_type=media_type, headers=headers)
