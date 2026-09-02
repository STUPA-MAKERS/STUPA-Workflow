---
name: be-applications
description: Application lifecycle — public create with Altcha/magic-link, versioned data edits with diff, status timeline, internal/public comments, archiving, public share links, DSGVO anonymization, and dual Principal-or-Applicant access control. Use when working on application CRUD, submission versions, status_event timeline, comments, archive, share links, magic-link/owner/gremium read scope, or anonymization in backend/app/modules/applications.
---

# Applications — `backend/app/modules/applications`

**Does:** Full application lifecycle: anonymous/logged-in submission, versioned `data` edits with structured diffs, status timeline, internal/public comments, list/export/search, and DSGVO Art. 17 anonymization. Every read/write route accepts two identities (`A/P`): a session Principal with the permission, or the applicant with a scoped magic-link token.

**Key files:**
- `models.py` — SQLAlchemy tables: `Application`, `Applicant` (separated PII), `SubmissionVersion`, `StatusEvent`, `MagicLink`, `ApplicationShare`, `Comment`.
- `router.py` — the `applications` APIRouter. It holds all `/api/applications…` routes, payload caps, magic-link and comment mail background tasks, xlsx export, and erasure-request.
- `service.py` — `ApplicationsService`: `create`/`patch`/`get`/`delete`/`timeline`/`versions`/`list_applications`/`list_tasks`/`add_comment`/`list_comments`/`anonymize`. It validates against the application's *pinned* form version, syncs the promoted `amount`, and resolves state colors from the active global flow.
- `access.py` — `Access` dataclass plus the `require_app_read`/`require_app_edit` deps. It merges Principal-permission, applicant magic-link scope, owner (`created_by`), and Gremium read-scope into one access object. It exposes `READ_ALL_PERMISSION`/`EDIT_ANY_PERMISSION`.
- `share.py` — `ShareService` (create/resolve/revoke/list_for) plus `build_public_view`, which reduces an application to the fixed `PublicApplication` shape a public page may show.
- `share_page.py` — the hand-written HTML for `/s/{token}`, with the OpenGraph tags a chat client reads.
- `share_router.py` — the public `GET /s/{token}` route. Mounted at the ROOT, outside `/api`.
- `diff.py` — pure `compute_diff` / `is_empty_diff` (added/removed/changed, value-wise, no recursive cell diff).
- `schemas.py` — camelCase Pydantic v2 request/response models (`ApplicationCreate`, `ApplicationOut`, `ApplicationPatch`, `StateOut`, `TimelineEventOut`, `VersionOut`, `ApplicationListItem`, `CommentCreate`, `CommentOut`, `ApplicantOut`).

