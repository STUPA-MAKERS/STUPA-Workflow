---
name: be-pdf
description: Async application-PDF rendering — POST /api/applications/{id}/pdf plus GET /api/jobs/{id}. Covers the render_job table, the pytex /render HTTP client, MinIO storage, the arq render_pdf worker task, and the exportPdf flow-action dispatcher. Use when working on PDF generation, render jobs, pytex client, or document Markdown in backend/app/modules/pdf.
---

# Application PDF Generation — `backend/app/modules/pdf`

**Does:** Renders application PDFs asynchronously. The API creates a `render_job` row and answers 202 with a jobId. The arq worker builds Markdown from the application, calls the internal pytex `/render` service, and stores the PDF in MinIO. `GET /jobs/{id}` returns the status plus a short-lived signed result URL.

**Key files:**
- `router.py` — the two routes. It runs the A/P access checks and answers 404 for a cross-tenant read (no existence oracle).
- `service.py` — `PdfService`: job lifecycle (`create_application_job`, `get_job`, `to_out`) bound to an `AsyncSession`, plus `load_application_doc` (DB → `ApplicationDoc`).
- `models.py` — `RenderJob` ORM model + `JOB_STATUSES`, `JOB_KIND_APPLICATION_PDF`.
- `schemas.py` — `JobOut` (camelCase: `applicationId`, `resultUrl`).
- `markdown.py` — DB-free, unit-tested `ApplicationDoc` dataclass plus `build_application_markdown` (YAML frontmatter + Markdown). It also holds `variant_for`/`_VARIANT_MAP` (cd_variant → pytex variant), which is the legacy fallback only.
- `render.py` — `RenderPipeline` (worker orchestration: running→pytex→MinIO→done) + `RenderRetry`. It injects the pytex and storage dependencies.
- `pytex_client.py` — `PytexClient.render_pdf` (HTTP POST to pytex `/render`), `PytexError`, and the `build_pytex_client(settings)` factory.
- `queue.py` — `ArqRenderQueue.enqueue` (enqueues the `render_pdf` arq task, dedup job-id `render:<id>`) and `render_queue_from_pool`.
- `action_dispatcher.py` — `PdfActionDispatcher` handles the `exportPdf` flow action. `ChainActionDispatcher` chains it with notify. The factory is `build_pdf_dispatcher(pool)`.
- The worker task lives outside the module at `backend/worker/pdf.py` (`render_pdf`). `backend/worker/main.py` registers it.

**Domain / data model:**
- Table `render_job` (`RenderJob`, UUID pk, TimestampMixin): `kind` (default `application_pdf`), `application_id` (FK `application.id`, ondelete CASCADE, nullable), `status` (`pending`→`running`→`done`/`failed`, CHECK-constrained), `storage_key` (MinIO key — PDF never in DB), `error` (short, path-free code, no stacktrace leak), `idempotency_key` (Text, partial-UNIQUE index — NULL allowed and repeatable), `finished_at`.
- `JOB_STATUSES = ("pending","running","done","failed")` and `JOB_KIND_APPLICATION_PDF = "application_pdf"`. The `kind` column exists so a future render kind needs no schema change.
- `ApplicationDoc` (markdown.py): application_id, type_name, gremium_slug, cd_variant, `gremium_id`, lang/default_lang, fields (`FormFieldDef[]`), data, applicant_name, created_at, timeline (`TimelineItem[]`), vote (`VoteResult|None`). `gremium_id` is what `RenderPipeline._render` resolves the corporate design with. The `.variant` property maps `cd_variant` → pytex variant (`makers`→`report-makers`, default `report`).
- MinIO key format: `pdf/<application_id>/<job_id>.pdf` (separate `pdf/` prefix from attachments).

**API surface:**
- `POST /api/applications/{application_id}/pdf` — A/P (`require_app_read`). It creates a `render_job` (pending), commits, enqueues, and answers 202 + `JobOut`. The REST path leaves `idempotency_key` NULL, so every call is a fresh render.
- `GET /api/jobs/{job_id}` — A/P job status. The route checks access against the application of the job (`resolve_access`, view scope, READ_PERMISSION). On `done` it returns a presigned MinIO URL (`pdf_url_ttl_seconds`). Without an identity it answers 401 before the DB lookup. A job without an application is principal-only.

**Conventions & gotchas:**
- The API never renders — it only writes the row and enqueues. No Redis → queue is `None`, job stays `pending` (no API block or crash). No MinIO → worker returns `skipped` and the job stays `pending`. `GET` then returns no `resultUrl`.
- The pytex call always carries the query params `input_kind=md`, `output_kind=pdf`, `trust_level` (default `trusted`) and an optional `variant`. The body shape depends on the call: **raw** `text/markdown` when there is neither a `config` nor an `asset`, otherwise **`multipart/form-data`** with `source` (the Markdown), `config` (a JSON object) and one repeated `assets` part per file. There is NO shell call — Markdown is never on a command line. App-generated PDFs use `trusted`. User-written Markdown (protocol/agenda-item bodies, in `be-protocol`) passes `trust_level="untrusted"` to lock the pytex Markdown-eval escape.
- **Corporate design.** `RenderPipeline._render` calls `resolve_cd_variant(session, storage, doc.gremium_id)` (`be-admin`, `admin/cd_resolver.py`). On `None` the call keeps the raw-body shape with `variant=doc.variant`. Otherwise it keeps the same `variant` — the shape belongs to the document kind, not to the design — and adds `cd_render_config(cd)` (`logos` / `footer_logos`) plus `cd.assets`. `_VARIANT_MAP` therefore only still decides the shape; the logos no longer come from it.
- Error discipline (RFC-9457 problem+json out): `error` holds only a short path-free code. A pytex 4xx is permanent (no retry, job `failed`). A 5xx or a transport error is transient → `RenderRetry` → arq `Retry` with linear backoff up to `pdf_max_tries`, then `mark_failed` (`render_unavailable`). See `pytex_client._error_detail` for the scrubbed-detail cap.
- Idempotency: the `exportPdf` flow action reuses an existing job for the same `idempotency_key` (one status-event ⇒ at most one render). arq `_job_id=render:<id>` coalesces duplicate enqueues.
- Markdown is injection-safe. `_yaml_scalar` double-quotes the frontmatter scalars. The builder skips PII fields (`FormFieldDef.is_pii`), which stay in the applicant record and never reach the gremium PDF. `resolve_i18n` resolves the i18n labels against the lang of the application.
- Settings: `pytex_url`, `pytex_trust`, `pytex_timeout_seconds`, `pdf_url_ttl_seconds`, `pdf_max_tries`, `pdf_retry_backoff_seconds`.

**Related:** be-protocol, be-applications, be-flow, be-files, be-forms.
