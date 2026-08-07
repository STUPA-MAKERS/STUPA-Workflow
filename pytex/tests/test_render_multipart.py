"""Contract tests for the `multipart/form-data` shape of `POST /render`.

The multipart shape is the channel that pushes binary assets (Corporate-Design
logos) and a config object into a render. The tests cover the forwarding
contract: `source`, `config` and every `assets` part reach `BuildRequest`
unchanged, and the query params still apply. They also cover the guards: a
malformed `config`, an unknown field, an asset part without a file name, a
duplicate asset name, too many assets, one oversize asset and an oversize
total. The render backend stays mocked, so no test touches tectonic.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import app as app_module
from tests.conftest import RenderRecorder, make_result

# httpx builds a multipart body from `files=` (file parts) plus `data=` (plain
# fields). A file part is `(field, (filename, bytes, content_type))`.
type FilePart = tuple[str, tuple[str | None, bytes, str]]

SOURCE_MD = b"# Bericht\n\nText."
LOGO_PNG = b"\x89PNG\r\n\x1a\nfake-logo"
CONFIG = {"logos": ["stupa.png"], "footer_logos": "asta.png", "title": "Bericht"}


def _source_part(source: bytes = SOURCE_MD) -> FilePart:
    return ("source", ("source.md", source, "text/markdown; charset=utf-8"))


def _asset_part(name: str, data: bytes = LOGO_PNG) -> FilePart:
    return ("assets", (name, data, "application/octet-stream"))


def test_multipart_forwards_source_config_and_assets(
    client: TestClient, render: RenderRecorder
) -> None:
    render.returns(make_result())
    resp = client.post(
        "/render?variant=report&trust_level=untrusted&output_kind=pdf",
        files=[
            _source_part(),
            _asset_part("stupa.png"),
            _asset_part("asta.png", b"second-logo"),
        ],
        data={"config": json.dumps(CONFIG)},
    )
    assert resp.status_code == 200
    assert render.last.source == SOURCE_MD
    assert render.last.config == CONFIG
    assert render.last.assets == {"stupa.png": LOGO_PNG, "asta.png": b"second-logo"}
    # The query params keep working next to the multipart body.
    assert render.last.variant == "report"
    assert render.last.trust.value == "untrusted"


def test_multipart_without_config_or_assets(
    client: TestClient, render: RenderRecorder
) -> None:
    """A `source`-only form is valid and behaves like the raw body."""
    render.returns(make_result())
    resp = client.post("/render", files=[_source_part()])
    assert resp.status_code == 200
    assert render.last.source == SOURCE_MD
    assert render.last.config == {}
    assert render.last.assets == {}


def test_multipart_source_as_plain_field(
    client: TestClient, render: RenderRecorder
) -> None:
    """`source` may arrive as a plain form field instead of a file part."""
    render.returns(make_result())
    resp = client.post("/render", data={"source": "# Hi"}, files=[_asset_part("l.png")])
    assert resp.status_code == 200
    assert render.last.source == b"# Hi"
    assert render.last.assets == {"l.png": LOGO_PNG}


def test_multipart_empty_source_400(
    client: TestClient, render: RenderRecorder
) -> None:
    resp = client.post("/render", files=[_asset_part("l.png")])
    assert resp.status_code == 400
    assert "source" in resp.json()["error"]
    assert not render.calls


@pytest.mark.parametrize("raw", ["not json", "[1, 2]", '"a string"', "42", "null"])
def test_multipart_config_must_be_a_json_object_400(
    client: TestClient, render: RenderRecorder, raw: str
) -> None:
    resp = client.post("/render", files=[_source_part()], data={"config": raw})
    assert resp.status_code == 400
    assert "config" in resp.json()["error"]
    assert not render.calls


def test_multipart_unknown_field_400(
    client: TestClient, render: RenderRecorder
) -> None:
    resp = client.post("/render", files=[_source_part()], data={"logo": "x"})
    assert resp.status_code == 400
    assert "logo" in resp.json()["error"]
    assert not render.calls


def test_multipart_asset_without_filename_400(
    client: TestClient, render: RenderRecorder
) -> None:
    resp = client.post("/render", files=[_source_part()], data={"assets": "raw bytes"})
    assert resp.status_code == 400
    assert "file name" in resp.json()["error"]
    assert not render.calls


def test_multipart_duplicate_asset_name_400(
    client: TestClient, render: RenderRecorder
) -> None:
    resp = client.post(
        "/render",
        files=[_source_part(), _asset_part("l.png"), _asset_part("l.png", b"other")],
    )
    assert resp.status_code == 400
    assert "duplicate" in resp.json()["error"]
    assert not render.calls


def test_too_many_assets_413(
    client: TestClient, render: RenderRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "_MAX_ASSETS", 2)
    files = [_source_part(), *(_asset_part(f"l{i}.png") for i in range(3))]
    resp = client.post("/render", files=files)
    assert resp.status_code == 413
    assert "assets" in resp.json()["error"]
    assert not render.calls


def test_single_oversize_asset_413(
    client: TestClient, render: RenderRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "_MAX_ASSET_BYTES", 4)
    resp = client.post(
        "/render", files=[_source_part(), _asset_part("big.png", b"123456789")]
    )
    assert resp.status_code == 413
    assert "big.png" in resp.json()["error"]
    assert not render.calls


def test_oversize_total_413(
    client: TestClient, render: RenderRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Source plus every asset must fit inside the total body cap."""
    monkeypatch.setattr(app_module, "_MAX_BODY_BYTES", 32)
    monkeypatch.setattr(app_module, "_MAX_ASSET_BYTES", 32)
    resp = client.post(
        "/render",
        files=[_source_part(b"# doc"), _asset_part("l.png", b"x" * 30)],
    )
    assert resp.status_code == 413
    assert "exceeds" in resp.json()["error"]
    assert not render.calls


def test_bad_asset_name_maps_to_400(
    client: TestClient, render: RenderRecorder
) -> None:
    """The library owns the asset-name rule; the route maps its error to 400."""
    from pytex_api import TrustError

    render.raises(TrustError("asset name must not contain a path separator: 'a/b'"))
    resp = client.post("/render", files=[_source_part(), _asset_part("a.png")])
    assert resp.status_code == 400
    assert "path separator" in resp.json()["error"]


def test_malformed_multipart_body_400(
    client: TestClient, render: RenderRecorder
) -> None:
    resp = client.post(
        "/render",
        content=b"--boundary\r\nnot a multipart part at all\r\n",
        headers={"content-type": "multipart/form-data; boundary=boundary"},
    )
    assert resp.status_code == 400
    assert not render.calls
