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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, cast

from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse
from python_multipart.exceptions import FormParserError
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException

from .appendix import Appendix, Size, document_assets, merge_appendix, page_sizes
from .compiler import ASSET_NAME_RE, CompileError, CompileTimeout, TypstCompiler, default_compiler
from .document import build_document
from .frontmatter import FrontmatterError
from .markdown import ConversionError

__all__ = ["app"]

# Hard ceiling on the body the service reads at all. It keeps a giant upload
# out of memory. The backend sends the logos, at most 24 MiB of images and at
# most 48 MiB of embedded PDFs (the Anlagen), so 96 MiB leaves room for all.
_MAX_BODY_BYTES = int(os.environ.get("TYPST_MAX_BODY_BYTES", str(96 * 1024 * 1024)))
# Caps on the asset channel of a multipart request. They sit under the total
# cap, so one huge file cannot eat the whole budget of a document. The backend
# sends the logos, at most 48 images of 8 MiB and at most 20 PDFs of 20 MiB, so
# 96 assets of 20 MiB each leave room for all.
_MAX_ASSETS = int(os.environ.get("TYPST_MAX_ASSETS", "96"))
_MAX_ASSET_BYTES = int(os.environ.get("TYPST_MAX_ASSET_BYTES", str(20 * 1024 * 1024)))
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


_MULTIPART_TYPE: Final[str] = "multipart/form-data"


class _Field(StrEnum):
    """The multipart contract.

    The service accepts these three field names and no other, so the accepted
    surface stays as narrow as the raw-body one.
    """

    SOURCE = "source"
    CONFIG = "config"
    ASSETS = "assets"


@dataclass(frozen=True, slots=True)
class _Payload:
    """What one render request carries, whatever its wire shape is."""

    source: bytes
    config: Mapping[str, object] = field(default_factory=dict[str, object])
    assets: Mapping[str, bytes] = field(default_factory=dict[str, bytes])


@dataclass(frozen=True, slots=True)
class _SourcePart:
    """The `source` part of a multipart request."""

    data: bytes


@dataclass(frozen=True, slots=True)
class _ConfigPart:
    """The parsed `config` part of a multipart request."""

    data: dict[str, object]


@dataclass(frozen=True, slots=True)
class _AssetPart:
    """One `assets` part of a multipart request, with its checked file name."""

    name: str
    data: bytes


type _Part = _SourcePart | _ConfigPart | _AssetPart


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
    return parsed


def _asset_name(value: UploadFile | str) -> str:
    """Return the checked file name of an asset part.

    Raises:
        _BadRequest: The part is a plain field, carries no file name, or the
            name is not a plain image file name.
    """
    if isinstance(value, str) or not value.filename:
        raise _BadRequest(f"each `{_Field.ASSETS}` part must be a file part with a file name")
    name = value.filename
    if not ASSET_NAME_RE.fullmatch(name):
        raise _BadRequest(
            f"invalid asset name {name!r}: use a plain file name with an image extension"
        )
    return name


def _repeated_assets(items: Sequence[tuple[str, UploadFile | str]]) -> frozenset[int]:
    """Return the positions of the asset parts whose file name an earlier asset part has."""
    names = [
        value.filename if key == _Field.ASSETS and not isinstance(value, str) else None
        for key, value in items
    ]
    first = {name: index for index, name in reversed(tuple(enumerate(names))) if name}
    return frozenset(index for index, name in enumerate(names) if name and first[name] != index)


async def _read_part(key: str, value: UploadFile | str, repeated: bool) -> _Part:
    """Read one multipart part by its field name.

    Raises:
        _BadRequest: The field name is unknown, or the part breaks the contract.
    """
    match key:
        case _Field.SOURCE:
            return _SourcePart(await _part_bytes(value))
        case _Field.CONFIG:
            return _ConfigPart(_parse_config(await _part_bytes(value)))
        case _Field.ASSETS:
            name = _asset_name(value)
            if repeated:
                raise _BadRequest(f"duplicate asset name {name!r}")
            return _AssetPart(name, await _part_bytes(value))
        case _:
            raise _BadRequest(
                f"unknown multipart field {key!r}; allowed: "
                f"{_Field.SOURCE}, {_Field.CONFIG}, {_Field.ASSETS}"
            )


async def _read_multipart(request: Request) -> _Payload:
    """Read `source`, `config` and the repeated `assets` parts out of the form.

    A repeated `source` or `config` part replaces the earlier one.

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
        items = form.multi_items()
        repeated = _repeated_assets(items)
        parts = [
            await _read_part(key, value, index in repeated)
            for index, (key, value) in enumerate(items)
        ]
    finally:
        await form.close()
    sources = [part.data for part in parts if isinstance(part, _SourcePart)]
    configs = [part.data for part in parts if isinstance(part, _ConfigPart)]
    return _Payload(
        source=sources[-1] if sources else b"",
        config=configs[-1] if configs else {},
        assets={part.name: part.data for part in parts if isinstance(part, _AssetPart)},
    )


async def _read_payload(request: Request) -> _Payload:
    """Read the request as multipart or as a raw body, whichever it declares.

    Raises:
        _BadRequest: The body is malformed or it carries no source.
    """
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
    payload = (
        await _read_multipart(request)
        if media_type.lower() == _MULTIPART_TYPE
        else _Payload(source=await request.body())
    )
    if not payload.source:
        raise _BadRequest(
            "empty source; POST the source as the raw body or as the "
            f"multipart `{_Field.SOURCE}` field"
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


def _document_sizes(documents: Mapping[str, bytes]) -> dict[str, tuple[Size, ...]]:
    """Read the page sizes of each uploaded PDF. A PDF that is no Anlage is left out."""
    sizes = ((doc, page_sizes(data)) for doc, data in documents.items())
    return {doc: found for doc, found in sizes if found is not None}


def _appendix_of(
    doc: Mapping[str, object], sizes: Mapping[str, tuple[Size, ...]]
) -> tuple[Appendix, ...]:
    """Rebuild the Anlagen of a document tree from its `appendix` data."""
    items = cast("list[dict[str, object]]", doc.get("appendix", []))
    return tuple(
        Appendix(
            number=int(cast("int", item["n"])),
            doc=str(item["doc"]),
            name=str(item["name"]),
            pages=sizes[str(item["doc"])],
        )
        for item in items
    )


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
        documents = document_assets(payload.assets)
        sizes = await asyncio.to_thread(_document_sizes, documents)
        doc = build_document(
            source,
            variant=variant,
            config=payload.config,
            assets=payload.assets.keys(),
            documents=sizes,
        )
    except _BadRequest as exc:
        return _error(400, exc.detail)
    except _TooLarge as exc:
        return _error(413, exc.detail)
    except (ConversionError, FrontmatterError) as exc:
        return _error(400, str(exc))

    try:
        async with _slots:
            compiled = await _compiler.compile(doc, payload.assets)
            pdf = await asyncio.to_thread(
                merge_appendix, compiled, _appendix_of(doc, sizes), documents
            )
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
