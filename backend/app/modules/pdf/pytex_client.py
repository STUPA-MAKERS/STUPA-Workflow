"""pytex HTTP client — the ``api`` container only ever calls ``/render``.

The client sends the server-generated Markdown as the raw request body to
``POST {PYTEX_URL}/render`` (``input_kind=md``, ``output_kind=pdf``,
``trust_level=trusted``, ``variant=<per gremium>``) and returns the PDF bytes. There is
no shell call — the Markdown is never part of a command line.

Errors map to ``PytexError`` carrying only status/short reason (the pytex container
scrubs paths/stacktraces itself), so no internal path leaks out. 4xx is a permanent
input/policy error (no retry), 5xx/transport is transient (worker retry).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from app.settings import Settings

# pytex signals a PDF via the Content-Type; any other body breaks the contract.
_PDF_CONTENT_TYPE = "application/pdf"
_MAX_ERROR_DETAIL = 300

# Live pytex ``eval`` trigger: pytex' ``_eval_comment`` fires ONLY for a link-reference
# definition with ``label == "//"`` AND a bare-``#`` target (``[//]: # "EXPR"``).
# CommonMark allows whitespace/newlines inside the label and around the ``:``; the
# label then normalises to ``//`` (whitespace collapses). We match exactly this head,
# independent of the sanitizer's regex, so the barrier holds even without ``marko``
# installed (the structural verifier there is only an extra line).
_LIVE_EVAL_TRIGGER_RE = re.compile(
    r"\[[ \t\r\n]*/[ \t\r\n]*/[ \t\r\n]*\]"  # label ``//`` (whitespace/newline tolerant)
    r"[ \t]*(?:\r?\n[ \t]*)?:"  # ``:`` (may sit on the next line)
    r"[ \t]*(?:\r?\n[ \t]*)?#"  # bare-``#`` target (possibly multi-line)
    r"(?=[ \t\r\n\"'(]|$)",  # … followed by whitespace/title delimiter/line end
    re.DOTALL,
)
# The evaluated pytex marker (``\iffalse{pytex(...)}\fi``) has no place in the body —
# its presence is likewise a not-trusted-capable signal.
_PYTEX_MARKER_RE = re.compile(r"\\iffalse\s*\{?\s*pytex\s*\(", re.DOTALL | re.IGNORECASE)


def _markdown_has_eval_trigger(markdown: str) -> bool:
    """``True`` if ``markdown`` carries a live pytex ``eval`` trigger.

    Second, independent RCE barrier for ``trusted`` renders: the sanitizer
    (``sanitize_user_markdown``) already strips eval-capable ``[//]: # "EXPR"``
    definitions while building the Markdown; here we verify at the client edge with a
    standalone regex that none survived (and no evaluated ``\\iffalse{pytex(...)}\\fi``
    marker leaks through). Works without an external dependency (unlike the marko-based
    structural check). Genuine reference links (``[foo]: #section`` → no bare ``#``)
    are untouched."""
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
    """Render failed. ``retryable`` separates transient (5xx/transport) from permanent
    (4xx/input)."""

    def __init__(self, detail: str, *, status: int | None = None, retryable: bool) -> None:
        super().__init__(detail)
        self.status = status
        self.retryable = retryable


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
    ) -> bytes:
        """Markdown → PDF bytes. ``variant=None`` ⇒ pytex infers it from the frontmatter.

        ``trust_level=None`` uses the client default (``self.trust_level``, usually
        ``trusted`` for app-generated PDFs). An explicit override applies to this call
        only — e.g. ``trust_level="untrusted"`` for user-written Markdown
        (protocol/agenda bodies), which locks pytex' Markdown ``eval`` escape and
        sandboxes the build (RCE protection).

        Defense in depth: the protocol/report variants must render ``trusted`` (the
        template machinery blocks ``untrusted``/``sandboxed``), so the only
        trusted-gated RCE vector for ``input_kind=md`` is the ``eval`` comment
        (``[//]: # "EXPR"``). The Markdown builders neutralise it via
        ``sanitize_user_markdown`` before the Markdown reaches here, but that sanitizer
        was the only barrier. As a second, independent line we structurally verify just
        before the ``trusted`` render that the body carries no live eval trigger; any
        sanitizer bypass thus becomes a contained (non-retryable) error rather than RCE
        (fail-closed). For non-``trusted`` renders pytex' own policy applies."""
        effective_trust = trust_level if trust_level is not None else self.trust_level
        if effective_trust == "trusted" and _markdown_has_eval_trigger(markdown):
            # Fail-closed: a surviving eval trigger must NOT render trusted. No retry —
            # the input permanently violates policy.
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
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    url,
                    params=params,
                    content=markdown.encode("utf-8"),
                    headers={"Content-Type": "text/markdown; charset=utf-8"},
                )
        except httpx.HTTPError as exc:
            # Transport/timeout error: transient → worker retry.
            raise PytexError(
                f"pytex unreachable ({type(exc).__name__})", retryable=True
            ) from exc

        if response.status_code != httpx.codes.OK:
            # 4xx = permanent input/policy error, 5xx = transient. The (already
            # pytex-scrubbed) ``{"error": …}`` body carries the reason (e.g. a LaTeX
            # compile error) — kept, defensively truncated, so the server log/422 shows
            # the cause instead of an opaque 503.
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
