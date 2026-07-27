---
name: be-privacy
description: DSGVO/GDPR backend — erasure-request queue (Art. 17), application anonymization, principal erasure, Auskunft XLSX export (Art. 15), and the global retention-months setting under /admin/privacy. Use when working on data erasure, anonymization, PII export, ErasureRequest/PrivacySettings, or privacy.manage in backend/app/modules/privacy.
---

# Privacy / DSGVO — `backend/app/modules/privacy`

**Does:** Implements GDPR data-subject rights. An erasure-request queue (Art. 17) anonymizes applications or erases principals. A personal-data export (Auskunft, Art. 15) returns XLSX. The module also holds a platform-wide retention default, and it audits every admin action.

**Key files:**
- `models.py` — `PrivacySettings` (singleton id=1) + `ErasureRequest` ORM models.
- `schemas.py` — camelCase Pydantic out/in models (`ErasureRequestOut`, `ErasureRejectBody`, `PrivacySettingsOut/Update`). It also defines the `SubjectType`/`ErasureStatus` literals.
- `service.py` — `PrincipalService.erase`, `ErasureRequestService` (create/list/execute/reject), `PrivacySettingsService`, `AuskunftService.collect`.
- `router.py` — `/admin/privacy` admin router, gated by `privacy.manage`.

**Domain / data model:**
- `privacy_settings` — single row, `id=1` (CheckConstraint `id = 1`), plus `default_retention_months` (server_default 24, min 1). Admins maintain it as the data protection officer (DSB) placeholder.
- `erasure_request` — UUID PK + `created_at`. Columns: `subject_type` ∈ {`applicant`,`principal`}, `application_id`/`principal_id` FKs `ON DELETE SET NULL`, `email` (CITEXT), `status` ∈ {`open`,`executed`,`rejected`} (server_default `open`, indexed), `requested_by`, `handled_by`, `handled_at`, `reason`. The FKs use SET NULL so the queue row survives as proof after a hard delete of the subject. The service captures `email` before anonymization for the confirmation mail.
- Status machine: `open → executed | rejected`. Only an `open` row may transition. Any other status raises `ConflictError code=erasure_not_open`.
- **applicant** erasure → `ApplicationsService.anonymize`. It sets the PII to NULL, sets `Applicant.anonymized_at`, and drops the attachments plus their storage objects. The application row stays.
- **principal** erasure → `PrincipalService.erase`. It sets email/display_name/calendar_token/oidc_groups to NULL, sets `active=False`, and deletes the `AuthSession` rows. It keeps `sub` as a pseudonym for the audit chain and the Keycloak link. Deletion of the Keycloak user itself happens out of band.

**API surface:**
- `GET /api/admin/privacy/erasures?status=` — erasure queue, newest first.
- `POST /api/admin/privacy/erasures/{id}/execute` — run erasure (anonymize/erase), atomic with status flip.
- `POST /api/admin/privacy/erasures/{id}/reject` — reject with `reason`.
- `POST /api/admin/privacy/principals/{id}/erase` — direct principal erasure (204).
- `GET /api/admin/privacy/auskunft?email=` — Art. 15 personal-data export as XLSX (applicants, applications+`data`, submission-version history, principal row).
- `GET|PUT /api/admin/privacy/settings` — global retention default.
- The public entry point lives in **be-applications**: `POST /api/applications/{id}/erasure-request` (202). Applicant self-service (magic-link, creator, or authorized reader) creates an `open` queue row. `require_app_read` gates it, not `privacy.manage`.

**Conventions & gotchas:**
- All routes require permission `privacy.manage` (`require_principal`) except the public erasure-request creation in be-applications.
- Services NEVER send mail. The router or the worker fires `notify_erasure_{requested,executed,rejected}` best-effort via `BackgroundTasks` **after** the commit (`app.modules.notifications.privacy`, `mail_queue_from_pool`).
- `execute`/`erase` call inner services with `commit=False` so anonymization + status change land in **one transaction**.
- `auskunft` writes its own `AuditAction.PII_EXPORT` entry with the queried email as `target_id`. The trail must stay traceable to WHOSE data left the platform (Art. 30 accountability). Other audited actions: `ERASURE_REQUESTED/EXECUTED/REJECTED`, `ANONYMIZATION`, `PRINCIPAL_ERASED`.
- `ErasureRequestService.create` validates the subject↔id pairing (`ValidationProblem`), checks the application up-front (404 not 500), and copies the applicant email before the erasure sets it to NULL.
- If a migration seed is missing, `PrivacySettingsService.get` seeds the id=1 row itself.
- The Auskunft export resolves the i18n type and state labels via `_i18n` (locale → `de` → `en` fallback).

**Related:** be-applications, be-audit, be-files, be-notifications, be-auth