**Domain / data model:**
- `application` — `type_id` (FK application_type), pinned `form_version_id` + `flow_version_id`, `current_state_id`, `gremium_id`, flat `budget_pot_id` plus tree `budget_id`/`fiscal_year_id` (set at budget assignment, movable via move-fiscal-year), promoted `amount`(Numeric 12,2)/`currency`(CHAR 3) synced from `data`, `data` JSONB (GIN `jsonb_path_ops`), `lang`, `created_by` (OIDC `sub` of the logged-in creator, NULL=anonymous), `email_confirmed_at` (guest submissions stay invisible until magic-link verify and are discarded after 12 h, logged-in = confirmed immediately).
- `applicant` — 1:1 separated PII (`email` CITEXT, `name`), `anonymized_at`, FK `ondelete=CASCADE`. Anonymize sets email and name to NULL and stamps `anonymized_at`. It keeps the application and is **not** a hard delete. Hard delete is the default erasure path.
- `application_share` — a public read-only link. The DB stores only `HMAC-SHA256(pepper, token)`, like `magic_link`, and never the plaintext. `expires_at` (1–365 days, default 30) plus a nullable `revoked_at`; NOT single-use, because several people are meant to open it. `created_by` is the OIDC `sub`, `label` a note for its creator.
- `submission_version` — versioned `data` snapshot plus `diff` JSONB, `UNIQUE(application_id, version)`, v1 at create, `changed_by`.
- `status_event` — timeline entry per transition: `from_state_id`/`to_state_id`/`transition_id`, `actor`, `note`, `at`.
- `magic_link` — the DB stores only the `sha256(token||pepper)` hash. Fields: `scope` CHECK `IN ('edit','view')`, `expires_at`, `single_use`/`used_at`, and a unique token-hash index that carries the atomic single-use redemption.
- `comment` — `author_kind` CHECK `IN ('principal','applicant')`, `visibility` CHECK `IN ('internal','public')`. Applicants read and write only `public`.
- States: `state.kind` (`normal`/`vote`/`approval`…), `state.edit_allowed` (edit-lock), `is_initial`, `config.gremiumId` for vote-states. There is exactly ONE active global flow (per-type flows removed, #28). A missing flow gives 404.

**API surface:**
- `POST /api/applications` — public create (anti-abuse: payload cap 413, rate-limit 429, Altcha unless authenticated). It separates PII, writes v1, and enqueues the edit-scope magic-link mail.
- `GET /api/applications` — Principal list. Filters: `state/gremium/type/topf/budget/q/amountMin/amountMax/createdFrom/createdTo`, `sort`/`order`, `mine`. Users without `application.read` fall back to the owner and Gremium read-scope.
- `GET /api/applications/tasks` — open tasks for the Principal (vote-state membership or firable manual transition, own applications too).
- `GET /api/applications/export.xlsx` — needs `application.export`. Same filters, hard cap `EXPORT_MAX_ROWS=10_000` → 413. The export is audited.
- `GET /api/applications/{id}` — A/P read. PII and internal data go to Principals only. It sets `canEdit`/`isOwner`.
- `GET /api/applications/{id}/form` — effective form from the *pinned* version.
- `PATCH /api/applications/{id}` — A(edit)/P. A `data` change writes a new version plus a diff. A locked state gives 409 unless the caller holds `application.edit_any`.
- `DELETE /api/applications/{id}` — **admin only**, irreversible (manager/creator cannot).
- `POST` / `DELETE /api/applications/{id}/archive` — needs `application.archive`. Reversible and destroys nothing: the application stays fully readable, it only leaves the working list. `archived_at` is a timestamp, not a flag. The list filter is a tri-state (`archived=false|true|all`, default `false`).
- `POST` / `GET` / `DELETE /api/applications/{id}/shares[/{share_id}]` — needs `application.share`. Mint, list and revoke public links. The POST response is the ONLY place the plaintext token ever appears; a listing returns `url: null`.
- `GET /s/{token}` — **public, unauthenticated, outside `/api`**. Server-rendered HTML for one shared application.
- `GET /api/applications/{id}/timeline` — A/P status history.
- `GET /api/applications/{id}/versions` — Principal (`application.read`). Version history plus diff.
- `POST /api/applications/{id}/comments` — A(public)/P. It triggers comment mails. Applicants may write only `public` comments.
- `GET /api/applications/{id}/comments` — A/P. Applicants see only `public` comments.
- `POST /api/applications/{id}/erasure-request` — DSGVO Art. 17 request → privacy queue, and it notifies the data-protection officers (202).

**Conventions & gotchas:**
- Validation runs **before** any DB write (422, not 500). It always uses the application's *pinned* `form_version_id` plus the pot `BudgetField`s, not the currently-active form (data-model §4). On PATCH you must prepend the synthetic system `title` field. If you do not, `_whitelist` drops it and the data is lost.
- Create and patch **strictly whitelist** `data` to known field keys. They discard unknown keys, because the public POST must not stash arbitrary GIN-indexed junk.
- `extract_promoted` promotes `amount`/`currency` out of `data` (default currency EUR) and re-syncs them on every patch.
- Access is dual: `require_app_read`/`require_app_edit` resolve Principal-permission OR magic-link scope OR `created_by` owner (#24) OR Gremium read-scope. `_committee_read_clauses` (list) and `_committee_can_read` (detail) **must stay mirrored** (budget view-scope subtree from the `path_key` prefix, vote-state `config.gremiumId`, historical meeting vote). `application.read_all`/`application.edit_any` bypass scope and lock.
- Anonymize scrubs ALL PII vectors: the applicant row, the current `data`, every `submission_version.data` and its stored `diff`. It also deletes magic-links and attachments (through `FilesService` when present). It unions the `isPII` keys across *all* form versions of the type, not only the pinned one. A field marked PII later must still be erased.
- The share routes are **two different decisions**. Creating a link is gated on `application.share`, deliberately NOT on the read permission: someone reading through a magic link must not be able to publish. Opening a link is unauthenticated and does NOT go through `resolve_access` — that function answers "may this principal read this?", and here there is no principal, so reusing it would mean inventing one.
- A share token that is unknown, expired or revoked all answer the same **404**, never 410. "This link expired" tells a stranger they found a real one and were only too late.
- The public view drops every field marked `is_pii`, reading the SAME definitions the PDF renders from through `_field_from_row`. Two readers of one definition cannot drift into disagreeing about what counts as personal. Comments and version history stay off the page entirely.
- The OpenGraph preview carries the **title only**. That text lands permanently on a chat server we do not control; a preview saying "€4,200, rejected" has published a decision to everyone in the room before anyone opened the link.
- `ShareService.create` flushes, it does not just `add`. `id` and `created_at` are server defaults, so without the flush the response model has nothing to serialize.
- nginx proxies `/s/<token>` to the API **ahead of the SPA fallback** (`deploy/web/nginx.conf`). Without that location the Angular shell swallows the path and every link preview shows a bare URL.
- Concurrent PATCH hitting the same `version` (UNIQUE) → caught `IntegrityError` → 409 retry, not 500.
- Never surface raw UUIDs in the UI. `_author_names` resolves actors, editors, and authors (`principal.sub`) to display names on the server (see [[no-uuids-in-ui]]). The service resolves state colors from the active global flow by `key` (old state rows carry `color=NULL` after a flow re-save).
- All error paths return `application/problem+json` (RFC-9457). Guards and validation use whitelist dispatch, never eval (see the `conventions` skill).

**Related:** be-forms, be-flow, be-budget, be-files, be-auth, be-notifications, be-privacy, be-audit
