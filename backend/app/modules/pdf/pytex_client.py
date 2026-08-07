"""pytex HTTP client — the ``api`` container only ever calls ``/render``.

The client sends the server-generated Markdown as the raw request body to
``POST {PYTEX_URL}/render`` (``input_kind=md``, ``output_kind=pdf``,
``trust_level=trusted``, ``variant=<per gremium>``) and returns the PDF bytes. There is
no shell call. The Markdown is never part of a command line.

A render with a document config or binary assets goes over ``multipart/form-data``
instead: ``source`` for the Markdown, ``config`` for a JSON object, and one repeated
``assets`` part per file. Without both the client keeps the raw-body shape.

Errors map to ``PytexError``, which carries only the status and a short reason. The
pytex container scrubs paths and stacktraces itself, so no internal path leaks out. A
4xx is a permanent input or policy error and gets no retry. A 5xx or a transport error
is transient, so the worker retries.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

import httpx

from app.settings import Settings

# pytex signals a PDF through the Content-Type. Any other body breaks the contract.
_PDF_CONTENT_TYPE = "application/pdf"
_MAX_ERROR_DETAIL = 300
_MARKDOWN_CONTENT_TYPE = "text/markdown; charset=utf-8"
# The multipart field names of the pytex ``/render`` contract.
_SOURCE_FIELD = "source"
_CONFIG_FIELD = "config"
_ASSETS_FIELD = "assets"
# pytex reads the asset name from the file name of the part, so the part needs one.
_ASSET_CONTENT_TYPE = "application/octet-stream"

# One multipart file part: ``(field, (filename, content, content_type))``.
type _FilePart = tuple[str, tuple[str, bytes, str]]

# Live pytex ``eval`` trigger: pytex ``_eval_comment`` fires ONLY for a link-reference
# with ``label == "//"`` AND a bare-``#`` target (``[//]: # "EXPR"``). CommonMark
# allows whitespace and newlines inside the label and around the ``:``. The label then
# normalizes to ``//``, because the whitespace collapses. We match exactly this head,
# independent of the sanitizer regex, so the barrier holds even when ``marko`` is
# missing. The structural verifier there is only an extra line of defense.
_LIVE_EVAL_TRIGGER_RE = re.compile(
    r"\[[ \t\r\n]*/[ \t\r\n]*/[ \t\r\n]*\]"  # label ``//`` (whitespace/newline tolerant)
    r"[ \t]*(?:\r?\n[ \t]*)?:"  # ``:`` (may sit on the next line)
    r"[ \t]*(?:\r?\n[ \t]*)?#"  # bare-``#`` target (possibly multi-line)
    r"(?=[ \t\r\n\"'(]|$)",  # … followed by whitespace/title delimiter/line end
    re.DOTALL,
)
# The evaluated pytex marker (``\iffalse{pytex(...)}\fi``) has no place in the body.
# Its presence is also a signal that the body must not render trusted.
_PYTEX_MARKER_RE = re.compile(r"\\iffalse\s*\{?\s*pytex\s*\(", re.DOTALL | re.IGNORECASE)


def _markdown_has_eval_trigger(markdown: str) -> bool:
    r"""``True`` if ``markdown`` carries a live pytex ``eval`` trigger.

    This is the second and independent RCE barrier for ``trusted`` renders. The
    sanitizer ``sanitize_user_markdown`` already strips eval-capable
    ``[//]: # "EXPR"`` definitions while it builds the Markdown. Here we verify at the
    client edge with a standalone regex that none of them survived. We also check that
    no evaluated ``\iffalse{pytex(...)}\fi`` marker leaks through. The check needs no
    external dependency, unlike the marko-based structural check. A genuine reference
    link (``[foo]: #section`` has no bare ``#``) stays untouched.
    """
    return bool(_LIVE_EVAL_TRIGGER_RE.search(markdown) or _PYTEX_MARKER_RE.search(markdown))


def _error_detail(response: httpx.Response) -> str:
    """Pull the scrubbed ``{"error": …}`` reason from the pytex error response (truncated)."""
    try:
        body = response.json()
        detail = body.get("error") if isinstance(body, dict) else None
    except ValueError:
        detail = response.text
    detail = (detail or "").strip() or "no detail"
    return detail[:_MAX_ERROR_DETAIL]


class PytexError(RuntimeError):
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
        PytexError: The config holds a value that JSON cannot represent.
    """
    if not config:
        return {}
    try:
        return {_CONFIG_FIELD: json.dumps(dict(config))}
    except (TypeError, ValueError) as exc:
        raise PytexError(
            f"pytex config is not JSON-serializable ({type(exc).__name__})",
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
class PytexClient:
    """Thin async HTTP client around the pytex ``/render`` endpoint."""

    base_url: str
    trust_level: str = "trusted"
    timeout_seconds: float = 120.0

    async def render_pdf(
        self,
        markdown: str,
        *,
        variant: str | None = None,
        trust_level: str | None = None,
        config: Mapping[str, object] | None = None,
        assets: Mapping[str, bytes] | None = None,
    ) -> bytes:
        """Render Markdown to PDF bytes.

        With ``variant=None`` pytex infers the variant from the frontmatter. With
        ``trust_level=None`` the call uses the client default (``self.trust_level``,
        usually ``trusted`` for app-generated PDFs). An explicit override applies to
        this call only. For example ``trust_level="untrusted"`` fits user-written
        Markdown such as a protocol or an agenda body. It locks the pytex Markdown
        ``eval`` escape and sandboxes the build, which protects against RCE.

        ``config`` holds document-class parameters, which override the frontmatter.
        ``assets`` holds binary files keyed by their plain file name, which pytex
        writes next to the rendered ``.tex`` file so ``config`` can name them.

        Defense in depth: the protocol and report variants must render ``trusted``,
        because the template machinery blocks ``untrusted`` and ``sandboxed``. The only
        trusted-gated RCE vector for ``input_kind=md`` is therefore the ``eval``
        comment (``[//]: # "EXPR"``). The Markdown builders neutralize it through
        ``sanitize_user_markdown`` before the Markdown reaches here, but that sanitizer
        was the only barrier. As a second and independent line we check the structure
        before the ``trusted`` render. The body must carry no live eval trigger. A
        sanitizer bypass thus becomes a contained, non-retryable error instead of RCE
        (fail-closed). For a non-``trusted`` render the pytex policy applies.

        Raises:
            PytexError: pytex refused or failed the render, or it returned a body that
                is not a PDF.
        """
        effective_trust = trust_level if trust_level is not None else self.trust_level
        if effective_trust == "trusted" and _markdown_has_eval_trigger(markdown):
            # Fail-closed: a surviving eval trigger must NOT render trusted. There is
            # no retry, because the input permanently violates the policy.
            raise PytexError(
                "refused to render trusted markdown with a live eval trigger",
                retryable=False,
            )
        params: dict[str, str] = {
            "input_kind": "md",
            "output_kind": "pdf",
            "trust_level": effective_trust,
        }
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
            raise PytexError(
                f"pytex unreachable ({type(exc).__name__})", retryable=True
            ) from exc

        if response.status_code != httpx.codes.OK:
            # The pytex-scrubbed ``{"error": …}`` body carries the reason, for example a
            # LaTeX compile error. We keep it, defensively truncated, so the server log
            # and the 422 show the cause instead of an opaque 503.
            retryable = response.status_code >= 500
            raise PytexError(
                f"pytex render failed (status {response.status_code}): {_error_detail(response)}",
                status=response.status_code,
                retryable=retryable,
            )

        content_type = response.headers.get("content-type", "")
        if not content_type.startswith(_PDF_CONTENT_TYPE):
            raise PytexError(
                f"pytex returned unexpected content-type {content_type!r}",
                retryable=False,
            )
        return response.content


def build_pytex_client(settings: Settings) -> PytexClient:
    """Build a ``PytexClient`` from settings (``PYTEX_URL``/``PYTEX_TRUST``)."""
    return PytexClient(
        base_url=settings.pytex_url,
        trust_level=settings.pytex_trust,
        timeout_seconds=float(settings.pytex_timeout_seconds),
    )
