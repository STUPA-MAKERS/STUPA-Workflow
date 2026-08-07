"""pytex render service: a thin FastAPI wrapper around `pytex_api.render_blob`.

The service exposes `POST /render` and a `/health` probe. Blob in, blob out.
POST the source as the raw request body. Pick the kinds, the trust level and the
variant with query params. The service answers with `application/pdf`, or with
`text/plain` for `.tex`. Every build runs in a per-request temp directory inside
the library. The caller reaches no filesystem.

`POST /render` also accepts `multipart/form-data`: the source in the `source`
field, a JSON object in `config`, and one file part per binary asset in the
repeated `assets` field, named after the file name of its part.

The service is internal-only and it renders first-party, app-generated documents
only, so the default trust level is `trusted`. `variant` defaults to `None`,
which makes the library auto-detect the variant from the YAML frontmatter of the
document. The service strips absolute filesystem paths out of every error
detail. No internal path and no stacktrace leaks to a client.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from typing import Final

from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pytex_api import (
    ApiError,
    BuildLimits,
    BuildRequest,
    CompileError,
    InputKind,
    LimitError,
    OutputKind,
    TrustError,
    TrustLevel,
    render_blob_async,
)
from python_multipart.exceptions import FormParserError
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException

# App-generated documents are first-party, so default to a real PDF at full trust.
_DEFAULT_OUTPUT = os.environ.get("PYTEX_DEFAULT_OUTPUT", "pdf").lower()
_DEFAULT_TRUST = os.environ.get("PYTEX_DEFAULT_TRUST", "trusted").lower()
# Hard ceiling on the body the service reads at all, in front of the input cap of
# the library. It keeps a giant upload out of memory. The code aligns the library
# cap with it below.
_MAX_BODY_BYTES = int(os.environ.get("PYTEX_MAX_BODY_BYTES", str(4 * 1024 * 1024)))
# Caps on the asset channel, under the total cap above.
_MAX_ASSETS = int(os.environ.get("PYTEX_MAX_ASSETS", "16"))
_MAX_ASSET_BYTES = int(os.environ.get("PYTEX_MAX_ASSET_BYTES", str(2 * 1024 * 1024)))
# Above the asset cap, so the count check below still answers its clear 413.
_MAX_PARTS = _MAX_ASSETS + 2
_MAX_FIELDS = 8
# Compile wall-clock and cpu kill (seconds). The 30 s default of the library kills
# the first trusted build during the bundle download. 120 s lets that warm-up
# finish, and a cached build takes a few seconds anyway.
_WALL_TIMEOUT_S = float(os.environ.get("PYTEX_WALL_TIMEOUT_S", "120"))
_CPU_TIMEOUT_S = float(os.environ.get("PYTEX_CPU_TIMEOUT_S", "120"))
_LIMITS = BuildLimits(
    wall_timeout_s=_WALL_TIMEOUT_S,
    cpu_timeout_s=_CPU_TIMEOUT_S,
    # Align the input cap of the library with the HTTP body cap. Otherwise a body
    # between 2 MiB (the library default) and PYTEX_MAX_BODY_BYTES still gets a 413.
    max_input_bytes=_MAX_BODY_BYTES,
)

# Protocol title page: pytex renders only its hard-wired frontmatter keys as data
# rows. The wrapper extends the module-level row table here. This is a patch, not
# a fork.
from pytex_markdown.protocol import document as _protocol_document  # noqa: E402

# Fail loud at start-up when a future pytex bump renames this private attribute.
# The existence check below is only an idempotency guard against a re-import.
assert hasattr(_protocol_document, "_SCALAR_ROWS"), (
    "pytex-preprocessor no longer exposes `_protocol_document._SCALAR_ROWS`; "
    "the protocol title-page patch must be re-validated against the new version"
)

for _label, _keys in (
    ("Gremium", ("gremium",)),
    ("Beschlussfähigkeit", ("beschlussfaehigkeit", "beschlussfähigkeit")),
):
    if not any(label == _label for label, _ in _protocol_document._SCALAR_ROWS):
        _protocol_document._SCALAR_ROWS = (
            *_protocol_document._SCALAR_ROWS,
            (_label, _keys),
        )

# Report the installed renderer version, so the service version string cannot
# drift from what ships. The value is "unknown" only when the metadata is absent.
try:
    _PYTEX_VERSION = _pkg_version("pytex-preprocessor")
except PackageNotFoundError:  # pragma: no cover - metadata always present in the image
    _PYTEX_VERSION = "unknown"

app = FastAPI(title="pytex render service", version=_PYTEX_VERSION)

# Strip absolute filesystem paths out of every error detail before it reaches the
# client. The pattern anchors on the known container root prefixes only. Detail
# with a legitimate slash (for example /linewidth or a URL segment) stays intact.
_PATH_RE = re.compile(r"/(?:tmp|app|cache|home|var|usr|root|opt|etc)/[^\s:'\"]*")


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


def _parse_enum[E: (InputKind, OutputKind, TrustLevel)](
    value: str, enum: type[E], field_name: str
) -> E:
    try:
        return enum(value.lower())
    except ValueError:
        allowed = ", ".join(m.value for m in enum)
        raise _BadRequest(
            f"invalid {field_name} {value!r}; allowed: {allowed}"
        ) from None


# The multipart contract: these three field names and no other.
_MULTIPART_TYPE: Final[str] = "multipart/form-data"
_SOURCE_FIELD: Final[str] = "source"
_CONFIG_FIELD: Final[str] = "config"
_ASSETS_FIELD: Final[str] = "assets"


@dataclass(frozen=True, slots=True)
class _Payload:
    """What one render request carries, whatever its wire shape is."""

    source: bytes
    config: dict[str, object] = field(default_factory=dict)
    assets: dict[str, bytes] = field(default_factory=dict)


async def _part_bytes(value: UploadFile | str) -> bytes:
    """Read one multipart part, whether it arrived as a file part or a field."""
    if isinstance(value, str):
        return value.encode("utf-8")
    return await value.read()


def _parse_config(raw: bytes) -> dict[str, object]:
    """Parse the `config` part into the document-class parameters.

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
    # `json.loads` builds a JSON object as a `dict` with `str` keys only.
    return parsed  # pyright: ignore[reportUnknownVariableType]


