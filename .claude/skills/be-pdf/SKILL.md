---
name: be-pdf
description: The HTTP client to the internal typst render service — TypstClient.render_pdf, TypstError, build_typst_client, variants and the multipart logo channel. The callers are the protocols, the export of a Haushaltsplan and the Antrag PDF (documents module, also the Antrag Anlage of a protocol). Use when working on the render call, its error and retry discipline, or the render settings in backend/app/modules/pdf.
---

# typst client — `backend/app/modules/pdf`

**Does:** Holds the HTTP client to the internal typst `/render` service. Nothing else. The
callers are `be-protocol`, which renders a meeting protocol to PDF and stores it in MinIO
itself, `be-budget`, which renders a version of a Haushaltsplan with the variant `plan` and
answers the bytes (spec 000875), and `app/modules/documents`, which renders an Antrag
synchronously (`GET /api/applications/{id}/pdf`, specs 000880-000883, signature section
000888) and as the Anlage of a protocol (000884-000886). The Antrag PDF is never stored.

> The old async application render (`render_job` table, arq `render_pdf` task, `exportPdf`
> flow action) stays removed. Do not reintroduce it: the Antrag PDF renders on request.

**Key files:**
- `typst_client.py` — `TypstClient.render_pdf`, `TypstError`, and the
  `build_typst_client(settings)` factory. The whole module.

**API surface:** none. This module exposes no route.

**Conventions & gotchas:**
- The call sends Markdown as the raw HTTP **body** (`text/markdown`) with the optional
  query param `variant`. With a `config` or `assets` it switches to `multipart/form-data`
  (`source`, `config`, repeated `assets`). There is no shell call.
- **No trust levels.** The render service turns the Markdown into data before Typst sees
  it, so no part of the Markdown runs as code and the call carries no trust level.
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
