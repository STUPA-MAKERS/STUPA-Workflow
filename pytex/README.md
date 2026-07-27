# pytex

Render service: a thin FastAPI wrapper around `pytex_api.render_blob`
(pytex-preprocessor **v1.0.6**, pinned in `requirements.txt`). pytex ships no
REST surface, so this container exposes one over the blob API. The PDF module of
the platform calls it.

Markdown in (raw request body) → PDF out (or `.tex`). The service reads the
variant (`report` / `protocol-stupa` / `protocol-asta` / …) from the YAML
frontmatter of the document. Force a variant with `?variant=`.

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

The service is **internal-only**: it has no host port and it sits on the
`internal` compose network. It renders first-party, app-generated documents
only, so it defaults to `trusted`. That default lets the first build pull the
tectonic bundle. After that the `pytex_cache` volume serves the bundle offline.

> ⚠️ **Keep the pytex port private.** The `trusted` default runs a build with
> the full tectonic and biber toolchain. Such a build shells out, and the first
> build uses the network. Never publish port `8099` to a host. Never expose it
> outside the `internal` network. An untrusted caller that reaches the port can
> abuse the trusted build path. Keep the port reachable from the backend only.

#### Error contract
The service scrubs absolute filesystem paths out of every detail string. No
stacktrace leaks.

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
| `PYTEX_MAX_BODY_BYTES`  | `4194304`   | hard body cap, before the 2 MiB library input cap |
| `XDG_CACHE_HOME`        | `/cache`    | tectonic bundle cache (mount `pytex_cache`) |

## Develop

```bash
cd pytex
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check . && .venv/bin/basedpyright && .venv/bin/python -m pytest
```

Unit tests mock the render backend, so they need no tectonic. The md→tex
integration tests run the real variant machinery and need no tectonic either.
They run in CI every time. pytest skips the md→pdf test unless `tectonic` is on
`PATH`:

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