def _asset_name(value: UploadFile | str) -> str:
    """Return the file name of an asset part.

    The private `pytex_api._security.validate_asset_name` owns the name rule
    (the exported `filter_assets` applies it); the route maps its `TrustError`
    to a 400.

    Raises:
        _BadRequest: The part is a plain field, or it carries no file name.
    """
    if isinstance(value, str) or not value.filename:
        raise _BadRequest(
            f"each `{_ASSETS_FIELD}` part must be a file part with a file name"
        )
    return value.filename


async def _read_multipart(request: Request) -> _Payload:
    """Read `source`, `config` and the repeated `assets` parts out of the form.

    Raises:
        _BadRequest: The body is malformed, it names an unknown field, or the
            `config` part is not a JSON object.
    """
    try:
        # Starlette defaults to 1000 files and 1000 fields; this contract needs neither.
        form = await request.form(
            max_part_size=_MAX_BODY_BYTES,
            max_files=_MAX_PARTS,
            max_fields=_MAX_FIELDS,
        )
    except HTTPException as exc:
        # Inside an app, starlette rewrites `MultiPartException` to a 400 `HTTPException`.
        raise _BadRequest(f"malformed multipart body: {exc.detail}") from None
    except FormParserError as exc:
        # A broken part header does not pass through the starlette wrapper.
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
        _TooLarge: The payload carries too many assets, an asset that is too
            big, or more bytes in total than the body cap allows.
    """
    if len(payload.assets) > _MAX_ASSETS:
        raise _TooLarge(f"request carries more than {_MAX_ASSETS} assets")
    for name, data in payload.assets.items():
        if len(data) > _MAX_ASSET_BYTES:
            raise _TooLarge(f"asset {name!r} exceeds {_MAX_ASSET_BYTES} bytes")
    total = len(payload.source) + sum(len(d) for d in payload.assets.values())
    if total > _MAX_BODY_BYTES:
        raise _TooLarge(f"request body exceeds {_MAX_BODY_BYTES} bytes")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/render")
async def render(
    request: Request,
    input_kind: str = Query("md", description="md | tex | py"),
    output_kind: str | None = Query(None, description="tex | pdf (default: server)"),
    trust_level: str | None = Query(
        None, description="untrusted | sandboxed | trusted (default: server)"
    ),
    variant: str | None = Query(
        None, description="document variant; None => auto-detect from frontmatter"
    ),
) -> Response:
    """Render the request source (Markdown) to a PDF or LaTeX blob.

    The source is the raw request body, or the `source` field of a multipart
    body that may also carry `config` and repeated `assets` parts.
    """
    # Reject an oversized upload from the declared Content-Length before the
    # service buffers the body. A missing or malformed header falls through to
    # the guard after the read.
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > _MAX_BODY_BYTES:
                return JSONResponse(
                    {"error": f"request body exceeds {_MAX_BODY_BYTES} bytes"},
                    status_code=413,
                )
        except ValueError:
            pass  # malformed header, fall through to the read and the length check

    try:
        payload = await _read_payload(request)
        _enforce_limits(payload)
        ik = _parse_enum(input_kind, InputKind, "input_kind")
        ok = _parse_enum(output_kind or _DEFAULT_OUTPUT, OutputKind, "output_kind")
        tl = _parse_enum(trust_level or _DEFAULT_TRUST, TrustLevel, "trust_level")
    except _BadRequest as exc:
        return JSONResponse({"error": _scrub(exc.detail)}, status_code=400)
    except _TooLarge as exc:
        return JSONResponse({"error": _scrub(exc.detail)}, status_code=413)

    req = BuildRequest(
        source=payload.source,
        input_kind=ik,
        output_kind=ok,
        trust=tl,
        variant=variant,
        config=payload.config,
        assets=payload.assets,
        limits=_LIMITS,
    )

    try:
        result = await render_blob_async(req)
    except LimitError as exc:
        # The build hit the input cap, the output cap or a build-resource cap.
        return JSONResponse({"error": _scrub(str(exc))}, status_code=413)
    except (TrustError, CompileError, ApiError) as exc:
        return JSONResponse({"error": _scrub(str(exc))}, status_code=400)
    except Exception:
        # Never leak an internal stacktrace or path.
        return JSONResponse({"error": "internal render error"}, status_code=500)

    headers = {
        "X-Render-Duration-Seconds": f"{result.duration_s:.3f}",
        "X-Warnings": str(len(result.warnings)),
    }
    if result.output_kind is OutputKind.PDF:
        return Response(
            content=result.output,
            media_type="application/pdf",
            headers={
                **headers,
                "Content-Disposition": 'inline; filename="document.pdf"',
            },
        )
    return PlainTextResponse(
        result.output.decode("utf-8", errors="replace"), headers=headers
    )
