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

import re
from dataclasses import dataclass

import httpx

from app.settings import Settings

# pytex erkennt PDF am Content-Type; ein anderer Body wäre ein Vertragsbruch.
_PDF_CONTENT_TYPE = "application/pdf"
_MAX_ERROR_DETAIL = 300

# Lebender pytex-``eval``-Trigger (AUD-010): pytex' ``_eval_comment`` feuert
# AUSSCHLIESSLICH für eine Link-Referenz-Definition mit ``label == "//"`` UND
# bare-``#``-Ziel (``[//]: # "EXPR"``). CommonMark erlaubt Whitespace/Zeilenumbruch
# innerhalb des Labels und vor/nach dem ``:`` — das Label normalisiert dabei zu
# ``//`` (Whitespace kollabiert). Wir matchen exakt diesen Kopf, unabhängig vom
# Regex des Sanitizers, sodass diese Barriere auch ohne installiertes ``marko``
# greift (der strukturelle Verifizierer dort ist nur eine Zusatzlinie).
_LIVE_EVAL_TRIGGER_RE = re.compile(
    r"\[[ \t\r\n]*/[ \t\r\n]*/[ \t\r\n]*\]"  # Label ``//`` (WS/Newline-tolerant)
    r"[ \t]*(?:\r?\n[ \t]*)?:"  # ``:`` (darf auf der Folgezeile stehen)
    r"[ \t]*(?:\r?\n[ \t]*)?#"  # bare-``#``-Ziel (ggf. mehrzeilig)
    r"(?=[ \t\r\n\"'(]|$)",  # … gefolgt von WS/Titel-Delimiter/Zeilenende
    re.DOTALL,
)
# Der ausgewertete pytex-Marker (``\iffalse{pytex(...)}\fi``) hat im Body nichts
# verloren — sein Vorhandensein ist ebenfalls ein nicht-trusted-fähiges Signal.
# Das optionale ``{`` steht IM optionalen Block ``(?:\{\s*)?`` (statt ``\{?`` zwischen
# zwei ``\s*``): ohne diesen Anker könnten zwei benachbarte ``\s*`` denselben
# Whitespace-Lauf auf O(N²)-viele Arten aufteilen (katastrophales Backtracking / ReDoS
# bei ``\iffalse``+langem Whitespace ohne folgendes ``pytex``).
_PYTEX_MARKER_RE = re.compile(
    r"\\iffalse\s*(?:\{\s*)?pytex\s*\(", re.DOTALL | re.IGNORECASE
)


def _markdown_has_eval_trigger(markdown: str) -> bool:
    """``True``, wenn ``markdown`` einen lebenden pytex-``eval``-Trigger trägt.

    Zweite, unabhängige RCE-Barriere für ``trusted``-Renders (AUD-010): der
    Sanitizer (``sanitize_user_markdown``) entfernt eval-fähige
    ``[//]: # "EXPR"``-Definitionen schon beim Markdown-Aufbau — hier verifizieren
    wir am Client-Rand mit einer **eigenständigen** Regex, dass keine überlebt hat
    (und kein ausgewerteter ``\\iffalse{pytex(...)}\\fi``-Marker durchsickert). Greift
    ohne externe Abhängigkeit (anders als der marko-basierte Struktur-Check). Echte
    Referenz-Links (``[foo]: #section`` → kein bare-``#``) bleiben unberührt."""
    return bool(_LIVE_EVAL_TRIGGER_RE.search(markdown) or _PYTEX_MARKER_RE.search(markdown))


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

    async def render_pdf(
        self,
        markdown: str,
        *,
        variant: str | None = None,
        trust_level: str | None = None,
    ) -> bytes:
        """Markdown → PDF-Bytes. ``variant=None`` ⇒ pytex erkennt aus dem Frontmatter.

        ``trust_level=None`` nutzt das Client-Default (``self.trust_level``, i. d. R.
        ``trusted`` für app-generierte PDFs). Ein expliziter Override gilt **nur** für
        diesen Aufruf — z. B. ``trust_level="untrusted"`` für vom Nutzer geschriebenes
        Markdown (Protokoll/TOP-Bodies), das pytex' Markdown-``eval``-Escape sperrt
        und den Build sandboxt (RCE-Schutz, security.md §2).

        **Defense-in-Depth (AUD-010):** Die Protokoll-/Report-Varianten müssen
        ``trusted`` rendern (die Template-Maschinerie sperrt ``untrusted``/``sandboxed``),
        also ist der einzige TRUSTED-gated RCE-Vektor für ``input_kind=md`` der
        ``eval``-Kommentar (``[//]: # "EXPR"``). Den entschärfen die Markdown-Builder
        per ``sanitize_user_markdown`` BEVOR das Markdown hierher kommt — aber dieser
        Sanitizer war bislang die **einzige** Barriere. Wir verifizieren daher als
        zweite, unabhängige Linie unmittelbar vor dem ``trusted``-Render strukturell,
        dass der Body **keinen** lebenden eval-Trigger trägt; ein etwaiger
        Sanitizer-Bypass wird so zu einem eingedämmten (nicht-retrybaren) Fehler statt
        zu RCE (fail-closed). Für nicht-``trusted`` Renders übernimmt pytex' Policy."""
        effective_trust = trust_level if trust_level is not None else self.trust_level
        if effective_trust == "trusted" and _markdown_has_eval_trigger(markdown):
            # Fail-closed: ein überlebender eval-Trigger DARF nicht trusted gerendert
            # werden. Kein Retry — die Eingabe ist dauerhaft policy-verletzend.
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
