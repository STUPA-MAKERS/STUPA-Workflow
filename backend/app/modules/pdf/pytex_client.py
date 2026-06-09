"""pytex-HTTP-Client (T-20/T-21, deployment §3: ``api``→``pytex`` nur ``/render``).

Der Client schickt das **server-generierte Markdown als rohen Request-Body** an
``POST {PYTEX_URL}/render`` (``input_kind=md``, ``output_kind=pdf``,
``trust_level=trusted``, ``variant=<je Gremium>``) und gibt die PDF-Bytes zurück. Es
gibt **keinen** Shell-Aufruf — das Markdown ist nie Teil einer Kommandozeile.

Fehler werden auf :class:`PytexError` gemappt und tragen **nur** Status/Kurzgrund (der
pytex-Container scrubbt seinerseits Pfade/Stacktraces) — kein interner Pfad-Leak nach
außen (security.md §2). 4xx ist ein dauerhafter Eingabe-/Policy-Fehler (kein Retry),
5xx/Transport ein transienter (Worker-Retry).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.settings import Settings

# pytex erkennt PDF am Content-Type; ein anderer Body wäre ein Vertragsbruch.
_PDF_CONTENT_TYPE = "application/pdf"
_MAX_ERROR_DETAIL = 300


def _error_detail(response: httpx.Response) -> str:
    """Gescrubbten ``{"error": …}``-Grund aus der pytex-Fehlerantwort ziehen (gekürzt)."""
    try:
        body = response.json()
        detail = body.get("error") if isinstance(body, dict) else None
    except ValueError:
        detail = response.text
    detail = (detail or "").strip() or "no detail"
    return detail[:_MAX_ERROR_DETAIL]


class PytexError(RuntimeError):
    """Render fehlgeschlagen. ``retryable`` trennt transient (5xx/Transport) von
    dauerhaft (4xx/Eingabe)."""

    def __init__(self, detail: str, *, status: int | None = None, retryable: bool) -> None:
        super().__init__(detail)
        self.status = status
        self.retryable = retryable


@dataclass(slots=True)
class PytexClient:
    """Dünner async HTTP-Client um den pytex-``/render``-Endpunkt."""

    base_url: str
    trust_level: str = "trusted"
    timeout_seconds: float = 120.0

    async def render_pdf(self, markdown: str, *, variant: str | None = None) -> bytes:
        """Markdown → PDF-Bytes. ``variant=None`` ⇒ pytex erkennt aus dem Frontmatter."""
        params: dict[str, str] = {
            "input_kind": "md",
            "output_kind": "pdf",
            "trust_level": self.trust_level,
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
            # Transport-/Timeout-Fehler: transient → Worker-Retry.
            raise PytexError(
                f"pytex unreachable ({type(exc).__name__})", retryable=True
            ) from exc

        if response.status_code != httpx.codes.OK:
            # 4xx = dauerhafter Eingabe-/Policy-Fehler, 5xx = transient. Der
            # (bereits von pytex gescrubbte) ``{"error": …}``-Body trägt den Grund
            # (z. B. LaTeX-Compile-Fehler) — defensiv gekürzt mitnehmen, damit das
            # Server-Log/422 die Ursache zeigt statt eines opaken 503.
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
    """:class:`PytexClient` aus den Settings (``PYTEX_URL``/``PYTEX_TRUST``)."""
    return PytexClient(
        base_url=settings.pytex_url,
        trust_level=settings.pytex_trust,
        timeout_seconds=float(settings.pytex_timeout_seconds),
    )
