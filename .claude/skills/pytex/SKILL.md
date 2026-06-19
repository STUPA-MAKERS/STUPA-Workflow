---
name: pytex
description: Internal-only Markdown→PDF/LaTeX render microservice — a thin FastAPI wrapper (app.py) around pytex_api.render_blob_async (pytex-preprocessor 1.0.0 + tectonic). Single POST /render route, trust levels untrusted/sandboxed/trusted, CD variants report/protocol-stupa/protocol-asta/report-makers/plain. Use when working on PDF/protocol rendering, the /render contract, tectonic/cache/Dockerfile, or the backend PytexClient in pytex/ and backend/app/modules/pdf.
---

# pytex render service — `pytex`

**Does:** Exposes a single internal HTTP endpoint that turns server-generated Markdown (raw request body) into a PDF (or `.tex`) via `pytex_api.render_blob_async`, which drives tectonic/biber. pytex-preprocessor ships no REST surface, so this container is the one wrapper the platform's PDF/protocol modules call.

**Key files:**
- `app.py` — the entire service: FastAPI app, `POST /render`, `GET /health`, enum parsing, body-size guards, error→status mapping, path-scrubbing, and a runtime monkeypatch adding `Gremium`/`Beschlussfähigkeit` rows to pytex's protocol title page (`_protocol_document._SCALAR_ROWS`).
- `warmup.py` — build-time cache warm-up; renders one realistic doc per protocol variant (asta/stupa) to pull the tectonic bundle + LaTeX packages into `/cache-seed`.
- `entrypoint.sh` — copies `/cache-seed` into the mounted `/cache` volume (missing-only), then `exec uvicorn app:app --host 0.0.0.0 --port 8099`.
- `inkscape-shim.sh` — installed as `/usr/local/bin/inkscape`; maps pytex's `inkscape … --export-type=pdf` SVG-logo call onto `rsvg-convert` (librsvg) so the image stays slim.
- `Dockerfile` — `python:3.13-slim`; bakes a pinned, sha256-verified tectonic musl binary onto PATH (no `curl|sh`); installs fontconfig/dejavu/librsvg2-bin; runs warm-up (3 retries); drops to uid 10001 `pytex`; `XDG_CACHE_HOME=/cache`; `EXPOSE 8099`.
- `pyproject.toml` — pins `pytex-preprocessor==1.0.0`; only `app.py` is packaged; ruff + basedpyright; pytest `integration` marker.
- `tests/conftest.py` — `RenderRecorder` fake (monkeypatches `render_blob_async`) + `make_result`/`client` fixtures.
- `tests/test_render.py` — contract tests (mocked backend): success shape, forwarding, body limits, enum/error map. `tests/test_integration.py` — real md→tex per variant (no tectonic) + md→pdf (skipped unless `tectonic` on PATH). `tests/test_health.py` — health probe.
- `README.md` — endpoint/param/env/error tables.

**Domain / data model:** No database, no persistence. Stateless per request: each build runs in a per-request temp dir inside the library; the only durable state is the `pytex_cache` volume at `/cache` (tectonic bundle + LaTeX packages). Library types come from `pytex_api`: `BuildRequest` (source bytes, `input_kind`, `output_kind`, `trust`, `variant`, `limits`), `BuildResult` (`output` bytes, `output_kind`, `log`, `warnings`, `duration_s`), `BuildLimits` (`wall_timeout_s`, `cpu_timeout_s`, `max_input_bytes`). Enums: `InputKind` (`md`/`tex`/`py`; `md`=`InputKind.MARKDOWN`), `OutputKind` (`tex`/`pdf`), `TrustLevel` (`untrusted`/`sandboxed`/`trusted`). Variants are strings auto-detected from YAML frontmatter when omitted: `report`, `protocol-stupa`, `protocol-asta`, `report-makers`, `plain`. Errors: `LimitError`, `TrustError`, `CompileError`, `ApiError`.

**API surface:**
- `POST /render` — source = raw request body (Markdown bytes); controls = query params `input_kind` (md|tex|py, default `md`), `output_kind` (tex|pdf, default `PYTEX_DEFAULT_OUTPUT`=pdf), `trust_level` (untrusted|sandboxed|trusted, default `PYTEX_DEFAULT_TRUST`=trusted), `variant` (default None ⇒ frontmatter auto-detect). Returns `application/pdf` (`Content-Disposition: inline; filename="document.pdf"`) or `text/plain; charset=utf-8` for `.tex`. Always sets `X-Render-Duration-Seconds` and `X-Warnings`.
- `GET /health` — `{"status": "ok"}`, dependency-free; drives the compose healthcheck.

Error map (every detail scrubbed of absolute paths via `_PATH_RE` → `<path>`): empty body / bad enum → 400; body > `PYTEX_MAX_BODY_BYTES` → 413 (checked against `Content-Length` before read, then again after read); `LimitError` → 413; `TrustError`/`CompileError`/`ApiError` → 400; anything else → 500 `{"error":"internal render error"}` (never leaks stacktrace).

**Conventions & gotchas:**
- **Internal-only, egress-isolated.** No host port. In `deploy/docker-compose.yml` pytex sits on `pytex_net` (`internal: true`, no egress); api/worker reach it over that net plus `internal`. Never publish `8099` or expose it outside `pytex_net`/`internal` — the `trusted` default runs the full tectonic/biber shell-out path. README's warning is load-bearing.
- **Default `trusted` is deliberate** because inputs are first-party, app-generated. The first trusted build lazily downloads the tectonic bundle; warm-up + the 120 s wall/cpu timeout (`_LIMITS`, overriding the library's 30 s) exist so that first build/download completes — cached builds finish in seconds.
- **Caller-side downgrade:** the backend `PytexClient` (`backend/app/modules/pdf/pytex_client.py`) passes `trust_level="untrusted"` for user-authored Markdown (protocol/TOP bodies) to sandbox the build and block pytex's Markdown `eval` escape; `trusted` only for fully app-generated docs. Configured via `Settings.pytex_url` (`http://pytex:8099`), `pytex_trust`, `pytex_timeout_seconds`.
- **Body cap is two-stage** and the library's `max_input_bytes` is aligned to `PYTEX_MAX_BODY_BYTES` (default 4 MiB) so bodies between the library's 2 MiB default and the HTTP cap don't spuriously 413.
- **Title-page patch:** pytex 1.0.6 only renders its hard-wired frontmatter keys; `app.py` appends `Gremium` and `Beschlussfähigkeit` rows to `_protocol_document._SCALAR_ROWS` at import (wrapper patch, not a fork). Re-check after any `pytex-preprocessor` bump.
- **SVG logos** go through the `inkscape` shim → `rsvg-convert`; any unexpected inkscape invocation fails loudly rather than guessing. CD-specific fonts (e.g. Blender for STUPA) must be added to the image separately.
- **Tests:** unit tests mock `render_blob_async` (no tectonic). md→tex integration runs in CI unconditionally; md→pdf is skipped unless `tectonic` is on PATH (opt-in via `RUN_PYTEX_INTEGRATION=1`). To bump tectonic, update version + both arch sha256 sums in the Dockerfile.

**Related:** be-pdf, be-protocol
