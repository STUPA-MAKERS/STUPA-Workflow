"""typst render service: protocol Markdown in, PDF out.

The service exposes `POST /render` and a `/health` probe. POST the Markdown
source as the raw request body. The optional `variant` query parameter picks
the default logos (`protocol-stupa`, `protocol-asta`, `protocol`). Without
it, the service reads them from the `gremium` frontmatter key.

`POST /render` also accepts `multipart/form-data`. That form carries the same
source in the `source` field, a JSON object in the `config` field, and one
file part per binary asset in the repeated `assets` field. The name of an
asset is the file name of its part. A caller uploads the logos of a
corporate design this way and names them in the `logos` or `footer_logos`
config key.

The Markdown never becomes Typst code: the converter turns it into JSON data
and the template reads that data. Typst itself has no shell escape and no
network access, and each compile runs in its own sandbox root with a
wall-clock limit. No filesystem path and no stacktrace reaches a client.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Final

from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse
from python_multipart.exceptions import FormParserError
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException

from .compiler import ASSET_NAME_RE, CompileError, CompileTimeout, TypstCompiler, default_compiler
from .document import build_document
from .frontmatter import FrontmatterError
from .markdown import ConversionError

__all__ = ["app"]

# Hard ceiling on the body the service reads at all. It keeps a giant upload
# out of memory. 32 MiB is the cap that production ran pytex with, after the
# 4 MiB default answered 413 for real protocols with their logos.
_MAX_BODY_BYTES = int(os.environ.get("TYPST_MAX_BODY_BYTES", str(32 * 1024 * 1024)))
# Caps on the asset channel of a multipart request. They sit under the total
# cap, so one huge logo cannot eat the whole budget of a document.
_MAX_ASSETS = int(os.environ.get("TYPST_MAX_ASSETS", "16"))
_MAX_ASSET_BYTES = int(os.environ.get("TYPST_MAX_ASSET_BYTES", str(2 * 1024 * 1024)))
# Compiles in parallel. A compile is CPU-bound, so more than the cores only
# queues work inside the kernel instead of here.
_MAX_CONCURRENCY = int(os.environ.get("TYPST_MAX_CONCURRENCY", "2"))

_compiler: TypstCompiler = default_compiler()
_slots = asyncio.Semaphore(_MAX_CONCURRENCY)

app = FastAPI(title="typst render service", version="0.1.0")

# Strip absolute filesystem paths out of every error detail. The pattern
# anchors on the known container root prefixes only.
_PATH_RE = re.compile(r"/(?:tmp|app|cache|home|var|usr|root|opt|etc|nix)/[^\s:'\"]*")


def _scrub(msg: str) -> str:
    return _PATH_RE.sub("<path>", msg)


class _BadRequest(Exception):
    """The request is malformed. The route answers 400."""

    def __init__(self, detail: str) -> None:
        self.detail = detail


class _TooLarge(Exception):
    """The request passed a size or count cap. The route answers 413."""

    def __init__(self, detail: str) -> None:
        self.detail = detail


# The multipart contract. The service accepts these three field names and no
# other, so the accepted surface stays as narrow as the raw-body one.
_MULTIPART_TYPE: Final[str] = "multipart/form-data"
_SOURCE_FIELD: Final[str] = "source"
_CONFIG_FIELD: Final[str] = "config"
_ASSETS_FIELD: Final[str] = "assets"


@dataclass(frozen=True, slots=True)
class _Payload:
    """What one render request carries, whatever its wire shape is."""

    source: bytes
    config: dict[str, object] = field(default_factory=dict[str, object])
    assets: dict[str, bytes] = field(default_factory=dict[str, bytes])


async def _part_bytes(value: UploadFile | str) -> bytes:
    """Read one multipart part, whether it arrived as a file part or a field."""
    if isinstance(value, str):
        return value.encode("utf-8")
    return await value.read()


def _parse_config(raw: bytes) -> dict[str, object]:
    """Parse the `config` part.

    Raises:
        _BadRequest: The part is not UTF-8, not JSON, or not a JSON object.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _BadRequest(f"config is not valid UTF-8: {exc}") from None
    try:
        parsed: object = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _BadRequest(f"config is not valid JSON: {exc.msg}") from None
    if not isinstance(parsed, dict):
        raise _BadRequest("config must be a JSON object")
    return parsed  # pyright: ignore[reportUnknownVariableType]


def _asset_name(value: UploadFile | str) -> str:
    """Return the checked file name of an asset part.

    Raises:
        _BadRequest: The part is a plain field, carries no file name, or the
            name is not a plain image file name.
    """
    if isinstance(value, str) or not value.filename:
        raise _BadRequest(f"each `{_ASSETS_FIELD}` part must be a file part with a file name")
    name = value.filename
    if not ASSET_NAME_RE.fullmatch(name):
        raise _BadRequest(
            f"invalid asset name {name!r}: use a plain file name with an image extension"
        )
    return name


