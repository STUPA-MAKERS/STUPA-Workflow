---
name: be-audit
description: Append-only audit log with a sha256(prev_hash||canonical_json) hash chain, DB-trigger-enforced no-UPDATE/DELETE, chain verification, and a closed AuditAction catalog (login/status_change/vote_cast/config_change/config_revert/budget_*/pii_*/delegation_*). Other modules write through the record() hook. Read, verify and revert sit under audit.read/audit.verify/audit.revert at GET/POST /api/admin/audit. Use when working on audit logging, hash-chain integrity, action catalog, or audit-log config/budget revert in backend/app/modules/audit.
---

# Audit Log — `backend/app/modules/audit`

**Does:** Append-only, tamper-evident audit log. The service hashes every security, config, or money relevant action into a forward-linked chain (`hash = sha256(prev_hash || canonical_json(entry))`). The verify route re-checks that chain end to end. Other modules write entries through a service hook. Admins read, verify, and revert config/budget changes from the log.

**Key files:**
- `service.py` — `AuditService` (record/verify_chain/query/query_cursor/list_actors + actor/target/data-id resolvers) and the module-level `record()` hook that other modules call.
- `models.py` — `AuditEntry` ORM row (`audit_entry` table). Append-only: a DB trigger and the least-privilege `audit_writer` grant block UPDATE and DELETE (both in the baseline migration).
- `hashing.py` — pure `canonical_payload(...)` (deterministic UTF-8 bytes, UTC-normalized `at`, sorted keys) and `compute_hash(prev_hash, canonical)`.
- `actions.py` — `AuditAction` StrEnum (closed action catalog) + `REVERTABLE_BUDGET_ACTIONS` frozenset.
- `router.py` — `/admin/audit` FastAPI router (list/actors/verify/revert).
- `schemas.py` — read-only camelCase out-models (`AuditEntryOut`, `AuditPageOut`, `AuditActorOut`, `ChainVerificationOut`, `AuditRevertOut`).
- `__init__.py` — re-exports `AuditAction`, `AuditService`, `record`.

**Domain / data model:**
- Table `audit_entry`: `id bigserial` PK (generation order = chain order), `actor` (Principal `sub`, nullable = system/anon), `action` (text, from `AuditAction`), `target_type`/`target_id` (nullable), `at` (tz-aware, `now()` default), `data` JSONB (`{}` default, **id-references/metadata only, never raw PII**), `prev_hash` bytea (nullable, genesis links from `b""`), `hash` bytea. Indexes: `ix_audit_entry_at`, `ix_audit_entry_target_type_target_id`.
- `AuditAction` catalog: `login`, `status_change`, `vote_cast`, `config_change`, `config_activation`, `config_revert`, `role_change`, `delegation_grant/revoke/use/substitute_add/substitute_remove`, `export`, `meeting_delete`, `webhook_config`, `attachment_quarantine/delete`, PII/DSGVO (`pii_access/deletion/export`, `anonymization`, `erasure_requested/executed/rejected`, `principal_erased`, `retention_anonymize`), budget (`budget_node_create/update/delete`, `budget_allocation_set`, `budget_expense_create/update/delete`, `budget_transfer_create`, `budget_invoice_create/update/delete`, `budget_assign`, `budget_move_fiscal_year`).
- `REVERTABLE_BUDGET_ACTIONS` = node_create/update, allocation_set, transfer_create, expense_create/update. Deletes and assign/move are NOT revertable on purpose (see [[revert-feature-scope]]).
- Chain verification (`ChainVerification` dataclass): catches `hash_mismatch` (mutated field) and `prev_hash_mismatch` (removed/inserted row). It reports the first `broken_at` id (fail-closed).

**API surface** (mounted under `/api`, prefix `/admin/audit`):
- `GET /api/admin/audit` — P(`audit.read`). Keyset-paged log (`before` cursor, newest first) with the filters `action`/`actor`/`since`/`until`. It resolves actor names, target labels, and embedded `data` UUIDs to clear names. Returns `AuditPageOut` (`items`, `nextCursor`, `hasMore`).
- `GET /api/admin/audit/actors` — P(`audit.read`). Distinct actors with resolved names (actor-filter dropdown).
- `GET /api/admin/audit/verify` — P(`audit.verify`). It recomputes the whole chain and returns `ChainVerificationOut`.
- `POST /api/admin/audit/{entry_id}/revert` — P(`audit.revert`). It undoes the config/budget change of the entry through `config_revision.RevertService`. It returns 404 when the entry or the revision is missing, and 409 when the change is not revertable or is stale. The revert is itself logged and revertable.

**Conventions & gotchas:**
- **Write through the hook, never raw-insert:** `await record(session, actor=..., action=..., target_type=..., target_id=..., data=...)`. It does NOT commit. It runs in the caller's transaction, so the audit row is atomic with the audited change. `data` MUST hold only id-references and metadata, never raw PII. That is the caller's responsibility.
- **Append serialization:** `record()` takes a fixed transaction advisory lock (`pg_advisory_xact_lock`, key `0x415544495400`) before it reads the previous `hash`. Concurrent appends therefore cannot race on `prev_hash`. Do not bypass the lock.
- **Hash determinism:** `canonical_payload` sorts the keys, uses compact separators, and normalizes `at` to UTC ISO-8601 (a naive value counts as UTC). The digest is therefore reproducible for any key insertion order and any server timezone. Non-JSON-native values in `data` raise `TypeError` on purpose (fail-closed). Any change to the canonicalization breaks verification of the existing rows.
- **No mutation path:** the ORM has no update or delete for `AuditEntry`. The DB enforces append-only with a trigger and the `audit_writer` least-privilege grant (defined in the baseline migration). Do not add an UPDATE or DELETE statement.
- **`verify_chain` streams** rows through a server-side cursor (`stream_scalars`). Very long logs stay verifiable because the whole chain never enters memory.
- **Three separate permissions:** `audit.read` (read/list/actors), `audit.verify` (chain check), and `audit.revert` (destructive undo). Keep them distinct. RBAC is fail-closed (401 without a session, 403 without the permission).
- **No UUIDs in UI** ([[no-uuids-in-ui]]): the router batch-resolves the actor `sub`, `(target_type,target_id)`, and every UUID-shaped value inside `data` to clear names on the server. It calls `resolve_actor_names`/`resolve_target_labels`/`resolve_data_ids` (i18n labels prefer `de`). Resolution is best-effort. Deleted or unknown ids fall back to the raw value in the FE. A new `target_type` or `data` entity ref needs an extension of these resolvers.
- `query_cursor` reads `limit+1` to compute `has_more` without a COUNT, which scales on long logs. The older offset-based `query()` still exists for non-cursor callers.
- `revertable_flags` is a cheap, mostly-static per-row property for the list. It does a single batch `ConfigRevision` prev-revision lookup. The authoritative stale/conflict check happens at revert time (409), not here.

**Related:** be-config-revision, be-auth, be-budget, be-admin
