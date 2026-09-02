---
name: be-files
description: Backend attachment storage for applications: multipart upload, libmagic MIME sniff plus extension match, MinIO/S3 object store. An arq worker runs the async ClamAV scan, quarantine gating guards the server-side download stream. Models Attachment (scanned/scan_result/storage_key). Routes under /api/applications/{id}/attachments and /api/attachments/{id}. Use when working on file uploads, virus scanning, MinIO storage, signed/download URLs, or attachment access control in backend/app/modules/files.
---

# Files / Attachments — `backend/app/modules/files`

**Does:** Handles application attachment uploads. It caps the size, sniffs the real MIME type, stores the blob in MinIO/S3 and enqueues an async ClamAV scan. It serves a download only after a clean scan. Binary content never lives in the DB.

**Key files:**
- `router.py` — FastAPI routes: upload, list, signed-url, download stream, delete. The access checks mirror application read and edit. A cross-tenant request gets 404, so there is no existence oracle.
- `service.py` — `FilesService`: `upload`, `list_for_application`, `get_attachment`, `signed_url`, `download_bytes`, `delete`, `delete_for_application` (GDPR), `finalize_scan` (worker callback). `max_bytes`, `_is_infected`, `_ready_attachment` (quarantine gates).
- `models.py` — `Attachment` ORM model + `MAX_ATTACHMENT_BYTES` (10 MiB) DB CHECK.
- `schemas.py` — `AttachmentOut` (id/filename/mime/size/scanned/is_comparison_offer), `SignedUrlOut` (url/expiresIn).
- `mime.py` — libmagic sniff + `ALLOWED_MIME_TYPES` allowlist, `_EXT_TO_MIME` ext↔mime match, `validate_upload`, `sanitize_filename` (path-traversal hardening), `MimeRejected`.
- `storage.py` — `ObjectStorage` Protocol, `MinioStorage` (sync minio client via `asyncio.to_thread`), `build_object_storage`, `_safe_disposition`, `StorageError`.
- `scanner.py` — `VirusScanner` Protocol, `ClamdScanner` (clamd TCP INSTREAM), `ScanVerdict`, `build_scanner`, `EICAR_TEST_BYTES`, `ScannerError`.
- `queue.py` — `ScanQueue` Protocol, `ArqScanQueue`, `SCAN_TASK_NAME="scan_attachment"`, `scan_queue_from_pool`.
- `../../../worker/scan.py` — arq task `scan_attachment`: fetch from MinIO → ClamAV → `finalize_scan`. A transient error raises `arq.Retry` with a linear backoff, up to `scan_max_tries`.

**Domain / data model:**
- One `attachment` row per upload.
- Columns: `id` (UUID PK), `application_id` (FK → `application.id`, `ondelete=CASCADE`, indexed), `field_key` (nullable, links to a form field), `filename`, `mime`, `size` (BigInt, CHECK `size <= 10485760`), `storage_key` (nullable, the MinIO object path `{application_id}/{uuid4hex}/{safe_name}`), `scanned` (bool, default false), `scan_result` (nullable: `NULL`/`clean`/virus-signature), `is_comparison_offer` (bool), `created_at` (tz-aware).
- Scan lifecycle: the row starts with `scanned=false`, which means quarantine. The worker then sets `scanned=true` and `scan_result='clean'`. On a hit it sets `scan_result=<signature>` and nulls `storage_key`. The object is deleted and gone for good.

**API surface:** (mounted under `/api`)
- `POST /api/applications/{application_id}/attachments` — multipart upload (≤10 MiB, streamed and capped) with the form fields `field_key` and `is_comparison_offer`. It needs app-edit rights and is rate-limited. Returns `AttachmentOut` with 201. Errors: 401/403/404/413/415/429/503.
- `GET /api/applications/{application_id}/attachments` — list the attachments (app-read).
- `GET /api/attachments/{attachment_id}` — returns `SignedUrlOut` that points at the `/download` route, not at a presigned bucket URL. It gives 409 while the scan runs, 410 for a quarantined or removed file, and 503 without storage.
- `GET /api/attachments/{attachment_id}/download` — streams the bytes server-side with `Content-Disposition: attachment`. The same gates apply.
- `DELETE /api/attachments/{attachment_id}` — 204. Open to a principal with `application.manage`, to an applicant in edit scope, and to the logged-in creator.

**Conventions & gotchas:**
- **Fail-closed quarantine** (`_ready_attachment`): an unscanned file (`scanned=false`) gives 409. An infected or removed file (`storage_key is None` or `_is_infected`) gives 410. NEVER loosen or invert the `if not attachment.scanned` check. It would serve unscanned content.
- **Download is server-side streamed, not presigned.** MinIO sits in the internal Docker network with no published port. An S3v4-presigned URL therefore binds the internal host, and the browser cannot reach it. `signed_url()` returns the app-relative URL `/api/attachments/{id}/download`. The bytes flow through nginx `/api/`. The `ObjectStorage` protocol carries **no** presigning method: it was removed once the last caller (`be-pdf`) was converted, so the mistake cannot be repeated by reaching for a method that exists.
- **No existence oracle:** an authenticated caller without read access to the application of the attachment gets 404, not 403. The auth check runs before the DB access on the URL, download and delete routes.
- **Access mirrors application read and edit** (not only the global `application.read`): `_resolve_attachment_read` covers `read_all`, view-applicant, the logged-in creator, and committee-read. See `be-applications`.
- **Content decides, not the extension:** `validate_upload` needs the sniffed MIME in the allowlist AND a matching `_EXT_TO_MIME` entry for the file extension. OOXML may sniff as `application/zip`, which is allowed only for `.docx/.xlsx/.pptx`. A mismatch or an empty result gives 415.
- **Upload is NOT edit-locked:** a user may add an attachment in a locked state (submitted or approved, for example a late invoice). The form data stays PATCH-locked elsewhere.
- **Optional infrastructure degrades safely:** without MinIO an upload gives 503. Without a Redis/arq pool the file stays quarantined, because the scan is never enqueued. The API does not block. The module imports the heavy libraries (`magic`, `minio`, `clamd`) lazily, which keeps them out of the contract CI.
- **Enqueue is idempotent:** the job id `scan:<attachment_id>` coalesces duplicate enqueues.
- The quarantine and delete actions write audit rows (`ATTACHMENT_QUARANTINE`, `ATTACHMENT_DELETE`), see `be-audit`. `delete_for_application` (GDPR anonymization) does NOT commit. The caller commits atomically.
- Tunables in settings: `attachment_max_bytes`, `attachment_url_ttl_seconds`, `storage_enabled`/`minio_*`, `clamav_*`, `scan_max_tries`, `scan_retry_backoff_seconds`.

**Related:** be-applications, be-audit, be-privacy, be-notifications
