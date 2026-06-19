---
name: be-files
description: Backend attachment storage for applications — multipart upload, libmagic MIME-sniff + extension match, MinIO/S3 object store, async ClamAV scan via arq worker, quarantine gating, server-side download stream. Models Attachment (scanned/scan_result/storage_key). Routes under /api/applications/{id}/attachments and /api/attachments/{id}. Use when working on file uploads, virus scanning, MinIO storage, signed/download URLs, or attachment access control in backend/app/modules/files.
---

# Files / Attachments — `backend/app/modules/files`

**Does:** Handles application attachment uploads: caps size, sniffs the real MIME type, stores the blob in MinIO/S3, enqueues an async ClamAV scan, and serves downloads only after a clean scan. Binary content never lives in the DB.

**Key files:**
- `router.py` — FastAPI routes: upload, list, signed-url, download stream, delete; access checks mirror application read/edit, cross-tenant → 404 (no existence oracle).
- `service.py` — `FilesService`: `upload`, `list_for_application`, `get_attachment`, `signed_url`, `download_bytes`, `delete`, `delete_for_application` (GDPR), `finalize_scan` (worker callback). `max_bytes`, `_is_infected`, `_ready_attachment` (quarantine gates).
- `models.py` — `Attachment` ORM model + `MAX_ATTACHMENT_BYTES` (10 MiB) DB CHECK.
- `schemas.py` — `AttachmentOut` (id/filename/mime/size/scanned/is_comparison_offer), `SignedUrlOut` (url/expiresIn).
- `mime.py` — libmagic sniff + `ALLOWED_MIME_TYPES` allowlist, `_EXT_TO_MIME` ext↔mime match, `validate_upload`, `sanitize_filename` (path-traversal hardening), `MimeRejected`.
- `storage.py` — `ObjectStorage` Protocol, `MinioStorage` (sync minio client via `asyncio.to_thread`), `build_object_storage`, `_safe_disposition`, `StorageError`.
- `scanner.py` — `VirusScanner` Protocol, `ClamdScanner` (clamd TCP INSTREAM), `ScanVerdict`, `build_scanner`, `EICAR_TEST_BYTES`, `ScannerError`.
- `queue.py` — `ScanQueue` Protocol, `ArqScanQueue`, `SCAN_TASK_NAME="scan_attachment"`, `scan_queue_from_pool`.
- `../../../worker/scan.py` — arq task `scan_attachment`: fetch from MinIO → ClamAV → `finalize_scan`; transient errors `arq.Retry` w/ linear backoff up to `scan_max_tries`.

**Domain / data model:** One `attachment` row per upload. Columns: `id` (UUID PK), `application_id` (FK → `application.id`, `ondelete=CASCADE`, indexed), `field_key` (nullable, links to a form field), `filename`, `mime`, `size` (BigInt, CHECK `size <= 10485760`), `storage_key` (nullable; the MinIO object path `{application_id}/{uuid4hex}/{safe_name}`), `scanned` (bool, default false), `scan_result` (nullable: `NULL`/`clean`/virus-signature), `is_comparison_offer` (bool), `created_at` (tz-aware). Scan lifecycle: row created `scanned=false` (quarantine) → worker sets `scanned=true` + `scan_result='clean'`, OR on a hit sets `scan_result=<signature>` and nulls `storage_key` (object deleted = permanently gone).

**API surface:** (mounted under `/api`)
- `POST /api/applications/{application_id}/attachments` — multipart upload (≤10 MiB, streamed/capped), form fields `field_key`, `is_comparison_offer`; requires app-edit; rate-limited. Returns `AttachmentOut` 201. Errors: 401/403/404/413/415/429/503.
- `GET /api/applications/{application_id}/attachments` — list attachments (app-read).
- `GET /api/attachments/{attachment_id}` — returns `SignedUrlOut` pointing at the `/download` route (not a presigned bucket URL); 409 while scanning, 410 if quarantined/removed, 503 no storage.
- `GET /api/attachments/{attachment_id}/download` — streams bytes server-side with `Content-Disposition: attachment`; same gates.
- `DELETE /api/attachments/{attachment_id}` — 204; principal `application.manage` / applicant edit-scope / logged-in creator.

**Conventions & gotchas:**
- **Fail-closed quarantine** (`_ready_attachment`): un-scanned files (`scanned=false`) → 409, infected/removed (`storage_key is None` or `_is_infected`) → 410. NEVER loosen/invert this `if not attachment.scanned` check — it would serve un-scanned content.
- **Download is server-side streamed, not presigned.** MinIO sits in the internal Docker net with no port publish, so an S3v4-presigned URL binds the internal host and is unreachable from the browser. `signed_url()` returns an app-relative `/api/attachments/{id}/download` URL; bytes flow through nginx `/api/`. (Some docstrings still mention presigned URLs — the streaming path is what runs.)
- **No existence oracle:** an authenticated caller without read access to the attachment's application gets 404, not 403. Auth check happens before DB access on the URL/download/delete routes.
- **Access mirrors application read/edit** (not just global `application.read`): `_resolve_attachment_read` covers `read_all`, view-applicant, logged-in creator, and committee-read — see `be-applications`.
- **Content decides, not extension:** `validate_upload` requires the sniffed MIME in the allowlist AND matching `_EXT_TO_MIME` for the file extension (OOXML may sniff as `application/zip`, allowed only for `.docx/.xlsx/.pptx`). Mismatch/empty → 415.
- **Upload is NOT edit-locked:** attachments may be added in locked states (submitted/approved, e.g. late invoices); form data stays PATCH-locked elsewhere.
- **Optional infra degrades gracefully:** no MinIO → upload 503; no Redis/arq pool → file stays quarantined (scan never enqueued, no API block). Heavy libs (`magic`, `minio`, `clamd`) are lazy-imported (kept out of contract-CI).
- **Enqueue is idempotent:** job id `scan:<attachment_id>` coalesces duplicate enqueues.
- Quarantine/delete actions write audit rows (`ATTACHMENT_QUARANTINE`, `ATTACHMENT_DELETE`) — see `be-audit`. `delete_for_application` (GDPR anonymization) does NOT commit; the caller commits atomically.
- Tunables in settings: `attachment_max_bytes`, `attachment_url_ttl_seconds`, `storage_enabled`/`minio_*`, `clamav_*`, `scan_max_tries`, `scan_retry_backoff_seconds`.

**Related:** be-applications, be-audit, be-privacy, be-notifications
