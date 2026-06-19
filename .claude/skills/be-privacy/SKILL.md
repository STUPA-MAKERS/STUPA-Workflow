---
name: be-privacy
description: DSGVO/GDPR backend — erasure-request queue (Art. 17), application anonymization, principal erasure, Auskunft XLSX export (Art. 15), and the global retention-months setting under /admin/privacy. Use when working on data erasure, anonymization, PII export, ErasureRequest/PrivacySettings, or privacy.manage in backend/app/modules/privacy.
---

# Privacy / DSGVO — `backend/app/modules/privacy`

**Does:** Implements GDPR data-subject rights — an erasure-request queue (Art. 17) that anonymizes applications or erases principals, a personal-data export (Auskunft, Art. 15) as XLSX, and a platform-wide retention default. All admin actions are audited.

**Key files:**
- `models.py` — `PrivacySettings` (singleton id=1) + `ErasureRequest` ORM models.
- `schemas.py` — camelCase Pydantic out/in models (`ErasureRequestOut`, `ErasureRejectBody`, `PrivacySettingsOut/Update`); `SubjectType`/`ErasureStatus` literals.
- `service.py` — `PrincipalService.erase`, `ErasureRequestService` (create/list/execute/reject), `PrivacySettingsService`, `AuskunftService.collect`.
- `router.py` — `/admin/privacy` admin router, gated by `privacy.manage`.

**Domain / data model:**
- `privacy_settings` — single row, `id=1` (CheckConstraint `id = 1`); `default_retention_months` (server_default 24, min 1). DSB placeholder, admin-maintained.
- `erasure_request` — UUID PK + `created_at`. Columns: `subject_type` ∈ {`applicant`,`principal`}; `application_id`/`principal_id` FKs `ON DELETE SET NULL` (queue row survives as proof when subject is hard-deleted); `email` (CITEXT, captured before anonymization for the confirmation mail); `status` ∈ {`open`,`executed`,`rejected`} (server_default `open`, indexed); `requested_by`, `handled_by`, `handled_at`, `reason`.
- Status machine: `open → executed | rejected` (only `open` may transition; else `ConflictError code=erasure_not_open`).
- Erasure semantics: **applicant** → `ApplicationsService.anonymize` (PII→NULL, sets `Applicant.anonymized_at`, drops attachments+storage objects; application row stays). **principal** → `PrincipalService.erase` (email/display_name/calendar_token/oidc_groups→NULL, `active=False`, deletes `AuthSession` rows; `sub` retained as pseudonym for audit chain + Keycloak link — actual Keycloak user deletion is out-of-band).

**API surface:**
- `GET /api/admin/privacy/erasures?status=` — erasure queue, newest first.
- `POST /api/admin/privacy/erasures/{id}/execute` — run erasure (anonymize/erase), atomic with status flip.
- `POST /api/admin/privacy/erasures/{id}/reject` — reject with `reason`.
- `POST /api/admin/privacy/principals/{id}/erase` — direct principal erasure (204).
- `GET /api/admin/privacy/auskunft?email=` — Art. 15 personal-data export as XLSX (applicants, applications+`data`, submission-version history, principal row).
- `GET|PUT /api/admin/privacy/settings` — global retention default.
- Public entry point lives in **be-applications**: `POST /api/applications/{id}/erasure-request` (202) — applicant self-service (magic-link / creator / authorized reader) creates an `open` queue row; gated by `require_app_read`, not `privacy.manage`.

**Conventions & gotchas:**
- All routes require permission `privacy.manage` (`require_principal`) except the public erasure-request creation in be-applications.
- Services NEVER send mail; the router/worker fires `notify_erasure_{requested,executed,rejected}` best-effort via `BackgroundTasks` **after** commit (`app.modules.notifications.privacy`, `mail_queue_from_pool`).
- `execute`/`erase` call inner services with `commit=False` so anonymization + status change land in **one transaction**.
- `auskunft` is itself audited as `AuditAction.PII_EXPORT` with the queried email as `target_id` (Art. 30 accountability — must stay traceable WHOSE data was exported). Other audited actions: `ERASURE_REQUESTED/EXECUTED/REJECTED`, `ANONYMIZATION`, `PRINCIPAL_ERASED`.
- `ErasureRequestService.create` validates subject↔id pairing (`ValidationProblem`), checks application existence up-front (404 not 500), and snapshots the applicant email before it gets nulled.
- `PrivacySettingsService.get` self-seeds the id=1 row defensively if a migration seed is missing.
- i18n type/state labels resolved via `_i18n` (locale → `de` → `en` fallback) in the Auskunft export.

**Related:** be-applications, be-audit, be-files, be-notifications, be-auth
