---
name: be-pdf
description: The HTTP client to the internal pytex render service — PytexClient.render_pdf, PytexError, build_pytex_client, trust levels and CD variants. Protocols are the only caller; applications no longer render a PDF. Use when working on the pytex call, its error and retry discipline, or the render settings in backend/app/modules/pdf.
---

# pytex client — `backend/app/modules/pdf`

**Does:** Holds the HTTP client to the internal pytex `/render` service. Nothing else. The
one caller is `be-protocol`, which renders a meeting protocol to PDF and stores it in
MinIO itself.

> **Applications no longer render a PDF.** The route, the `render_job` table, the arq
> `render_pdf` task, the `exportPdf` flow action and the application Markdown builder were
> all removed. If you are looking for any of those, they are gone on purpose — do not
> reintroduce them without asking.

**Key files:**
- `pytex_client.py` — `PytexClient.render_pdf` (HTTP POST to pytex `/render`), `PytexError`,
  and the `build_pytex_client(settings)` factory. The whole module.

**API surface:** none. This module exposes no route.

**Conventions & gotchas:**
- The call sends Markdown as the raw HTTP **body** (`text/markdown`) with query params
  `input_kind=md`, `output_kind=pdf`, `trust_level`, optional `variant`. There is no shell
  call — Markdown never reaches a command line.
- Trust levels: user-written Markdown (protocol and agenda-item bodies) passes
  `trust_level="untrusted"` to lock the pytex Markdown-eval escape. The `trusted` default
  is for server-generated documents.
- Error discipline: a pytex 4xx is permanent and gets no retry. A 5xx or a transport error
  is transient and retryable — `PytexError.retryable` carries which. `_error_detail`
  returns the scrubbed `{"error": …}` body, defensively truncated, so a compile error
  reaches the log without a path leak.
- **Every variant the platform asks for must be warmed in `pytex/warmup.py`.** A variant
  that is not meets a cold cache in production, tries to fetch its LaTeX packages at run
  time, and dies behind the container's egress block; pytex answers 400.
  `pytex/tests/test_warmup_covers_used_variants.py` pins the list.
- **No browser bucket links.** MinIO has no published port, so a presigned S3 URL binds a
  host the browser cannot resolve. Renders stream through the API the way `be-files` and
  `be-protocol` do. `ObjectStorage` carries no presigning method at all — do not add one.
- Settings: `pytex_url`, `pytex_trust`, `pytex_timeout_seconds`.

**Related:** be-protocol, pytex, be-files.
