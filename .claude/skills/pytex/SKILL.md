---
name: pytex
description: Internal-only Markdown→PDF/LaTeX render microservice — a thin FastAPI wrapper (app.py) around pytex_api.render_blob_async (pytex-preprocessor 1.0.0 + tectonic). Single POST /render route, trust levels untrusted/sandboxed/trusted, CD variants report/protocol-stupa/protocol-asta/report-makers/plain. Use when working on PDF/protocol rendering, the /render contract, tectonic/cache/Dockerfile, or the backend PytexClient in pytex/ and backend/app/modules/pdf.
---

# pytex render service — `pytex`

**Does:** Exposes one internal HTTP endpoint. The endpoint turns server-generated Markdown (the raw request body) into a PDF or a `.tex` blob through `pytex_api.render_blob_async`, which drives tectonic/biber. The pytex-preprocessor package ships no REST surface. This container is therefore the one wrapper that the PDF and protocol modules of the platform call.

**Key files:**
- `app.py` — the whole service: FastAPI app, `POST /render`, `GET /health`, enum parsing, body-size guards, error→status mapping, path scrubbing, and a runtime monkeypatch that adds `Gremium` and `Beschlussfähigkeit` rows to the protocol title page of pytex (`_protocol_document._SCALAR_ROWS`).
- `warmup.py` — build-time cache warm-up. It renders one realistic doc per protocol variant (asta/stupa) to pull the tectonic bundle + LaTeX packages into `/cache-seed`.
- `entrypoint.sh` — copies `/cache-seed` into the mounted `/cache` volume (missing-only), then `exec uvicorn app:app --host 0.0.0.0 --port 8099`.
- `inkscape-shim.sh` — installed as `/usr/local/bin/inkscape`. It maps the `inkscape … --export-type=pdf` SVG-logo call of pytex onto `rsvg-convert` (librsvg), which keeps the image small.
- `Dockerfile` — `python:3.13-slim`. It bakes a pinned, sha256-verified tectonic musl binary onto PATH (no `curl|sh`). It installs fontconfig/dejavu/librsvg2-bin, runs the warm-up (3 retries) and drops to uid 10001 `pytex`. It sets `XDG_CACHE_HOME=/cache` and `EXPOSE 8099`.
- `pyproject.toml` — pins `pytex-preprocessor==1.0.0`. It packages only `app.py`. It adds ruff + basedpyright and the pytest `integration` marker.
- `tests/conftest.py` — `RenderRecorder` fake (monkeypatches `render_blob_async`) + `make_result`/`client` fixtures.
- `tests/test_render.py` — contract tests (mocked backend): success shape, forwarding, body limits, enum/error map. `tests/test_integration.py` — real md→tex per variant (no tectonic) + md→pdf (skipped unless `tectonic` on PATH). `tests/test_health.py` — health probe.
- `README.md` — endpoint/param/env/error tables.

**Domain / data model:** No database, no persistence. Every request is stateless. Each build runs in a per-request temp dir inside the library. The only durable state is the `pytex_cache` volume at `/cache` (tectonic bundle + LaTeX packages). Library types come from `pytex_api`: `BuildRequest` (source bytes, `input_kind`, `output_kind`, `trust`, `variant`, `limits`), `BuildResult` (`output` bytes, `output_kind`, `log`, `warnings`, `duration_s`), `BuildLimits` (`wall_timeout_s`, `cpu_timeout_s`, `max_input_bytes`). Enums: `InputKind` (`md`/`tex`/`py`, where `md`=`InputKind.MARKDOWN`), `OutputKind` (`tex`/`pdf`), `TrustLevel` (`untrusted`/`sandboxed`/`trusted`). Variants are strings: `report`, `protocol-stupa`, `protocol-asta`, `report-makers`, `plain`. When you omit the variant, the library reads it from the YAML frontmatter. Errors: `LimitError`, `TrustError`, `CompileError`, `ApiError`.

**API surface:**
- `POST /render` — the source is the raw request body (Markdown bytes). Query params carry the controls: `input_kind` (md|tex|py, default `md`), `output_kind` (tex|pdf, default `PYTEX_DEFAULT_OUTPUT`=pdf), `trust_level` (untrusted|sandboxed|trusted, default `PYTEX_DEFAULT_TRUST`=trusted), `variant` (default None ⇒ frontmatter auto-detect). Returns `application/pdf` (`Content-Disposition: inline; filename="document.pdf"`) or `text/plain; charset=utf-8` for `.tex`. Always sets `X-Render-Duration-Seconds` and `X-Warnings`.
- `GET /health` — `{"status": "ok"}`, dependency-free. It drives the compose healthcheck.

Error map. The service replaces every absolute path in an error detail with `<path>` via `_PATH_RE`. Empty body or bad enum → 400. Body > `PYTEX_MAX_BODY_BYTES` → 413 (checked against `Content-Length` before the read, then again after the read). `LimitError` → 413. `TrustError`/`CompileError`/`ApiError` → 400. Anything else → 500 `{"error":"internal render error"}`, which never leaks a stacktrace.

**Conventions & gotchas:**
- **Internal-only, egress-isolated.** No host port. In `deploy/docker-compose.yml` pytex sits on `pytex_net` (`internal: true`, no egress). The api and worker services reach it over that net plus `internal`. Never publish `8099`. Never expose the service outside `pytex_net`/`internal`, because the `trusted` default runs the full tectonic/biber shell-out path. The warning in the README is load-bearing.
- **The `trusted` default is deliberate** because the inputs are first-party and app-generated. The first trusted build downloads the tectonic bundle lazily. The warm-up and the 120 s wall/cpu timeout (`_LIMITS`) exist so that this first build and its download finish. `_LIMITS` overrides the 30 s of the library. A cached build finishes in seconds.
- **Caller-side downgrade:** the backend `PytexClient` (`backend/app/modules/pdf/pytex_client.py`) passes `trust_level="untrusted"` for user-authored Markdown, which covers protocol and agenda-item bodies. The untrusted level sandboxes the build and blocks the Markdown `eval` escape of pytex. Only fully app-generated docs keep `trusted`. `Settings.pytex_url` (`http://pytex:8099`), `pytex_trust` and `pytex_timeout_seconds` configure the client.
- **The body cap works in two stages.** The service aligns the library `max_input_bytes` with `PYTEX_MAX_BODY_BYTES` (default 4 MiB). A body between the 2 MiB default of the library and the HTTP cap therefore never gets a spurious 413.
- **Title-page patch:** pytex 1.0.6 renders only its hard-wired frontmatter keys. At import, `app.py` appends `Gremium` and `Beschlussfähigkeit` rows to `_protocol_document._SCALAR_ROWS`. This is a wrapper patch, not a fork. Re-check it after every `pytex-preprocessor` bump.
- **SVG logos** go through the `inkscape` shim → `rsvg-convert`. Any unexpected inkscape call fails loudly instead of guessing. You must add CD-specific fonts (for example Blender for STUPA) to the image separately.
- **Tests:** unit tests mock `render_blob_async` (no tectonic). The md→tex integration test always runs in CI. pytest skips the md→pdf test unless `tectonic` is on PATH (opt-in via `RUN_PYTEX_INTEGRATION=1`). To bump tectonic, update the version and both arch sha256 sums in the Dockerfile.

**Related:** be-pdf, be-protocol
