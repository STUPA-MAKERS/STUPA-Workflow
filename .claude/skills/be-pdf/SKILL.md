---
name: be-pdf
description: The HTTP client to the internal typst render service — TypstClient.render_pdf, TypstError, build_typst_client, variants and the multipart logo channel. Protocols are the only caller; applications no longer render a PDF. Use when working on the render call, its error and retry discipline, or the render settings in backend/app/modules/pdf.
---

# typst client — `backend/app/modules/pdf`

**Does:** Holds the HTTP client to the internal typst `/render` service. Nothing else. The
one caller is `be-protocol`, which renders a meeting protocol to PDF and stores it in
MinIO itself.

> **Applications no longer render a PDF.** The route, the `render_job` table, the arq
> `render_pdf` task, the `exportPdf` flow action and the application Markdown builder were
> all removed. If you are looking for any of those, they are gone on purpose — do not
> reintroduce them without asking.

**Key files:**
- `typst_client.py` — `TypstClient.render_pdf`, `TypstError`, and the
  `build_typst_client(settings)` factory. The whole module.

**API surface:** none. This module exposes no route.

**Conventions & gotchas:**
- The call sends Markdown as the raw HTTP **body** (`text/markdown`) with the optional
  query param `variant`. With a `config` or `assets` it switches to `multipart/form-data`
  (`source`, `config`, repeated `assets`). There is no shell call.
- **No trust levels.** The render service turns the Markdown into data before Typst sees
  it, so the pytex-era `trust_level` and the eval-trigger gate are gone.
- Error discipline: a 4xx is permanent and gets no retry. A 5xx or a transport error is
  transient and retryable — `TypstError.retryable` carries which. `_error_detail` returns
  the scrubbed `{"error": …}` body, truncated.
- **No browser bucket links.** MinIO has no published port, so a presigned S3 URL binds a
  host the browser cannot resolve. Renders stream through the API the way `be-files` and
  `be-protocol` do. `ObjectStorage` carries no presigning method at all — do not add one.
- The client passes the Markdown through unchanged. `be-protocol` builds the frontmatter;
  the `typst` skill lists the contract (`keepers` records, `entschuldigt`, `started_at`,
  the legacy `protokoll`). A change of that contract needs the api and the typst image
  deployed together. The legacy keys keep an older typst image working in between.
- Settings: `typst_url` (`TYPST_URL`), `typst_timeout_seconds`.

**Related:** be-protocol, typst, be-files.
