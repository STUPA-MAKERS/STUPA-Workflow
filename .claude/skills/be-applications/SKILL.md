---
name: be-applications
description: Application (Antrag) lifecycle — public create with Altcha/magic-link, versioned data edits with diff, status timeline, internal/public comments, DSGVO anonymization, and dual Principal-or-Applicant access control. Use when working on application CRUD, submission versions, status_event timeline, comments, magic-link/owner/committee read scope, or anonymization in backend/app/modules/applications.
---

# Applications (Anträge) — `backend/app/modules/applications`

**Does:** Full application lifecycle: anonymous/logged-in submission, versioned `data` edits with structured diffs, status timeline, internal/public comments, list/export/search, and DSGVO Art. 17 anonymization. Every read/write route is dual-identity (`A/P`): reachable by a session Principal (permission) or by the applicant via a scoped magic-link token.

**Key files:**
- `models.py` — SQLAlchemy tables: `Application`, `Applicant` (separated PII), `SubmissionVersion`, `StatusEvent`, `MagicLink`, `Comment`.
- `router.py` — `applications` APIRouter; all `/api/applications…` routes, payload caps, magic-link + comment mail background tasks, xlsx export, erasure-request.
- `service.py` — `ApplicationsService`: `create`/`patch`/`get`/`delete`/`timeline`/`versions`/`list_applications`/`list_tasks`/`add_comment`/`list_comments`/`anonymize`; validates against the application's *pinned* form version, syncs promoted `amount`, resolves state colors from the active global flow.
- `access.py` — `Access` dataclass + `require_app_read`/`require_app_edit` deps; unifies Principal-permission, applicant magic-link scope, owner (`created_by`), and committee read-scope into one access object. Exposes `READ_ALL_PERMISSION`/`EDIT_ANY_PERMISSION`.
- `diff.py` — pure `compute_diff` / `is_empty_diff` (added/removed/changed; value-wise, no recursive cell diff).
- `schemas.py` — camelCase Pydantic v2 request/response models (`ApplicationCreate`, `ApplicationOut`, `ApplicationPatch`, `StateOut`, `TimelineEventOut`, `VersionOut`, `ApplicationListItem`, `CommentCreate`, `CommentOut`, `ApplicantOut`).

**Domain / data model:**
- `application` — `type_id` (FK application_type), pinned `form_version_id` + `flow_version_id`, `current_state_id`, `gremium_id`, flat `budget_pot_id` plus tree `budget_id`/`fiscal_year_id` (set at budget assignment, movable via move-fiscal-year), promoted `amount`(Numeric 12,2)/`currency`(CHAR 3) synced from `data`, `data` JSONB (GIN `jsonb_path_ops`), `lang`, `created_by` (OIDC `sub` of logged-in creator; NULL=anonymous), `email_confirmed_at` (guest submissions invisible until magic-link verify, discarded after 12 h; logged-in = confirmed immediately).
- `applicant` — 1:1 separated PII (`email` CITEXT, `name`), `anonymized_at`; FK `ondelete=CASCADE`. Anonymize = email/name → NULL + set `anonymized_at` (application kept; **not** hard-delete — that is the default erasure path).
- `submission_version` — versioned `data` snapshot + `diff` JSONB; `UNIQUE(application_id, version)`, v1 at create, `changed_by`.
- `status_event` — timeline entry per transition: `from_state_id`/`to_state_id`/`transition_id`, `actor`, `note`, `at`.
- `magic_link` — DB stores only `sha256(token||pepper)` hash; `scope` CHECK `IN ('edit','view')`, `expires_at`, `single_use`/`used_at`, unique token-hash index (carries atomic single-use redemption).
- `comment` — `author_kind` CHECK `IN ('principal','applicant')`, `visibility` CHECK `IN ('internal','public')`; applicants see/write only `public`.
- States: `state.kind` (`normal`/`vote`/`approval`…), `state.edit_allowed` (edit-lock), `is_initial`, `config.gremiumId` for vote-states. There is exactly ONE active global flow (typ-flows removed, #28); missing → 404.

**API surface:**
- `POST /api/applications` — public create (anti-abuse: payload cap 413, rate-limit 429, Altcha unless authenticated); separates PII, writes v1, enqueues edit-scope magic-link mail.
- `GET /api/applications` — Principal list; filters `state/gremium/type/topf/budget/q/amountMin/amountMax/createdFrom/createdTo`, `sort`/`order`, `mine`; owner + committee read-scope for users without `application.read`.
- `GET /api/applications/tasks` — open tasks for the Principal (vote-state membership or firable manual transition; own apps too).
- `GET /api/applications/export.xlsx` — `application.export`; same filters, hard cap `EXPORT_MAX_ROWS=10_000` → 413; audited.
- `GET /api/applications/{id}` — A/P read; PII/internal only for Principals; sets `canEdit`/`isOwner`.
- `GET /api/applications/{id}/form` — effective form from the *pinned* version.
- `PATCH /api/applications/{id}` — A(edit)/P; `data` → new version + diff; locked state → 409 unless `application.edit_any`.
- `DELETE /api/applications/{id}` — **admin only**, irreversible (manager/creator cannot).
- `GET /api/applications/{id}/timeline` — A/P status history.
- `GET /api/applications/{id}/versions` — Principal (`application.read`); version history + diff.
- `POST /api/applications/{id}/comments` — A(public)/P; triggers comment mails; applicants restricted to `public`.
- `GET /api/applications/{id}/comments` — A/P; applicants see only `public`.
- `POST /api/applications/{id}/erasure-request` — DSGVO Art. 17 request → privacy queue + notifies data-protection officers (202).

**Conventions & gotchas:**
- Validation runs **before** any DB write (422 not 500), always against the application's *pinned* `form_version_id` (+ pot `BudgetField`s) — not the currently-active form (data-model §4). On PATCH the synthetic system `title` field must be prepended or `_whitelist` drops it (data loss).
- `data` is **strictly whitelisted** to known field keys on create/patch (unknown keys discarded — the public POST must not stash arbitrary GIN-indexed junk).
- `amount`/`currency` are promoted from `data` via `extract_promoted` (default currency EUR) and re-synced on every patch.
- Access is dual: `require_app_read`/`require_app_edit` resolve Principal-permission OR magic-link scope OR `created_by` owner (#24) OR committee read-scope. `_committee_read_clauses` (list) and `_committee_can_read` (detail) **must stay mirrored** (budget view-scope subtree via `path_key` prefix + vote-state `config.gremiumId` + historical meeting vote). `application.read_all`/`application.edit_any` bypass scope/lock.
- Anonymize scrubs ALL PII vectors: applicant row, current `data`, every `submission_version.data` + its stored `diff`, plus deletes magic-links and attachments (via `FilesService` when present). `isPII` keys are unioned across *all* form versions of the type, not just the pinned one (a field marked PII later must still be erased).
- Concurrent PATCH hitting the same `version` (UNIQUE) → caught `IntegrityError` → 409 retry, not 500.
- Never surface raw UUIDs in the UI: actors/editors/authors (`principal.sub`) are resolved to display names server-side via `_author_names` (see [[no-uuids-in-ui]]). State colors are resolved from the active global flow by `key` (old state rows have `color=NULL` after a flow re-save).
- All error paths return `application/problem+json` (RFC-9457); guards/validation use whitelist dispatch, never eval (see `conventions` skill).

**Related:** be-forms, be-flow, be-budget, be-files, be-auth, be-notifications, be-privacy, be-audit
