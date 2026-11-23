---
name: be-paperless
description: The optional Paperless-ngx integration — one connection (address, token, switches) at /admin/paperless behind admin.paperless, the worker cron process_paperless_filings that files final protocols, decided Anträge with their clean attachments and plan versions in force, the record paperless_filing (job, retries, failed list, backfill, tag Ersetzt), and the entry "In Paperless öffnen" behind paperless.use. Covers PaperlessClient, ConnectionService, FilingRunner, FileBuilder, new_filings/backfill_filings and PAPERLESS_HOST_ALLOWLIST. Use when working on backend/app/modules/paperless, backend/app/modules/paperless_filing, backend/worker/paperless.py or the admin page pages/admin/paperless.
---

# Paperless — `backend/app/modules/paperless` + `backend/app/modules/paperless_filing`

**Does:** Files the documents of the platform in one Paperless-ngx instance and links each element to its document (specs F/integrations/paperless 002511-002535, NF/security/network 002514, 002515). The integration is optional: without an address and a token nothing runs. The platform uploads and tags documents; it deletes none.

**Two modules, because of the import layers:** `paperless` is low (same layer as `webhooks`): models, client, connection, the record of the filings. It imports no domain module, so `privacy` can read the filed documents of an Antrag (`filings.filed_for_applications`). `paperless_filing` is a top module: it reads protocols, Anträge, attachments and plans, builds the files and has the routes.

**Key files:**
- `paperless/models.py` — `PaperlessSettings` (single row `id = 1`: `base_url`, `token`, the switches `file_protocols`, `file_applications`, `file_plans`, `insert_enabled`, each with `<part>_since`) and `PaperlessFiling` (one row = one job; unique `(kind, source_id, source_at)`).
- `paperless/client.py` — `PaperlessClient`: `check`, `ensure(where, name)` (document type, tag, custom field by name), `upload` (answers the consume task), `task`, `set_link`, `add_tag`. `PaperlessError(code)` with the codes `blocked`, `timeout`, `unreachable`, `redirect`, `unauthorized`, `status`, `format`. `host_allowed`, `normalize_url`, `document_url`.
- `paperless/connection.py` — `ConnectionService`: `row`, `read`, `save` (422 `paperless_host_not_allowed`, audit `paperless_connection`), `client`, `test`. `part_since(row, part)` tells whether a part is on.
- `paperless/filings.py` — the record: `open_filings`, `due_filings`, `lock_due`, `mark_*`, `replaced_documents`, `failed_filings`, `retry_filing`, `element_document`, `filed_for_applications`. `MAX_TRIES = 8`, `backoff` (1 min, doubled per try).
- `paperless_filing/sources.py` — `new_filings` (the events since the switch of a part went on) and `backfill_filings` (elements without any job).
- `paperless_filing/files.py` — `FileBuilder.build(filing)` → `Prepared` (file, title, date, document type, Gremium, link). `BuildError(code, final)`.
- `paperless_filing/runner.py` — `FilingRunner.run` (two steps: upload, then read the consume task and set the custom field `Plattform`) and `tag_replaced` (tag `Ersetzt`).
- `paperless_filing/router.py` — the routes.
- `backend/worker/paperless.py` — job `process_paperless_filings`: asked for at each event (`paperless/queue.py`), and a cron every minute at second 45.

**What is filed (kinds):**
- `protocol`, `protocol_public` — both stored PDFs of a final protocol, one job per finalization (`source_at = finalized_at`). Document type `Protokoll`.
- `application` — the PDF of an Antrag at each decision (a `status_event` into a state with `is_approved` or `is_denied`; `source_id` is the event). Rendered by a system reader with the admin role, so the archive copy hides no field. Document type `Antrag`.
- `attachment` — each attachment of that Antrag with a clean virus scan, once per attachment. Document type `Antrag`, title `<Antrag> – <file name>`.
- `plan` — the PDF of a plan version in force (`source_id` is the version). Document type `Haushaltsplan`.
Each document gets the name of its Gremium as a tag and the address of its element in the custom field `Plattform`.