async def _read_multipart(request: Request) -> _Payload:
    """Read `source`, `config` and the repeated `assets` parts out of the form.

    Raises:
        _BadRequest: The body is malformed, it names an unknown field, or a
            part breaks the contract.
    """
    try:
        # `max_part_size` keeps a single part inside the total body cap even
        # when the request declares no Content-Length (chunked upload).
        form = await request.form(max_part_size=_MAX_BODY_BYTES)
    except MultiPartException as exc:
        raise _BadRequest(f"malformed multipart body: {exc.message}") from None
    except FormParserError as exc:
        # The parser under starlette raises this for a broken part header.
        raise _BadRequest(f"malformed multipart body: {exc}") from None
    try:
        source = b""
        config: dict[str, object] = {}
        assets: dict[str, bytes] = {}
        for key, value in form.multi_items():
            if key == _SOURCE_FIELD:
                source = await _part_bytes(value)
            elif key == _CONFIG_FIELD:
                config = _parse_config(await _part_bytes(value))
            elif key == _ASSETS_FIELD:
                name = _asset_name(value)
                if name in assets:
                    raise _BadRequest(f"duplicate asset name {name!r}")
                assets[name] = await _part_bytes(value)
            else:
                raise _BadRequest(
                    f"unknown multipart field {key!r}; allowed: "
                    f"{_SOURCE_FIELD}, {_CONFIG_FIELD}, {_ASSETS_FIELD}"
                )
    finally:
        await form.close()
    return _Payload(source=source, config=config, assets=assets)


async def _read_payload(request: Request) -> _Payload:
    """Read the request as multipart or as a raw body, whichever it declares.

    Raises:
        _BadRequest: The body is malformed or it carries no source.
    """
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
    if media_type.lower() == _MULTIPART_TYPE:
        payload = await _read_multipart(request)
    else:
        payload = _Payload(source=await request.body())
    if not payload.source:
        raise _BadRequest(
            "empty source; POST the source as the raw body or as the "
            f"multipart `{_SOURCE_FIELD}` field"
        )
    return payload


def _enforce_limits(payload: _Payload) -> None:
    """Check the payload against the asset caps and the total body cap.

    Raises:
        _TooLarge: Too many assets, an asset that is too big, or more bytes in
            total than the body cap allows.
    """
    if len(payload.assets) > _MAX_ASSETS:
        raise _TooLarge(f"request carries more than {_MAX_ASSETS} assets")
    for name, data in payload.assets.items():
        if len(data) > _MAX_ASSET_BYTES:
            raise _TooLarge(f"asset {name!r} exceeds {_MAX_ASSET_BYTES} bytes")
    total = len(payload.source) + sum(len(d) for d in payload.assets.values())
    if total > _MAX_BODY_BYTES:
        raise _TooLarge(f"request body exceeds {_MAX_BODY_BYTES} bytes")


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse({"error": _scrub(detail)}, status_code=status)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/render")
async def render(
    request: Request,
    variant: str | None = Query(
        None, description="protocol-stupa | protocol-asta | protocol; None reads `gremium`"
    ),
) -> Response:
    """Render the protocol Markdown of the request to a PDF."""
    # Reject an oversized upload from the declared Content-Length before the
    # service buffers the body.
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > _MAX_BODY_BYTES:
                return _error(413, f"request body exceeds {_MAX_BODY_BYTES} bytes")
        except ValueError:
            pass  # malformed header: the read and the length check follow

    started = time.monotonic()
    try:
        payload = await _read_payload(request)
        _enforce_limits(payload)
        try:
            source = payload.source.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _BadRequest(f"source is not valid UTF-8: {exc}") from None
        doc = build_document(
            source, variant=variant, config=payload.config, assets=payload.assets.keys()
        )
    except _BadRequest as exc:
        return _error(400, exc.detail)
    except _TooLarge as exc:
        return _error(413, exc.detail)
    except (ConversionError, FrontmatterError) as exc:
        return _error(400, str(exc))

    try:
        async with _slots:
            pdf = await _compiler.compile(doc, payload.assets)
    except CompileTimeout as exc:
        # A document that runs past the limit does so on every retry.
        return _error(413, str(exc))
    except CompileError as exc:
        return _error(400, str(exc))
    except Exception:
        # Never leak an internal stacktrace or path.
        return JSONResponse({"error": "internal render error"}, status_code=500)

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="document.pdf"',
            "X-Render-Duration-Seconds": f"{time.monotonic() - started:.3f}",
        },
    )
