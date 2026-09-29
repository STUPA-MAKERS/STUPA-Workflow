"""HTTP client of the typst render service. The `api` container only calls `/render`.

The client sends the server-generated protocol Markdown as the raw request body to
``POST {TYPST_URL}/render`` (optional ``variant=<per gremium>``) and returns the PDF
bytes. There is no shell call. The Markdown is never part of a command line.

A render that carries a document config or binary assets (for example the uploaded
Corporate-Design logos) goes over ``multipart/form-data`` instead: the Markdown in the
``source`` field, the config as a JSON object in the ``config`` field, and one file
part per asset in the repeated ``assets`` field. Without a config and without assets
the client keeps the raw-body shape.

The render service turns the Markdown into data before Typst sees it, so no part of
the Markdown can run as code there. The client therefore has no trust levels.

Errors map to ``TypstError``, which carries only the status and a short reason. The
service scrubs paths and stacktraces itself, so no internal path leaks out. A 4xx is
a permanent input error and gets no retry. A 5xx or a transport error is transient,
so the worker retries.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

import httpx

from app.settings import Settings

# The service signals a PDF through the Content-Type. Any other body breaks the contract.
_PDF_CONTENT_TYPE = "application/pdf"
_MAX_ERROR_DETAIL = 300
_MARKDOWN_CONTENT_TYPE = "text/markdown; charset=utf-8"
# The multipart field names of the ``/render`` contract.
_SOURCE_FIELD = "source"
_CONFIG_FIELD = "config"
_ASSETS_FIELD = "assets"
# The service reads the asset name from the file name of the part, so the part needs
# one. The bytes are opaque to the service; the template loads them as an image.
_ASSET_CONTENT_TYPE = "application/octet-stream"

# One multipart file part: ``(field, (filename, content, content_type))``.
type _FilePart = tuple[str, tuple[str, bytes, str]]


def _error_detail(response: httpx.Response) -> str:
    """Pull the scrubbed ``{"error": …}`` reason from the error response (truncated)."""
    try:
        body = response.json()
        detail = body.get("error") if isinstance(body, dict) else None
    except ValueError:
        detail = response.text
    detail = (detail or "").strip() or "no detail"
    return detail[:_MAX_ERROR_DETAIL]


class TypstError(RuntimeError):
    """The render failed.

    ``retryable`` separates a transient failure (5xx or transport) from a permanent one
    (4xx or bad input).
    """

    def __init__(self, detail: str, *, status: int | None = None, retryable: bool) -> None:
        super().__init__(detail)
        self.status = status
        self.retryable = retryable


def _config_part(config: Mapping[str, object] | None) -> dict[str, str]:
    """Serialize ``config`` into the ``config`` form field (empty when there is none).

    Raises:
        TypstError: The config holds a value that JSON cannot represent. That is a
            permanent caller error, so it gets no retry.
    """
    if not config:
        return {}
    try:
        return {_CONFIG_FIELD: json.dumps(dict(config))}
    except (TypeError, ValueError) as exc:
        raise TypstError(
            f"render config is not JSON-serializable ({type(exc).__name__})",
            retryable=False,
        ) from exc


def _file_parts(markdown: str, assets: Mapping[str, bytes] | None) -> list[_FilePart]:
    """Build the ``source`` part and one ``assets`` part per uploaded file."""
    parts: list[_FilePart] = [
        (_SOURCE_FIELD, ("source.md", markdown.encode("utf-8"), _MARKDOWN_CONTENT_TYPE))
    ]
    parts.extend(
        (_ASSETS_FIELD, (name, data, _ASSET_CONTENT_TYPE))
        for name, data in (assets or {}).items()
    )
    return parts


@dataclass(slots=True)
class TypstClient:
    """Thin async HTTP client around the typst ``/render`` endpoint."""

    base_url: str
    timeout_seconds: float = 60.0

    async def render_pdf(
        self,
        markdown: str,
        *,
        variant: str | None = None,
        config: Mapping[str, object] | None = None,
        assets: Mapping[str, bytes] | None = None,
    ) -> bytes:
        """Render protocol Markdown to PDF bytes.

        With ``variant=None`` the service reads the default logos from the
        ``gremium`` frontmatter key. ``config`` holds keys that override the
        frontmatter, for example ``logos`` and ``footer_logos``. ``assets`` holds
        binary files keyed by their plain file name; a ``logos`` entry that names an
        asset selects that uploaded file. With both empty the client sends the raw
        body. The service owns the asset-name rule and answers 400 for a bad name.

        Raises:
            TypstError: The service refused or failed the render, or it returned a
                body that is not a PDF.
        """
        params: dict[str, str] = {}
        if variant is not None:
            params["variant"] = variant
        url = self.base_url.rstrip("/") + "/render"
        # Only a config or an asset needs the multipart shape.
        multipart = bool(config) or bool(assets)
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                if multipart:
                    response = await client.post(
                        url,
                        params=params,
                        data=_config_part(config),
                        files=_file_parts(markdown, assets),
                    )
                else:
                    response = await client.post(
                        url,
                        params=params,
                        content=markdown.encode("utf-8"),
                        headers={"Content-Type": _MARKDOWN_CONTENT_TYPE},
                    )
        except httpx.HTTPError as exc:
            raise TypstError(f"typst unreachable ({type(exc).__name__})", retryable=True) from exc

        if response.status_code != httpx.codes.OK:
            # The scrubbed ``{"error": …}`` body carries the reason, for example a
            # malformed formula. We keep it, defensively truncated, so the server log
            # and the 422 show the cause instead of an opaque 503.
            raise TypstError(
                f"typst render failed (status {response.status_code}): "
                f"{_error_detail(response)}",
                status=response.status_code,
                retryable=response.status_code >= 500,
            )

        content_type = response.headers.get("content-type", "")
        if not content_type.startswith(_PDF_CONTENT_TYPE):
            raise TypstError(
                f"typst returned unexpected content-type {content_type!r}",
                retryable=False,
            )
        return response.content


def build_typst_client(settings: Settings) -> TypstClient:
    """Build a ``TypstClient`` from settings (``TYPST_URL``, ``TYPST_TIMEOUT_SECONDS``)."""
    return TypstClient(
        base_url=settings.typst_url,
        timeout_seconds=float(settings.typst_timeout_seconds),
    )
