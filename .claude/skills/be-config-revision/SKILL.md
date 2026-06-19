---
name: be-config-revision
description: Append-only versioned config snapshots (form/flow/site_config) with field-diff, sidebar restore, and audit-log revert spanning config + application status + budget/bookings. Use when working on config versioning, ConfigRevision, snapshot/diff/restore, reapply_snapshot, RevertService, or audit revert under /admin/config-revisions and /admin/audit/{id}/revert.
---

# Config Revision — `backend/app/modules/config_revision`

**Does:** Maintains an append-only snapshot chain of every versioned config (forms, global flow, branding/site_config), powers the FE version-sidebar (list + field-diff + restore), and provides the central audit-log Revert dispatcher that undoes config changes, application status transitions, and budget/money mutations.

**Key files:**
- `models.py` — `ConfigRevision` ORM (append-only; UPDATE/DELETE/TRUNCATE rejected by a DB trigger, migration 0034 + `audit_writer` least-priv grant).
- `service.py` — `ConfigRevisionService`: `record` (append snapshot + linked audit entry), `head`, `get`, `list_for`, `diff`; entity-type constants + `_flatten`/`_lock_key`.
- `reapply.py` — `reapply_snapshot`: replays a snapshot as a new active version through the owning config service (shared restore/revert core).
- `revert.py` — `RevertService`: audit-log revert dispatcher (config / status_change / budget).
- `schemas.py` — `ConfigRevisionOut` (sidebar row), `ConfigRevisionDiffOut` (reuses `applications.diff.DataDiff`).
- `router.py` — `/admin/config-revisions` read + restore endpoints.

**Domain / data model:**
- Table `config_revision`: `id` (uuid), `entity_type` (`form`|`flow`|`site_config`), `entity_id` (form: `application_type_id`; flow/site_config: `'global'` = `GLOBAL_ID`), `version` (monotonic per entity), `snapshot` (JSONB, natural config form — config only, never principal PII), `prev_revision_id` (self-FK `ondelete=RESTRICT`, NULL = first state), `created_by` (OIDC `sub`), `at`.
- Constraints: `uq_config_revision_entity_version` (entity_type, entity_id, version), index `ix_config_revision_entity`. Chain: `prev_revision_id` links successive states; diff = consecutive snapshots.
- Entity constants: `ENTITY_FORM='form'`, `ENTITY_FLOW='flow'`, `ENTITY_SITE_CONFIG='site_config'` (= audit `target_type`).
- Each snapshot links from the audit entry via `data.revisionId` (id-reference only) + `data.version`.

**API surface:**
- `GET  /api/admin/config-revisions?entityType=&entityId=` — snapshot feed for an entity (newest first); reader = `audit.read` OR `form.configure`/`flow.configure`/`admin.site`. Head row flagged `isCurrent`.
- `GET  /api/admin/config-revisions/{id}/diff` — field-diff vs predecessor (`DataDiff`, consumed by FE `mapDiff`).
- `POST /api/admin/config-revisions/{id}/restore` → 204 — replay an older snapshot as a new active version (forward op, no conflict block); per-entity gate `_RESTORE_PERM` (form.configure / flow.configure / admin.site).
- `POST /api/admin/audit/{entry_id}/revert` — lives in `be-audit` router, calls `RevertService`; gated by `audit.revert`. Undoes config-change (predecessor snapshot), `status_change`, or budget actions.

**Conventions & gotchas:**
- **Append-only, never delete.** Restore/revert always go forward: they write a NEW version through the normal config save path (`reapply_snapshot`), differing only by audit `action`/`extra_data`. Restore → `CONFIG_CHANGE` (+ `restoredFromVersion`); audit revert → `CONFIG_REVERT` (+ `revertedAuditId`, `revertedRevisionId`).
- `record()` takes `pg_advisory_xact_lock(_lock_key(...))` BEFORE reading head so concurrent appends serialize and `version`/`prev` stay consistent. The lock key is a deterministic BLAKE2b digest as signed bigint (never Python `hash()` — randomized per process), embedded as an int constant in raw SQL (no bind param).
- **No commit here** — the caller's transaction commits atomically with the config mutation. `record` only `flush`es.
- `_flatten` maps each entity's natural snapshot onto identity-keyed maps (`field:<key>`, `state:<key>`, `transition:<from>-><to>[:branch]`, `meta:*`) so `compute_diff` yields meaningful per-field add/remove/change instead of opaque list compares.
- `reapply.py` uses **lazy imports** of config services (admin `ConfigService`, forms `FormsService`, admin `SiteConfigService`) to avoid import cycles.
- **RevertService dispatch** keys on the audit entry: `data.revisionId` → `_revert_config`; `action==STATUS_CHANGE` → `_revert_status` (FlowService); action in `REVERTABLE_BUDGET_ACTIONS` → `_revert_budget` (BudgetTreeService); else `409 not_revertable`.
- Config revert restores `R.prev` only if `head==R`, else `409 stale_revert`; first state (no prev) → `409 nothing_to_revert`. Scope = config + status + budget/bookings only — deletes & assign/move are deliberately excluded ([[revert-feature-scope]]). Every revert is itself audited and (where sensible) re-revertable.
- Snapshot must contain ONLY config, never principal PII, so DSGVO deletion stays intact even though the chain is immutable.

**Related:** be-audit, be-admin, be-forms, be-flow, be-budget, be-applications
