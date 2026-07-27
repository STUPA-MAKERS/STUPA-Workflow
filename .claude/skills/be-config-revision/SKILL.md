---
name: be-config-revision
description: Append-only versioned config snapshots (form/flow/site_config) with field-diff, sidebar restore, and audit-log revert that spans config, application status and budget/bookings. Use when working on config versioning, ConfigRevision, snapshot/diff/restore, reapply_snapshot, RevertService, or audit revert under /admin/config-revisions and /admin/audit/{id}/revert.
---

# Config Revision — `backend/app/modules/config_revision`

**Does:** Maintains an append-only snapshot chain of every versioned config: forms, the global flow, and branding/site_config. It powers the FE version sidebar with list, field-diff and restore. It also holds the central audit-log revert dispatcher. That dispatcher undoes config changes, application status transitions, and budget/money mutations.

**Key files:**
- `models.py` — the `ConfigRevision` ORM. The table is append-only. A DB trigger rejects UPDATE, DELETE and TRUNCATE (migration 0034 plus the `audit_writer` least-privilege grant).
- `service.py` — `ConfigRevisionService`: `record` (append snapshot + linked audit entry), `head`, `get`, `list_for`, `diff`. It also holds the entity-type constants and `_flatten`/`_lock_key`.
- `reapply.py` — `reapply_snapshot`: replays a snapshot as a new active version through the owning config service (shared restore/revert core).
- `revert.py` — `RevertService`: the audit-log revert dispatcher (config / status_change / budget).
- `schemas.py` — `ConfigRevisionOut` (sidebar row), `ConfigRevisionDiffOut` (reuses `applications.diff.DataDiff`).
- `router.py` — `/admin/config-revisions` read + restore endpoints.

**Domain / data model:**
- Table `config_revision`: `id` (uuid), `entity_type` (`form`|`flow`|`site_config`), `entity_id` (form → `application_type_id`, flow and site_config → `'global'` = `GLOBAL_ID`), `version` (monotonic per entity), `snapshot` (JSONB, natural config form, config only and never principal PII), `prev_revision_id` (self-FK `ondelete=RESTRICT`, NULL = first state), `created_by` (OIDC `sub`), `at`.
- Constraints: `uq_config_revision_entity_version` (entity_type, entity_id, version), index `ix_config_revision_entity`. Chain: `prev_revision_id` links successive states. A diff compares two consecutive snapshots.
- Entity constants: `ENTITY_FORM='form'`, `ENTITY_FLOW='flow'`, `ENTITY_SITE_CONFIG='site_config'` (= audit `target_type`).
- Each snapshot links from the audit entry via `data.revisionId` (id-reference only) + `data.version`.

**API surface:**
- `GET  /api/admin/config-revisions?entityType=&entityId=` — snapshot feed for an entity, newest first. The reader needs `audit.read` OR `form.configure`/`flow.configure`/`admin.site`. The head row carries `isCurrent`.
- `GET  /api/admin/config-revisions/{id}/diff` — field-diff against the predecessor (`DataDiff`, consumed by the FE `mapDiff`).
- `POST /api/admin/config-revisions/{id}/restore` → 204 — replay an older snapshot as a new active version. The operation goes forward and never blocks on a conflict. The per-entity gate is `_RESTORE_PERM` (form.configure / flow.configure / admin.site).
- `POST /api/admin/audit/{entry_id}/revert` — lives in the `be-audit` router and calls `RevertService`. The gate is `audit.revert`. It undoes a config change (predecessor snapshot), a `status_change`, or a budget action.

**Conventions & gotchas:**
- **Append-only, never delete.** Restore and revert always go forward. Both write a NEW version through the normal config save path (`reapply_snapshot`). They differ only in the audit `action` and `extra_data`. Restore writes `CONFIG_CHANGE` plus `restoredFromVersion`. An audit revert writes `CONFIG_REVERT` plus `revertedAuditId` and `revertedRevisionId`.
- `record()` takes `pg_advisory_xact_lock(_lock_key(...))` BEFORE it reads the head. Concurrent appends then serialize, and `version`/`prev` stay consistent. The lock key is a deterministic BLAKE2b digest as a signed bigint. Never use Python `hash()` here, because it is randomized per process. The key goes into the raw SQL as an int constant, not as a bind parameter.
- **No commit here.** The transaction of the caller commits atomically with the config mutation. `record` only calls `flush`.
- `_flatten` maps the natural snapshot of each entity onto identity-keyed maps (`field:<key>`, `state:<key>`, `transition:<from>-><to>[:branch]`, `meta:*`). `compute_diff` then yields a meaningful per-field add, remove or change instead of an opaque list compare.
- `reapply.py` uses **lazy imports** of the config services (admin `ConfigService`, forms `FormsService`, admin `SiteConfigService`) to avoid import cycles.
- **RevertService dispatch** keys on the audit entry. `data.revisionId` → `_revert_config`. `action==STATUS_CHANGE` → `_revert_status` (FlowService). An action in `REVERTABLE_BUDGET_ACTIONS` → `_revert_budget` (BudgetTreeService). Anything else gives `409 not_revertable`.
- A config revert restores `R.prev` only when `head==R`, else it gives `409 stale_revert`. The first state has no prev and gives `409 nothing_to_revert`. The scope covers config, status and budget/bookings only. Deletes and assign/move stay out on purpose ([[revert-feature-scope]]). Every revert is audited itself, and where it makes sense you can revert it again.
- A snapshot must contain ONLY config and never principal PII. The chain is immutable, so DSGVO deletion must stay intact.

**Related:** be-audit, be-admin, be-forms, be-flow, be-budget, be-applications
