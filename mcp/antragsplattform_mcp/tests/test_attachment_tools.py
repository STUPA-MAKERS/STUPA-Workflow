"""Tests for the attachment tools: `upload_attachment` and `download_attachment`.

The first part fakes the API and checks the arguments that the tools hand to it. The
second part runs the real `ApiClient` against an `httpx.MockTransport` and checks the
exact multipart request on the wire: the path, the part name `file`, the file name, the
part content type and the form fields `field_key` and `is_comparison_offer`. These are
the names of `POST /api/applications/{id}/attachments` in
`backend/app/modules/files/router.py`. `test_attachment_contract.py` runs the same
tools against that router itself.
"""

from __future__ import annotations

import asyncio
from email.parser import BytesParser
from email.policy import default as email_default
from pathlib import Path
from typing import Any

import httpx
import pytest

from antragsplattform_mcp.client import ApiClient, ApiError
from antragsplattform_mcp.config import Config
from antragsplattform_mcp.tools import _common, meetings

APP_ID = "8f6c2a52-6f2e-4a55-9a43-0a6f1c3b9d10"
ATT_ID = "0b1f6a3e-2f7d-4c1e-8e7a-5d9c4b3a2f10"
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


class _FakeApi:
    """Record each post and answer like the upload route."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def post(self, path: str, **kw: Any) -> dict[str, Any]:
        self.calls.append((path, kw))
        return {"id": ATT_ID, "scanned": False}


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    return fake


@pytest.fixture
def pdf(tmp_path: Path) -> Path:
    p = tmp_path / "Angebot 1.pdf"
    p.write_bytes(PDF)
    return p


def test_upload_sends_file_part_and_form(fake_api: _FakeApi, pdf: Path) -> None:
    out = asyncio.run(
        meetings.upload_attachment(
            APP_ID, str(pdf), field_key="offer", is_comparison_offer=True
        )
    )
    assert out == {"id": ATT_ID, "scanned": False}
    assert fake_api.calls == [
        (
            f"/applications/{APP_ID}/attachments",
            {
                "files": {"file": ("Angebot 1.pdf", PDF, "application/pdf")},
                "data": {"is_comparison_offer": "true", "field_key": "offer"},
            },
        )
    ]


def test_upload_leaves_out_field_key(fake_api: _FakeApi, pdf: Path) -> None:
    asyncio.run(meetings.upload_attachment(APP_ID, str(pdf)))
    assert fake_api.calls[0][1]["data"] == {"is_comparison_offer": "false"}


def test_upload_filename_override_drops_directories(
    fake_api: _FakeApi, tmp_path: Path
) -> None:
    p = tmp_path / "tmp-123"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 16)
    asyncio.run(meetings.upload_attachment(APP_ID, str(p), filename="../x/Beleg.PNG"))
    name, _, mime = fake_api.calls[0][1]["files"]["file"]
    assert (name, mime) == ("Beleg.PNG", "image/png")


def test_upload_expands_home(
    fake_api: _FakeApi, pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(pdf.parent))
    asyncio.run(meetings.upload_attachment(APP_ID, f"~/{pdf.name}"))
    assert fake_api.calls[0][1]["files"]["file"][0] == pdf.name


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("missing.pdf", None, "file not found"),
        ("empty.pdf", b"", "file is empty"),
        ("script.exe", b"MZ", "is not allowed"),
        ("noext", b"x", "'(none)' is not allowed"),
    ],
)
def test_upload_rejects_before_sending(
    fake_api: _FakeApi, tmp_path: Path, name: str, content: bytes | None, message: str
) -> None:
    p = tmp_path / name
    if content is not None:
        p.write_bytes(content)
    with pytest.raises(ApiError) as err:
        asyncio.run(meetings.upload_attachment(APP_ID, str(p)))
    assert err.value.status == 400
    assert message in err.value.message
    assert fake_api.calls == []


def test_upload_rejects_a_directory(fake_api: _FakeApi, tmp_path: Path) -> None:
    with pytest.raises(ApiError, match="file not found"):
        asyncio.run(meetings.upload_attachment(APP_ID, str(tmp_path)))
    assert fake_api.calls == []


def test_upload_rejects_more_than_the_cap(fake_api: _FakeApi, tmp_path: Path) -> None:
    p = tmp_path / "big.pdf"
    with p.open("wb") as f:
        f.truncate(meetings.ATTACHMENT_MAX_BYTES + 1)
    with pytest.raises(ApiError, match="at most"):
        asyncio.run(meetings.upload_attachment(APP_ID, str(p)))
    assert fake_api.calls == []


def test_upload_rejects_an_unreadable_file(
    fake_api: _FakeApi, pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `os.access` instead of chmod: root reads a mode-0 file, and CI may run as root.
    monkeypatch.setattr(meetings.os, "access", lambda path, mode: False)
    with pytest.raises(ApiError, match="not readable"):
        asyncio.run(meetings.upload_attachment(APP_ID, str(pdf)))
    assert fake_api.calls == []


# --- The real ApiClient on a mock transport -------------------------------------------


class _Wire:
    """A mock transport that records every request and answers from a handler."""

    def __init__(self, handler: Any) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        return self._handler(request, len(self.requests))


def _client(monkeypatch: pytest.MonkeyPatch, wire: _Wire) -> ApiClient:
    client = ApiClient(Config(base_url="https://stupa.example", scope="read"))
    client._client = httpx.AsyncClient(
        base_url="https://stupa.example/api", transport=httpx.MockTransport(wire)
    )
    tokens = iter(["tok-1", "tok-2"])

    async def _token(*, force_login: bool = False) -> str:
        return next(tokens)

    monkeypatch.setattr(client, "_token", _token)
    monkeypatch.setattr(_common, "_client", client)
    return client


def _parts(request: httpx.Request) -> dict[str, Any]:
    """Parse a multipart/form-data body into {name: (filename, content type, bytes)}."""
    head = f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode()
    msg = BytesParser(policy=email_default).parsebytes(head + request.content)
    assert msg.is_multipart()
    out: dict[str, Any] = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        out[name] = (
            part.get_filename(),
            part.get_content_type() if part.get("content-type") else None,
            part.get_payload(decode=True),
        )
    return out


def test_upload_wire_format(monkeypatch: pytest.MonkeyPatch, pdf: Path) -> None:
    body = {
        "id": ATT_ID,
        "filename": "Angebot_1.pdf",
        "mime": "application/pdf",
        "size": len(PDF),
        "scanned": False,
        "is_comparison_offer": True,
    }
    wire = _Wire(lambda req, n: httpx.Response(201, json=body))
    _client(monkeypatch, wire)
    out = asyncio.run(
        meetings.upload_attachment(
            APP_ID, str(pdf), field_key="offer", is_comparison_offer=True
        )
    )
    assert out == body
    (req,) = wire.requests
    assert req.method == "POST"
    assert req.url.path == f"/api/applications/{APP_ID}/attachments"
    assert req.headers["authorization"] == "Bearer tok-1"
    assert req.headers["content-type"].startswith("multipart/form-data; boundary=")
    assert _parts(req) == {
        "file": ("Angebot 1.pdf", "application/pdf", PDF),
        "is_comparison_offer": (None, None, b"true"),
        "field_key": (None, None, b"offer"),
    }


def test_upload_maps_problem_detail(monkeypatch: pytest.MonkeyPatch, pdf: Path) -> None:
    wire = _Wire(
        lambda req, n: httpx.Response(
            415, json={"title": "Unsupported Media Type", "detail": "type mismatch"}
        )
    )
    _client(monkeypatch, wire)
    with pytest.raises(ApiError) as err:
        asyncio.run(meetings.upload_attachment(APP_ID, str(pdf)))
    assert (err.value.status, err.value.message) == (415, "type mismatch")


def _download(content: bytes, name: str = "Angebot_1.pdf") -> Any:
    def handler(req: httpx.Request, n: int) -> httpx.Response:
        return httpx.Response(
            200,
            content=content,
            headers={
                "content-type": "application/pdf",
                "content-disposition": f'attachment; filename="{name}"',
            },
        )

    return handler


def test_download_to_a_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    wire = _Wire(_download(PDF * 5000))
    _client(monkeypatch, wire)
    target = tmp_path / "out.pdf"
    out = asyncio.run(meetings.download_attachment(ATT_ID, str(target)))
    assert target.read_bytes() == PDF * 5000
    assert out == {
        "path": str(target.resolve()),
        "filename": "Angebot_1.pdf",
        "mime": "application/pdf",
        "size": len(PDF) * 5000,
    }
    (req,) = wire.requests
    assert (req.method, req.url.path) == ("GET", f"/api/attachments/{ATT_ID}/download")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.pdf"]


def test_download_into_a_directory_uses_the_stored_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _client(monkeypatch, _Wire(_download(PDF, name="../../etc/Beleg.pdf")))
    out = asyncio.run(meetings.download_attachment(ATT_ID, str(tmp_path)))
    assert out["path"] == str((tmp_path / "Beleg.pdf").resolve())
    assert (tmp_path / "Beleg.pdf").read_bytes() == PDF


def test_download_keeps_an_existing_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wire = _Wire(_download(PDF))
    _client(monkeypatch, wire)
    target = tmp_path / "out.pdf"
    target.write_bytes(b"old")
    with pytest.raises(ApiError, match="overwrite"):
        asyncio.run(meetings.download_attachment(ATT_ID, str(target)))
    assert target.read_bytes() == b"old"
    assert wire.requests == []
    asyncio.run(meetings.download_attachment(ATT_ID, str(target), overwrite=True))
    assert target.read_bytes() == PDF


def test_download_keeps_an_existing_file_in_a_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _client(monkeypatch, _Wire(_download(PDF, name="a.pdf")))
    (tmp_path / "a.pdf").write_bytes(b"old")
    with pytest.raises(ApiError, match="overwrite"):
        asyncio.run(meetings.download_attachment(ATT_ID, str(tmp_path)))
    assert (tmp_path / "a.pdf").read_bytes() == b"old"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.pdf"]


def test_download_needs_an_existing_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wire = _Wire(_download(PDF))
    _client(monkeypatch, wire)
    with pytest.raises(ApiError, match="directory not found"):
        asyncio.run(meetings.download_attachment(ATT_ID, str(tmp_path / "no" / "x.pdf")))
    assert wire.requests == []


def test_download_while_scanning_raises_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wire = _Wire(
        lambda req, n: httpx.Response(409, json={"detail": "Attachment is being scanned."})
    )
    _client(monkeypatch, wire)
    with pytest.raises(ApiError) as err:
        asyncio.run(meetings.download_attachment(ATT_ID, str(tmp_path / "x.pdf")))
    assert (err.value.status, err.value.message) == (409, "Attachment is being scanned.")
    assert list(tmp_path.iterdir()) == []


def test_download_retries_once_after_401(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ok = _download(PDF)
    wire = _Wire(lambda req, n: httpx.Response(401) if n == 1 else ok(req, n))
    _client(monkeypatch, wire)
    asyncio.run(meetings.download_attachment(ATT_ID, str(tmp_path / "x.pdf")))
    assert [r.headers["authorization"] for r in wire.requests] == [
        "Bearer tok-1",
        "Bearer tok-2",
    ]
    assert (tmp_path / "x.pdf").read_bytes() == PDF


def test_download_rejects_a_path_in_the_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wire = _Wire(_download(PDF))
    _client(monkeypatch, wire)
    with pytest.raises(ApiError, match="traversal"):
        asyncio.run(meetings.download_attachment("../admin", str(tmp_path / "x.pdf")))
    assert wire.requests == []
