"""Unit tests for the pytex client (T-20): a respx mock of `POST /render`.

The tests cover success (PDF bytes), 4xx (permanent, no retry), 5xx (transient),
a transport error (transient), and an unexpected content type. They also cover the
two wire shapes: the raw body without a config and without assets, and the
multipart form that carries the config object plus the binary assets.
"""

from __future__ import annotations

import json
from email import message_from_bytes
from email.message import Message

import httpx
import pytest
import respx

from app.modules.pdf.pytex_client import PytexClient, PytexError, build_pytex_client
from app.settings import load_settings

BASE = "http://pytex:8099"


def _client() -> PytexClient:
    return PytexClient(base_url=BASE, trust_level="trusted", timeout_seconds=5)


def _parts(request: httpx.Request) -> list[tuple[str, str | None, bytes]]:
    """Parse a recorded multipart body into `(field name, file name, bytes)` triples."""
    raw = (
        b"Content-Type: "
        + request.headers["content-type"].encode()
        + b"\r\n\r\n"
        + request.content
    )
    payload = message_from_bytes(raw).get_payload()
    assert isinstance(payload, list), "the request body is not multipart"
    out: list[tuple[str, str | None, bytes]] = []
    for part in payload:
        assert isinstance(part, Message)
        name = part.get_param("name", header="content-disposition")
        body = part.get_payload(decode=True)
        out.append(
            (str(name), part.get_filename(), body if isinstance(body, bytes) else b"")
        )
    return out


def _pdf_route() -> respx.Route:
    return respx.post(f"{BASE}/render").mock(
        return_value=httpx.Response(
            200, content=b"%PDF", headers={"content-type": "application/pdf"}
        )
    )


@respx.mock
async def test_render_success_returns_pdf_bytes() -> None:
    route = respx.post(f"{BASE}/render").mock(
        return_value=httpx.Response(
            200, content=b"%PDF-1.4 ok", headers={"content-type": "application/pdf"}
        )
    )
    out = await _client().render_pdf("# doc", variant="report")
    assert out == b"%PDF-1.4 ok"
    # The client sends the Markdown as a raw body plus query parameters. It runs no
    # shell and applies no form encoding.
    req = route.calls.last.request
    assert req.content == b"# doc"
    assert req.url.params["output_kind"] == "pdf"
    assert req.url.params["variant"] == "report"
    assert req.url.params["trust_level"] == "trusted"


@respx.mock
async def test_render_trust_level_override_per_call() -> None:
    """An explicit `trust_level` applies only to this call.

    The client default (`trusted`) stays unchanged. This test covers the client
    plumbing for per-call overrides.
    """
    route = respx.post(f"{BASE}/render").mock(
        return_value=httpx.Response(
            200, content=b"%PDF", headers={"content-type": "application/pdf"}
        )
    )
    client = _client()  # the default is trusted
    await client.render_pdf("# d", trust_level="untrusted")
    assert route.calls.last.request.url.params["trust_level"] == "untrusted"
    assert client.trust_level == "trusted"  # the default stays unchanged
    # Without an override the client falls back to its default.
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


# Config + assets channel: the caller pushes uploaded Corporate-Design logos into a
# render. Only such a call switches the wire shape to multipart.

LOGO = b"\x89PNG\r\n\x1a\nfake-logo"
CONFIG: dict[str, object] = {"logos": ["stupa.png"], "footer_logos": "asta.png"}


@respx.mock
async def test_render_without_config_or_assets_keeps_the_raw_body() -> None:
    """No config and no assets means the exact request the client sent before."""
    route = _pdf_route()
    await _client().render_pdf("# doc", variant="report")
    req = route.calls.last.request
    assert req.content == b"# doc"
    assert req.headers["content-type"] == "text/markdown; charset=utf-8"


@respx.mock
async def test_render_with_empty_config_and_assets_keeps_the_raw_body() -> None:
    """An empty mapping carries nothing, so it must not force a multipart request."""
    route = _pdf_route()
    await _client().render_pdf("# doc", config={}, assets={})
    req = route.calls.last.request
    assert req.content == b"# doc"
    assert req.headers["content-type"] == "text/markdown; charset=utf-8"


