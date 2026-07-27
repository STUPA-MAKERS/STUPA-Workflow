"""pytex render service: a thin FastAPI wrapper around `pytex_api.render_blob`.

The service exposes `POST /render` and a `/health` probe. Blob in, blob out.
POST the source as the raw request body. Pick the kinds, the trust level and the
variant with query params. The service answers with `application/pdf`, or with
`text/plain` for `.tex`. Every build runs in a per-request temp directory inside
the library. The caller reaches no filesystem.

The service is internal-only and it renders first-party, app-generated documents
only, so the default trust level is `trusted`. `variant` defaults to `None`,
which makes the library auto-detect the variant from the YAML frontmatter of the
document. The service strips absolute filesystem paths out of every error
detail. No internal path and no stacktrace leaks to a client.
"""

from __future__ import annotations

import os
import re
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

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

# App-generated documents are first-party, so default to a real PDF at full trust.
_DEFAULT_OUTPUT = os.environ.get("PYTEX_DEFAULT_OUTPUT", "pdf").lower()
_DEFAULT_TRUST = os.environ.get("PYTEX_DEFAULT_TRUST", "trusted").lower()
# Hard ceiling on the body the service reads at all, in front of the input cap of
# the library. It keeps a giant upload out of memory. The code aligns the library
# cap with it below.
_MAX_BODY_BYTES = int(os.environ.get("PYTEX_MAX_BODY_BYTES", str(4 * 1024 * 1024)))
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
    def __init__(self, detail: str) -> None:
        self.detail = detail


def _parse_enum[E: (InputKind, OutputKind, TrustLevel)](
    value: str, enum: type[E], field: str
) -> E:
    try:
        return enum(value.lower())
    except ValueError:
        allowed = ", ".join(m.value for m in enum)
        raise _BadRequest(f"invalid {field} {value!r}; allowed: {allowed}") from None


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
    """Render the raw request body (Markdown) to a PDF or LaTeX blob."""
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

    source = await request.body()
    if not source:
        return JSONResponse(
            {"error": "empty request body; POST the source as the raw body"},
            status_code=400,
        )
    if len(source) > _MAX_BODY_BYTES:
        return JSONResponse(
            {"error": f"request body exceeds {_MAX_BODY_BYTES} bytes"},
            status_code=413,
        )

    try:
        ik = _parse_enum(input_kind, InputKind, "input_kind")
        ok = _parse_enum(output_kind or _DEFAULT_OUTPUT, OutputKind, "output_kind")
        tl = _parse_enum(trust_level or _DEFAULT_TRUST, TrustLevel, "trust_level")
    except _BadRequest as exc:
        return JSONResponse({"error": exc.detail}, status_code=400)

    req = BuildRequest(
        source=source,
        input_kind=ik,
        output_kind=ok,
        trust=tl,
        variant=variant,
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
