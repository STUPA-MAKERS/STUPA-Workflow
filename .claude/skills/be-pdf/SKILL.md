---
name: be-pdf
description: Async application-PDF rendering — POST /api/applications/{id}/pdf + GET /api/jobs/{id}, the render_job table, the pytex /render HTTP client, MinIO storage, the arq render_pdf worker task, and the exportPdf flow-action dispatcher. Use when working on PDF generation, render jobs, pytex client, or document Markdown in backend/app/modules/pdf.
---

# Application PDF Generation — `backend/app/modules/pdf`

**Does:** Renders application PDFs asynchronously: the API creates a `render_job` row (202 + jobId), the arq worker builds Markdown from the application, calls the internal pytex `/render` service, and stores the PDF in MinIO. `GET /jobs/{id}` returns status plus a short-lived signed result URL.

**Key files:**
- `router.py` — the two routes; A/P access checks; cross-tenant → 404 (no existence oracle).
- `service.py` — `PdfService`: job lifecycle (`create_application_job`, `get_job`, `to_out`) bound to an `AsyncSession`, plus `load_application_doc` (DB → `ApplicationDoc`).
- `models.py` — `RenderJob` ORM model + `JOB_STATUSES`, `JOB_KIND_APPLICATION_PDF`.
- `schemas.py` — `JobOut` (camelCase: `applicationId`, `resultUrl`).
- `markdown.py` — DB-free, unit-tested `ApplicationDoc` dataclass + `build_application_markdown` (YAML frontmatter + Markdown); `variant_for`/`_VARIANT_MAP` (cd_variant → pytex variant).
- `render.py` — `RenderPipeline` (worker orchestration: running→pytex→MinIO→done) + `RenderRetry`; injects pytex/storage deps.
- `pytex_client.py` — `PytexClient.render_pdf` (HTTP POST to pytex `/render`) + `PytexError`; `build_pytex_client(settings)`.
- `queue.py` — `ArqRenderQueue.enqueue` (enqueues `render_pdf` arq task, dedup job-id `render:<id>`); `render_queue_from_pool`.
- `action_dispatcher.py` — `PdfActionDispatcher` handles the `exportPdf` flow action; `ChainActionDispatcher` chains it with notify; `build_pdf_dispatcher(pool)`.
- Worker task lives outside the module at `backend/worker/pdf.py` (`render_pdf`), registered in `backend/worker/main.py`.

**Domain / data model:**
- Table `render_job` (`RenderJob`, UUID pk, TimestampMixin): `kind` (default `application_pdf`), `application_id` (FK `application.id`, ondelete CASCADE, nullable), `status` (`pending`→`running`→`done`/`failed`, CHECK-constrained), `storage_key` (MinIO key — PDF never in DB), `error` (short, path-free code; no stacktrace leak), `idempotency_key` (Text, partial-UNIQUE index — NULL allowed and repeatable), `finished_at`.
- `JOB_STATUSES = ("pending","running","done","failed")`; `JOB_KIND_APPLICATION_PDF = "application_pdf"` (kind column exists so future render kinds need no schema change).
- `ApplicationDoc` (markdown.py): application_id, type_name, gremium_slug, cd_variant, lang/default_lang, fields (`FormFieldDef[]`), data, applicant_name, created_at, timeline (`TimelineItem[]`), vote (`VoteResult|None`); `.variant` property maps `cd_variant` → pytex variant (`report`, `makers`→`report-makers`, default `report`).
- MinIO key format: `pdf/<application_id>/<job_id>.pdf` (separate `pdf/` prefix from attachments).

**API surface:**
- `POST /api/applications/{application_id}/pdf` — A/P (`require_app_read`); creates a `render_job` (pending), commits, then enqueues; → 202 + `JobOut`. REST path leaves `idempotency_key` NULL (every call = fresh render).
- `GET /api/jobs/{job_id}` — A/P; job status; access checked against the job's application (`resolve_access`, view scope, READ_PERMISSION); on `done` returns a presigned MinIO URL (`pdf_url_ttl_seconds`). 401 before DB lookup if no identity; jobs without an application are principal-only.

**Conventions & gotchas:**
- API never renders — it only writes the row + enqueues. No Redis → queue is `None`, job stays `pending` (no API block/crash). No MinIO → worker returns `skipped`, job stays `pending`; `GET` returns no `resultUrl`.
- pytex sends server-generated Markdown as the raw HTTP **body** (`text/markdown`) with query params `input_kind=md`, `output_kind=pdf`, `trust_level` (default `trusted`), optional `variant`. There is NO shell call — Markdown is never on a command line. App-generated PDFs use `trusted`; user-written Markdown (protocol/TOP bodies, in `be-protocol`) passes `trust_level="untrusted"` to lock pytex's Markdown-eval escape.
- Error discipline (RFC-9457 problem+json out): `error` holds only a short path-free code; pytex 4xx = permanent (no retry, job `failed`), 5xx/transport = transient → `RenderRetry` → arq `Retry` with linear backoff up to `pdf_max_tries`, then `mark_failed` (`render_unavailable`). See `pytex_client._error_detail` for the scrubbed-detail cap.
- Idempotency: the `exportPdf` flow action reuses an existing job for the same `idempotency_key` (one status-event ⇒ at most one render). arq `_job_id=render:<id>` coalesces duplicate enqueues.
- Markdown is injection-safe: frontmatter scalars are double-quoted via `_yaml_scalar`; PII fields (`FormFieldDef.is_pii`) are skipped (they stay in the applicant record, not the gremium PDF). i18n labels resolved with `resolve_i18n` against the application's lang.
- Settings: `pytex_url`, `pytex_trust`, `pytex_timeout_seconds`, `pdf_url_ttl_seconds`, `pdf_max_tries`, `pdf_retry_backoff_seconds`.

**Related:** be-protocol, be-applications, be-flow, be-files, be-forms.