@respx.mock
async def test_render_with_assets_and_config_sends_multipart() -> None:
    route = _pdf_route()
    out = await _client().render_pdf(
        "# doc",
        variant="report",
        config=CONFIG,
        assets={"stupa.png": LOGO, "asta.png": b"second"},
    )
    assert out == b"%PDF"
    req = route.calls.last.request
    assert req.headers["content-type"].startswith("multipart/form-data")
    # The query params keep working next to the multipart body.
    assert req.url.params["variant"] == "report"
    assert req.url.params["trust_level"] == "trusted"
    assert req.url.params["output_kind"] == "pdf"

    parts = _parts(req)
    source = [p for p in parts if p[0] == "source"]
    assert source == [("source", "source.md", b"# doc")]
    config = [p for p in parts if p[0] == "config"]
    assert len(config) == 1
    assert json.loads(config[0][2]) == CONFIG
    # pytex reads the asset name from the file name of the part.
    assets = {name: data for field, name, data in parts if field == "assets"}
    assert assets == {"stupa.png": LOGO, "asta.png": b"second"}


@respx.mock
async def test_render_with_assets_only_sends_no_config_part() -> None:
    route = _pdf_route()
    await _client().render_pdf("# doc", assets={"logo.png": LOGO})
    fields = [field for field, _, _ in _parts(route.calls.last.request)]
    assert fields == ["source", "assets"]


@respx.mock
async def test_render_with_config_only_sends_no_asset_part() -> None:
    route = _pdf_route()
    await _client().render_pdf("# doc", config={"title": "Bericht"})
    fields = [field for field, _, _ in _parts(route.calls.last.request)]
    assert sorted(fields) == ["config", "source"]


@respx.mock
async def test_render_rejects_a_config_that_is_not_json_serializable() -> None:
    """A permanent caller error. The request never leaves the process."""
    route = _pdf_route()
    with pytest.raises(PytexError) as ei:
        await _client().render_pdf("# doc", config={"when": object()})
    assert ei.value.retryable is False
    assert not route.called


def test_build_pytex_client_from_settings() -> None:
    settings = load_settings(pytex_url="http://px:1", pytex_trust="sandboxed")
    client = build_pytex_client(settings)
    assert client.base_url == "http://px:1"
    assert client.trust_level == "sandboxed"


# AUD-010: client-side eval-trigger gate for trusted renders

# A live pytex eval comment (`[//]: # "EXPR"`) is the only TRUSTED-gated RCE surface
# of `input_kind=md`. The Markdown builders strip it with `sanitize_user_markdown`.
# The client is the second, independent barrier.
_EVAL_BODY = '[//]: # "__import__(\'os\').system(\'id\')"\n\n# doc'


@respx.mock
async def test_trusted_render_refuses_live_eval_trigger() -> None:
    """The client refuses to render a surviving eval trigger as trusted (fail closed)."""
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
    """Below trusted the client does not gate. The pytex policy blocks the eval."""
    route = respx.post(f"{BASE}/render").mock(
        return_value=httpx.Response(
            200, content=b"%PDF", headers={"content-type": "application/pdf"}
        )
    )
    out = await _client().render_pdf(_EVAL_BODY, trust_level="untrusted")
    assert out == b"%PDF"
    assert route.called


@respx.mock
async def test_trusted_multipart_render_refuses_live_eval_trigger() -> None:
    """The gate applies to the Markdown, whatever the wire shape is."""
    route = _pdf_route()
    with pytest.raises(PytexError) as ei:
        await _client().render_pdf(
            _EVAL_BODY, variant="report", assets={"logo.png": LOGO}, config=CONFIG
        )
    assert ei.value.retryable is False
    assert not route.called


@respx.mock
async def test_trusted_render_allows_clean_markdown() -> None:
    """Normal Markdown (real refs, callouts) renders as trusted without a block."""
    route = respx.post(f"{BASE}/render").mock(
        return_value=httpx.Response(
            200, content=b"%PDF", headers={"content-type": "application/pdf"}
        )
    )
    # A real reference link definition (`[foo]: #section`, not a bare `#` target) and
    # an inline anchor must not look like the eval trigger.
    clean = (
        "# Protokoll\n\nSee [section](#intro)\n\n[foo]: #section\n\n"
        "> [!abstimmung] **Frage**\n"
    )
    out = await _client().render_pdf(clean, variant="protocol-stupa")
    assert out == b"%PDF"
    assert route.called