**API surface:**
- `GET/PUT /api/admin/paperless`, `POST /api/admin/paperless/test`, `GET /api/admin/paperless/failed-filings`, `POST /api/admin/paperless/failed-filings/{id}/retry`, `POST /api/admin/paperless/backfill` — permission `admin.paperless`.
- `GET /api/paperless/documents/{kind}/{element_id}` (`kind`: `protocol|application|plan`) — permission `paperless.use`; answers `{url, documentId}`, both null without a filed document or with the part off.
- No MCP tool: no OAuth scope carries the two permissions (spec 001201).

**Conventions & gotchas:**
- **The events only ask for a run.** `paperless/queue.py: request_filing(pool)` enqueues one `process_paperless_filings` job. Three places call it after their commit: `flow/paperless_actions.py` (`PaperlessFilingDispatcher`, last in the chain of `build_worker_dispatcher`, so every committed transition), the two state routes of `budget/plan_router.py`, and `worker/protocol.py` after a finalization. The call passes no id and never fails (no pool: nothing; a queue error: a log line). The run itself scans for events since `<part>_since` with `NOT EXISTS` on `paperless_filing`, and the minute cron stays as the safety net. A new source is a query in `sources.py` plus one `request_filing` call at its event.
- **The token is write-only** (002515): no response model has it, no log line and no audit entry names it. `PUT` without `token` keeps the stored one; `clearToken` removes it.
- **The host allowlist is checked twice** (002514): at the save and in `PaperlessClient._send` before every call. `PAPERLESS_HOST_ALLOWLIST` empty allows no host. The client follows no redirect.
- **A job never uploads twice for one document number:** after the upload the row keeps `task_id`; after the consume task it keeps `document_id`, and a failed link step tries only the link again. A failure before the document exists starts with a new upload.
- A failure that a new try cannot repair (`source_missing`, a refused render, `rejected` by Paperless) ends the job at once. Each other failure counts one try.
- A part whose switch is off opens no job, runs none (`open_kinds`) and gives the entry no address.
- `backfill` only opens jobs; the worker files them. It covers the parts whose switch is on.
- The insert with `::` (specs 002527-002529, 002534) is on while `insert_on(row)` holds (switch `insert_enabled` and a connection). `GET /api/paperless/insert` tells the state and `GET /api/paperless/search?q=` searches (`PaperlessClient.search`: full text, 20 hits, 5 s limit; an empty query answers the newest documents), both behind `paperless.use`; the search answers 404 while the part is off and 503 `paperless_unavailable` for each `PaperlessError`. The copy is a route of the protocol, `POST /api/meetings/{id}/documents/paperless` (`protocol/documents_router.py`): write right of the Sitzung and `paperless.use`, `PaperlessClient.title` + `download` (archive PDF, cap `markdown_document_max_bytes`), then `MediaService.upload_document(..., paperless_document_id=)` (scan and PDF check as for an upload), the column `markdown_document.paperless_document_id` and the audit action `PAPERLESS_INSERTED`. `get_connection_service` lives in `paperless/connection.py`, so `protocol` can depend on it; a test overrides it to inject the fake client. The three routes are in the exclusion list of the MCP route parity test.
- Tests: `tests/_support/paperless_fakes.py` (`FakePaperless` behind `httpx.MockTransport`); the worker takes `ctx['paperless_sessionmaker']` and `ctx['paperless_client_factory']`.

- Feature switch `paperless` under /admin/features (spec 002762, on by default): off = the routes under `/api/paperless`, `/api/admin/paperless` and the copy route answer 404 `feature_disabled` (`app/feature_routes.py`; a new route outside these prefixes needs a line there), the worker returns at once (`job_feature_on`), and the frontend hides the admin page and every entry (`PaperlessService.canUse()` reads `FeatureService.isOn('paperless')`). The connection, the part switches, the filings and the privacy lists stay.

**Frontend:** `pages/admin/paperless` (kit settings screen with no own styles: connection, switches, actions, and the failed filings as action rows with the icon "Erneut versuchen", which asks first), `core/api/paperless.service.ts` (`paperlessLink(kind, idSignal)`, `openInPaperless`), the menu entry `paperless.open` in the Antrag detail, the plan page and the meeting page (final protocol).

**Related:** be-protocol, be-applications, be-budget, be-files, be-pdf, be-webhooks (same SSRF concern), be-privacy, deploy
