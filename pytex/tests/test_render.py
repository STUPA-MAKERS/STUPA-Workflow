"""Contract tests for ``POST /render`` with the render backend mocked.

Covers the success shape (PDF/TeX bytes + headers), the forwarding contract
(body, variant, kinds reach :class:`BuildRequest` verbatim), and the error map
(empty/oversize body, bad enums, library errors) — every detail string scrubbed
of filesystem paths.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from pytex_api import (
    ApiError,
    CompileError,
    InputKind,
    LimitError,
    OutputKind,
    TrustError,
    TrustLevel,
)

import app as app_module
from tests.conftest import RenderRecorder, make_result

PROTOCOL_MD = b"""---
typ: protokoll
gremium: StuPa
---
# Sitzung

TOP 1.
"""


# --- success ---------------------------------------------------------------


def test_render_md_to_pdf_returns_pdf_bytes(
    client: TestClient, render: RenderRecorder
) -> None:
    render.returns(make_result(b"%PDF-1.5 hello", OutputKind.PDF))
    resp = client.post(
        "/render?input_kind=md&output_kind=pdf", content=b"# Hi\n\nWorld."
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == b"%PDF-1.5 hello"
    assert resp.headers["x-render-duration-seconds"] == "0.123"
    # forwarding contract: body verbatim, declared kinds honoured.
    assert render.last.source == b"# Hi\n\nWorld."
    assert render.last.input_kind is InputKind.MARKDOWN
    assert render.last.output_kind is OutputKind.PDF


def test_render_md_to_tex_returns_plain_text(
    client: TestClient, render: RenderRecorder
) -> None:
    render.returns(make_result(b"\\documentclass{article}", OutputKind.TEX))
    resp = client.post("/render?input_kind=md&output_kind=tex", content=b"# Hi")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert resp.text == "\\documentclass{article}"


def test_warnings_header(client: TestClient, render: RenderRecorder) -> None:
    render.returns(make_result(warnings=("a", "b")))
    resp = client.post("/render", content=b"# Hi")
    assert resp.headers["x-warnings"] == "2"


# --- defaults: app-generated docs are trusted, PDF out ---------------------


def test_defaults_trusted_pdf(client: TestClient, render: RenderRecorder) -> None:
    render.returns(make_result())
    resp = client.post("/render", content=b"# Hi")
    assert resp.status_code == 200
    assert render.last.input_kind is InputKind.MARKDOWN
    assert render.last.output_kind is OutputKind.PDF
    assert render.last.trust is TrustLevel.TRUSTED


# --- variant -----------------------------------------------------------------


def test_variant_defaults_to_none_for_frontmatter_autodetect(
    client: TestClient, render: RenderRecorder
) -> None:
    # No ?variant -> None, so the library auto-detects from frontmatter. The
    # frontmatter bytes must reach the request untouched.
    render.returns(make_result())
    resp = client.post("/render", content=PROTOCOL_MD)
    assert resp.status_code == 200
    assert render.last.variant is None
    assert render.last.source == PROTOCOL_MD


def test_variant_query_is_forwarded(
    client: TestClient, render: RenderRecorder
) -> None:
    for name in ("protocol-stupa", "protocol-asta", "report"):
        render.returns(make_result())
        resp = client.post(f"/render?variant={name}", content=b"# Hi")
        assert resp.status_code == 200
        assert render.last.variant == name


# --- body limits -------------------------------------------------------------


def test_empty_body_400(client: TestClient, render: RenderRecorder) -> None:
    resp = client.post("/render", content=b"")
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_oversize_body_413(
    client: TestClient, render: RenderRecorder, monkeypatch
) -> None:
    monkeypatch.setattr(app_module, "_MAX_BODY_BYTES", 8)
    resp = client.post("/render", content=b"123456789")  # 9 > 8
    assert resp.status_code == 413


# --- enum parsing ------------------------------------------------------------


def test_bad_trust_level_400(client: TestClient, render: RenderRecorder) -> None:
    resp = client.post("/render?trust_level=wizard", content=b"# Hi")
    assert resp.status_code == 400
    assert "trust_level" in resp.json()["error"]


def test_bad_output_kind_400(client: TestClient, render: RenderRecorder) -> None:
    resp = client.post("/render?output_kind=docx", content=b"# Hi")
    assert resp.status_code == 400


# --- error mapping (scrubbed) ------------------------------------------------


def test_limit_error_413(client: TestClient, render: RenderRecorder) -> None:
    render.raises(LimitError("input exceeds cap at /tmp/pytex-api-xyz/in.md"))
    resp = client.post("/render", content=b"# Hi")
    assert resp.status_code == 413
    assert "/tmp/pytex-api-xyz" not in resp.json()["error"]
    assert "<path>" in resp.json()["error"]


def test_compile_error_400_scrubbed(
    client: TestClient, render: RenderRecorder
) -> None:
    render.raises(CompileError("tectonic failed: /home/app/.cache/x.log line 4"))
    resp = client.post("/render", content=b"# Hi")
    assert resp.status_code == 400
    assert "/home/app" not in resp.json()["error"]


def test_trust_error_400(client: TestClient, render: RenderRecorder) -> None:
    render.raises(TrustError("python execution forbidden for untrusted"))
    resp = client.post("/render?trust_level=untrusted", content=b"# Hi")
    assert resp.status_code == 400


def test_api_error_400(client: TestClient, render: RenderRecorder) -> None:
    render.raises(ApiError("bad asset name"))
    resp = client.post("/render", content=b"# Hi")
    assert resp.status_code == 400


def test_unexpected_error_500_no_leak(
    client: TestClient, render: RenderRecorder
) -> None:
    render.raises(RuntimeError("boom at /home/app/secret/path"))
    resp = client.post("/render", content=b"# Hi")
    assert resp.status_code == 500
    body = resp.json()
    assert body == {"error": "internal render error"}
    assert "/home/app" not in str(body)
