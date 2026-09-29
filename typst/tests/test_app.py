"""Contract tests for `POST /render` and `GET /health`, with a fake compiler."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from typst_service import app as app_module
from typst_service.compiler import CompileError, CompileTimeout

from .conftest import FAKE_PDF, CompileRecorder

# httpx builds a multipart body from `files=` (file parts) plus `data=` (plain
# fields). A file part is `(field, (filename, bytes, content_type))`.
type FilePart = tuple[str, tuple[str | None, bytes, str]]

SOURCE = b'---\ntitle: "Sitzung"\ngremium: "StuPa"\n---\n\n# Bericht\n\nText.\n'
LOGO_PNG = b"\x89PNG\r\n\x1a\nfake-logo"


def _source_part(source: bytes = SOURCE) -> FilePart:
    return ("source", ("source.md", source, "text/markdown; charset=utf-8"))


def _asset_part(name: str, data: bytes = LOGO_PNG) -> FilePart:
    return ("assets", (name, data, "application/octet-stream"))


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_raw_body_renders_pdf(client: TestClient, compiler: CompileRecorder) -> None:
    resp = client.post(
        "/render?variant=protocol-asta",
        content=SOURCE,
        headers={"Content-Type": "text/markdown; charset=utf-8"},
    )
    assert resp.status_code == 200
    assert resp.content == FAKE_PDF
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["content-disposition"] == 'inline; filename="document.pdf"'
    assert float(resp.headers["x-render-duration-seconds"]) >= 0
    assert compiler.doc["title"] == "Sitzung"
    assert compiler.doc["logos"] == [{"name": "ASTA"}]
    assert compiler.assets == {}


def test_multipart_forwards_config_and_assets(
    client: TestClient, compiler: CompileRecorder
) -> None:
    config = {"logos": ["a1-stupa.png", "INF"], "footer_logos": "a2-asta.png"}
    resp = client.post(
        "/render?variant=protocol-stupa",
        files=[_source_part(), _asset_part("a1-stupa.png"), _asset_part("a2-asta.png", b"x")],
        data={"config": json.dumps(config)},
    )
    assert resp.status_code == 200
    assert compiler.doc["logos"] == [{"asset": "a1-stupa.png"}, {"name": "INF"}]
    assert compiler.doc["footer_logos"] == [{"asset": "a2-asta.png"}]
    assert compiler.assets == {"a1-stupa.png": LOGO_PNG, "a2-asta.png": b"x"}


def test_multipart_source_as_plain_field(client: TestClient, compiler: CompileRecorder) -> None:
    resp = client.post("/render", data={"source": "# Hi"}, files=[_asset_part("l.png")])
    assert resp.status_code == 200
    assert compiler.assets == {"l.png": LOGO_PNG}


@pytest.mark.parametrize(
    ("kwargs", "needle"),
    [
        ({"content": b""}, "source"),
        ({"files": [_asset_part("l.png")]}, "source"),
        ({"files": [_source_part()], "data": {"config": "not json"}}, "config"),
        ({"files": [_source_part()], "data": {"config": "[1, 2]"}}, "config"),
        ({"files": [_source_part()], "data": {"logo": "x"}}, "logo"),
        ({"files": [_source_part()], "data": {"assets": "raw"}}, "file name"),
        ({"files": [_source_part(), _asset_part("../x.png")]}, "asset name"),
        ({"files": [_source_part(), _asset_part("x.exe")]}, "asset name"),
        ({"files": [_source_part(), _asset_part(".hidden.png")]}, "asset name"),
        (
            {"files": [_source_part(), _asset_part("l.png"), _asset_part("l.png", b"o")]},
            "duplicate",
        ),
        ({"content": b"\xff\xfe not utf-8"}, "UTF-8"),
        ({"content": b"---\ntitle: [unclosed\n---\n"}, "YAML"),
        ({"files": [_source_part()], "data": {"config": '{"logos": ["NOPE"]}'}}, "NOPE"),
    ],
)
def test_bad_requests_answer_400(
    client: TestClient, compiler: CompileRecorder, kwargs: dict[str, object], needle: str
) -> None:
    resp = client.post("/render", **kwargs)  # pyright: ignore[reportArgumentType]
    assert resp.status_code == 400
    assert needle in resp.json()["error"]
    assert not compiler.calls


def test_unknown_variant_400(client: TestClient, compiler: CompileRecorder) -> None:
    resp = client.post("/render?variant=report", content=SOURCE)
    assert resp.status_code == 400
    assert "variant" in resp.json()["error"]
    assert not compiler.calls


def test_too_many_assets_413(
    client: TestClient, compiler: CompileRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "_MAX_ASSETS", 2)
    files = [_source_part(), *(_asset_part(f"l{i}.png") for i in range(3))]
    resp = client.post("/render", files=files)
    assert resp.status_code == 413
    assert not compiler.calls


def test_oversize_asset_413(
    client: TestClient, compiler: CompileRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "_MAX_ASSET_BYTES", 4)
    resp = client.post("/render", files=[_source_part(), _asset_part("big.png", b"123456789")])
    assert resp.status_code == 413
    assert "big.png" in resp.json()["error"]


def test_total_over_body_cap_413(
    client: TestClient, compiler: CompileRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "_MAX_BODY_BYTES", 20)
    # A chunked upload declares no Content-Length, so the check after the read
    # must hold on its own.
    resp = client.post("/render", content=iter([SOURCE]))
    assert resp.status_code == 413
    assert not compiler.calls


def test_declared_length_over_cap_413(
    client: TestClient, compiler: CompileRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "_MAX_BODY_BYTES", 20)
    resp = client.post("/render", content=SOURCE)
    assert resp.status_code == 413
    assert not compiler.calls


def test_malformed_content_length_falls_through(client: TestClient) -> None:
    resp = client.post("/render", content=SOURCE, headers={"content-length": "abc"})
    # httpx rewrites a bad header, so the request still carries the body; the
    # route must not crash on a non-integer value either way.
    assert resp.status_code in (200, 400)


def test_compile_error_400_scrubs_paths(client: TestClient, compiler: CompileRecorder) -> None:
    compiler.error = CompileError("error: failed at /tmp/typst-job-x/main.typ:3")
    resp = client.post("/render", content=SOURCE)
    assert resp.status_code == 400
    assert "/tmp" not in resp.json()["error"]
    assert "<path>" in resp.json()["error"]


def test_compile_timeout_413(client: TestClient, compiler: CompileRecorder) -> None:
    compiler.error = CompileTimeout("typst compile exceeded 60 s")
    resp = client.post("/render", content=SOURCE)
    assert resp.status_code == 413


def test_unexpected_error_500_without_detail(client: TestClient, compiler: CompileRecorder) -> None:
    compiler.error = RuntimeError("secret /app/internal detail")
    resp = client.post("/render", content=SOURCE)
    assert resp.status_code == 500
    assert resp.json() == {"error": "internal render error"}


def test_malformed_multipart_400(client: TestClient) -> None:
    resp = client.post(
        "/render",
        content=b"--nope\r\nbroken",
        headers={"Content-Type": "multipart/form-data; boundary=nope"},
    )
    assert resp.status_code == 400
