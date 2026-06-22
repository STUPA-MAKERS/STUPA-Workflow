"""Unit-Tests pytex-Client (T-20): respx-Mock von ``POST /render``.

Deckt Erfolg (PDF-Bytes), 4xx (dauerhaft, kein Retry), 5xx (transient), Transport-
Fehler (transient) und unerwarteten Content-Type ab.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.modules.pdf.pytex_client import (
    PytexClient,
    PytexError,
    _markdown_has_eval_trigger,
    build_pytex_client,
)
from app.settings import load_settings

BASE = "http://pytex:8099"


def test_eval_trigger_check_is_linear_on_adversarial_marker() -> None:
    """Regressionsschutz gegen ReDoS: ``\\iffalse`` + langer Whitespace OHNE folgendes
    ``pytex(`` darf NICHT katastrophal backtracken (vorher O(N²) → CI-Hang). Kein
    Treffer + in Millisekunden statt Minuten."""
    import time

    adversarial = "\\iffalse" + " " * 200_000 + "{"
    start = time.perf_counter()
    assert _markdown_has_eval_trigger(adversarial) is False
    assert time.perf_counter() - start < 1.0


def _client() -> PytexClient:
    return PytexClient(base_url=BASE, trust_level="trusted", timeout_seconds=5)


@respx.mock
async def test_render_success_returns_pdf_bytes() -> None:
    route = respx.post(f"{BASE}/render").mock(
        return_value=httpx.Response(
            200, content=b"%PDF-1.4 ok", headers={"content-type": "application/pdf"}
        )
    )
    out = await _client().render_pdf("# doc", variant="report")
    assert out == b"%PDF-1.4 ok"
    # Markdown geht als roher Body (keine Shell/kein Form-Encoding) + Query-Params.
    req = route.calls.last.request
    assert req.content == b"# doc"
    assert req.url.params["output_kind"] == "pdf"
    assert req.url.params["variant"] == "report"
    assert req.url.params["trust_level"] == "trusted"


@respx.mock
async def test_render_trust_level_override_per_call() -> None:
    """Ein expliziter ``trust_level`` gilt nur für diesen Aufruf, ohne das
    Client-Default (``trusted``) zu ändern (Client-Plumbing für per-Call-Overrides)."""
    route = respx.post(f"{BASE}/render").mock(
        return_value=httpx.Response(
            200, content=b"%PDF", headers={"content-type": "application/pdf"}
        )
    )
    client = _client()  # Default trusted
    await client.render_pdf("# d", trust_level="untrusted")
    assert route.calls.last.request.url.params["trust_level"] == "untrusted"
    assert client.trust_level == "trusted"  # Default unverändert
    # Ohne Override fällt der Client auf sein Default zurück.
    await client.render_pdf("# d")
    assert route.calls.last.request.url.params["trust_level"] == "trusted"


@respx.mock
async def test_render_omits_variant_when_none() -> None:
    route = respx.post(f"{BASE}/render").mock(
        return_value=httpx.Response(
            200, content=b"%PDF", headers={"content-type": "application/pdf"}
        )
    )
    await _client().render_pdf("# d")
    assert "variant" not in route.calls.last.request.url.params


@respx.mock
async def test_render_4xx_is_permanent() -> None:
    respx.post(f"{BASE}/render").mock(return_value=httpx.Response(400, json={"error": "bad"}))
    with pytest.raises(PytexError) as ei:
        await _client().render_pdf("# d")
    assert ei.value.retryable is False
    assert ei.value.status == 400


@respx.mock
async def test_render_5xx_is_retryable() -> None:
    respx.post(f"{BASE}/render").mock(return_value=httpx.Response(503))
    with pytest.raises(PytexError) as ei:
        await _client().render_pdf("# d")
    assert ei.value.retryable is True


@respx.mock
async def test_render_transport_error_is_retryable() -> None:
    respx.post(f"{BASE}/render").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(PytexError) as ei:
        await _client().render_pdf("# d")
    assert ei.value.retryable is True


@respx.mock
async def test_render_unexpected_content_type_permanent() -> None:
    respx.post(f"{BASE}/render").mock(
        return_value=httpx.Response(200, text="oops", headers={"content-type": "text/plain"})
    )
    with pytest.raises(PytexError) as ei:
        await _client().render_pdf("# d")
    assert ei.value.retryable is False


def test_build_pytex_client_from_settings() -> None:
    settings = load_settings(pytex_url="http://px:1", pytex_trust="sandboxed")
    client = build_pytex_client(settings)
    assert client.base_url == "http://px:1"
    assert client.trust_level == "sandboxed"


# --- AUD-010: client-side eval-trigger gate for trusted renders ---------------

# A live pytex eval comment (``[//]: # "EXPR"``) — the only TRUSTED-gated RCE
# surface for ``input_kind=md``. The Markdown builders strip it via
# ``sanitize_user_markdown``; the client is the second, independent barrier.
_EVAL_BODY = '[//]: # "__import__(\'os\').system(\'id\')"\n\n# doc'


@respx.mock
async def test_trusted_render_refuses_live_eval_trigger() -> None:
    """A surviving eval trigger must NOT be rendered trusted (fail-closed)."""
    route = respx.post(f"{BASE}/render").mock(
        return_value=httpx.Response(
            200, content=b"%PDF", headers={"content-type": "application/pdf"}
        )
    )
    with pytest.raises(PytexError) as ei:
        await _client().render_pdf(_EVAL_BODY, variant="protocol-stupa")
    # Permanent policy error, and the body never reached pytex.
    assert ei.value.retryable is False
    assert not route.called


@respx.mock
async def test_nontrusted_render_passes_eval_trigger_to_pytex() -> None:
    """Below trusted, pytex' own policy blocks the eval — the client doesn't gate."""
    route = respx.post(f"{BASE}/render").mock(
        return_value=httpx.Response(
            200, content=b"%PDF", headers={"content-type": "application/pdf"}
        )
    )
    out = await _client().render_pdf(_EVAL_BODY, trust_level="untrusted")
    assert out == b"%PDF"
    assert route.called


@respx.mock
async def test_trusted_render_allows_clean_markdown() -> None:
    """Normal Markdown (real refs, callouts) renders trusted unimpeded."""
    route = respx.post(f"{BASE}/render").mock(
        return_value=httpx.Response(
            200, content=b"%PDF", headers={"content-type": "application/pdf"}
        )
    )
    # A real reference link def (``[foo]: #section`` — NOT a bare ``#`` target) and
    # an inline anchor must not be mistaken for the eval trigger.
    clean = (
        "# Protokoll\n\nSee [section](#intro)\n\n[foo]: #section\n\n"
        "> [!abstimmung] **Frage**\n"
    )
    out = await _client().render_pdf(clean, variant="protocol-stupa")
    assert out == b"%PDF"
    assert route.called
