"""pytex render service — thin FastAPI wrapper around ``pytex_api.render_blob`` (T-21).

The platform generates Markdown server-side and needs a PDF back; pytex
ships no REST surface, so this container exposes ``POST /render`` (and a
``/health`` probe) over the blob API. The exact ``pytex-preprocessor`` version
that ships is pinned in ``requirements.txt`` / ``pyproject.toml`` and surfaced
at runtime via ``importlib.metadata`` (see ``_PYTEX_VERSION`` below) so the
service version string never drifts from the installed renderer.

Blob in / blob out: POST the Markdown source as the raw request body, pick the
kinds / trust / variant via query params, get an ``application/pdf`` (or
``text/plain`` ``.tex``) back. No filesystem is exposed to the caller — every
build runs in a per-request temp dir inside the library.

Design choices (SDS overview §1, deployment §1):
* The service is internal-only (compose ``internal`` network, no host port) and
  is fed first-party, app-generated documents, so the default trust level is
  ``trusted`` — this unlocks the tectonic bundle/biber auto-download on the very
  first build, after which the ``pytex_cache`` volume keeps subsequent builds
  offline. Override per request via ``?trust_level=``.
* The variant (``report`` / ``protocol-stupa`` / ``protocol-asta`` / …) defaults
  to ``None`` so the library auto-detects it from the document's YAML
  frontmatter; an explicit ``?variant=`` overrides that.
* Errors are mapped to status codes and every detail string is scrubbed of
  absolute filesystem paths, so no internal path or stacktrace leaks to clients
  (``LimitError`` → 413, ``TrustError`` / ``CompileError`` / ``ApiError`` → 400,
  anything else → 500).
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

# --- configurable defaults -------------------------------------------------
# App-generated docs are first-party; default to a real PDF built at full trust.
_DEFAULT_OUTPUT = os.environ.get("PYTEX_DEFAULT_OUTPUT", "pdf").lower()
_DEFAULT_TRUST = os.environ.get("PYTEX_DEFAULT_TRUST", "trusted").lower()
# Hard ceiling on the body we even read, in front of the library's input cap;
# keeps a giant upload out of memory. The library cap is aligned below.
_MAX_BODY_BYTES = int(os.environ.get("PYTEX_MAX_BODY_BYTES", str(4 * 1024 * 1024)))
# Compile wall-clock/cpu kill (seconds). The library default of 30 s is too tight
# for the FIRST trusted build: tectonic lazily downloads its LaTeX bundle into
# the cache volume on that run and gets killed mid-download — every retry starts
# over and the render never succeeds. 120 s lets the warm-up complete; cached
# builds finish in a few seconds anyway.
_WALL_TIMEOUT_S = float(os.environ.get("PYTEX_WALL_TIMEOUT_S", "120"))
_CPU_TIMEOUT_S = float(os.environ.get("PYTEX_CPU_TIMEOUT_S", "120"))
_LIMITS = BuildLimits(
    wall_timeout_s=_WALL_TIMEOUT_S,
    cpu_timeout_s=_CPU_TIMEOUT_S,
    # Align the library's input cap with the HTTP body cap — otherwise bodies
    # between 2 MiB (library default) and PYTEX_MAX_BODY_BYTES still 413.
    max_input_bytes=_MAX_BODY_BYTES,
)

# Protokoll-Titelseite: pytex rendert nur seine fest verdrahteten
# Frontmatter-Keys als Daten-Zeilen — »Beschlussfähigkeit« kennt es nicht.
# Die Zeilen-Tabelle ist ein Modul-Tuple, das `_data_lines` zur Laufzeit liest;
# wir erweitern sie hier (Wrapper-Patch statt Paket-Fork, #protocol-quorum).
from pytex_markdown.protocol import document as _protocol_document  # noqa: E402

# Fail loud, not silent: if a future pytex bump renames this private attribute
# the patch must abort container start-up rather than quietly drop the extra
# title-page rows. The silent existence check below is only a per-label
# idempotency guard against re-applying on re-import.
assert hasattr(_protocol_document, "_SCALAR_ROWS"), (
    "pytex-preprocessor no longer exposes `_protocol_document._SCALAR_ROWS`; "
    "the protocol title-page patch must be re-validated against the new version"
)

for _label, _keys in (
    # Gremium als Titelseiten-Daten-Zeile (#14) — pytex kennt den Key nicht nativ.
    ("Gremium", ("gremium",)),
    ("Beschlussfähigkeit", ("beschlussfaehigkeit", "beschlussfähigkeit")),
):
    if not any(label == _label for label, _ in _protocol_document._SCALAR_ROWS):
        _protocol_document._SCALAR_ROWS = (
            *_protocol_document._SCALAR_ROWS,
            (_label, _keys),
        )

# Surface the installed renderer version so the service version string can never
# drift from what actually ships (AUD-061). Fall back to "unknown" only if the
# package metadata is somehow absent (e.g. running from a raw checkout).
try:
    _PYTEX_VERSION = _pkg_version("pytex-preprocessor")
except PackageNotFoundError:  # pragma: no cover - metadata always present in the image
    _PYTEX_VERSION = "unknown"

app = FastAPI(title="pytex render service", version=_PYTEX_VERSION)

# Strip absolute filesystem paths (/home/..., /tmp/pytex-api-...) out of any
# error detail before it reaches the client. Anchored to the known container
# root prefixes only, so legitimate slash-containing detail (LaTeX command
# fragments like /linewidth, fractions, URL path segments) survives intact.
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
    # Reject oversized uploads from the declared Content-Length *before* reading
    # the body into memory, so a giant POST never gets buffered. A missing or
    # malformed header falls through to the post-read guard below.
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > _MAX_BODY_BYTES:
                return JSONResponse(
                    {"error": f"request body exceeds {_MAX_BODY_BYTES} bytes"},
                    status_code=413,
                )
        except ValueError:
            pass  # malformed header; defensive fall-through to read + length check

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
        # Input / output / build-resource cap exceeded.
        return JSONResponse({"error": _scrub(str(exc))}, status_code=413)
    except (TrustError, CompileError, ApiError) as exc:
        # Policy rejection or build failure -> client error, scrubbed.
        return JSONResponse({"error": _scrub(str(exc))}, status_code=400)
    except Exception:
        # Never leak an internal stacktrace / path.
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
