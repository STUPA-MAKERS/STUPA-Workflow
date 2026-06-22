# pytex

Render service: a thin FastAPI wrapper around `pytex_api.render_blob`
(pytex-preprocessor **v1.0.6**, pinned in `requirements.txt`). pytex ships no REST surface, so this container
exposes one over the blob API for the platform's PDF module to call.

Markdown in (raw request body) → PDF out (or `.tex`). Variant
(`report` / `protocol-stupa` / `protocol-asta` / …) is auto-detected from the
document's YAML frontmatter, or forced via `?variant=`.

## Endpoints

### `POST /render`
Source = **raw request body** (Markdown bytes). Controls = query params.

| param         | values                                    | default               |
|---------------|-------------------------------------------|-----------------------|
| `input_kind`  | `md` \| `tex` \| `py`                     | `md`                  |
| `output_kind` | `tex` \| `pdf`                            | `pdf` (`PYTEX_DEFAULT_OUTPUT`) |
| `trust_level` | `untrusted` \| `sandboxed` \| `trusted`   | `trusted` (`PYTEX_DEFAULT_TRUST`) |
| `variant`     | `report` \| `protocol-stupa` \| `protocol-asta` \| `report-makers` \| `plain` | auto-detect from frontmatter |

Response: `application/pdf` (PDF) or `text/plain; charset=utf-8` (`.tex`).
Headers: `X-Render-Duration-Seconds`, `X-Warnings`.

The service is **internal-only** (no host port, `internal` compose network) and
is fed first-party, app-generated documents, so it defaults to `trusted` — which
lets the first build pull the tectonic bundle, after which the `pytex_cache`
volume serves it offline.

> ⚠️ **The pytex port must stay private.** The `trusted` default runs builds with
> the full tectonic/biber toolchain (shell-out, network on first build). Never
> publish port `8099` to a host or expose it outside the `internal` network;
> untrusted callers reaching it could abuse the trusted build path. Keep it
> reachable only from the backend.

#### Error contract
Detail strings are scrubbed of absolute filesystem paths; no stacktrace leaks.

| condition                              | status | body                              |
|----------------------------------------|--------|-----------------------------------|
| empty body / bad enum                  | 400    | `{"error": …}`                    |
| body > `PYTEX_MAX_BODY_BYTES`          | 413    | `{"error": …}`                    |
| `LimitError` (input/output/build cap)  | 413    | `{"error": <scrubbed>}`           |
| `TrustError` / `CompileError` / `ApiError` | 400 | `{"error": <scrubbed>}`           |
| anything else                          | 500    | `{"error": "internal render error"}` |

### `GET /health`
`{"status": "ok"}` — dependency-free, drives the compose healthcheck.

## Config (env)

| var                     | default     | meaning                                  |
|-------------------------|-------------|------------------------------------------|
| `PYTEX_DEFAULT_OUTPUT`  | `pdf`       | output kind when `?output_kind` omitted  |
| `PYTEX_DEFAULT_TRUST`   | `trusted`   | trust level when `?trust_level` omitted  |
| `PYTEX_MAX_BODY_BYTES`  | `4194304`   | hard body cap, in front of the lib's 2 MiB input cap |
| `XDG_CACHE_HOME`        | `/cache`    | tectonic bundle cache (mount `pytex_cache`) |

## Develop

```bash
cd pytex
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check . && .venv/bin/basedpyright && .venv/bin/python -m pytest
```

Unit tests mock the render backend (no tectonic needed). The md→tex real-render
integration tests run the genuine variant machinery and need no tectonic, so
they run in CI by default. Only the md→pdf test is skipped unless `tectonic` is
on `PATH`:

```bash
.venv/bin/python -m pytest -m integration   # md->tex run; md->pdf needs tectonic
```

## Example

```bash
B=http://pytex:8099
# md -> pdf (frontmatter picks the variant)
curl -s -o out.pdf --data-binary @protocol.md "$B/render?output_kind=pdf"
# md -> tex, forced variant
curl -s --data-binary @doc.md "$B/render?output_kind=tex&variant=report"
```
