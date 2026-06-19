---
name: be-audit
description: Append-only audit log with a sha256(prev_hash||canonical_json) hash chain, DB-trigger-enforced no-UPDATE/DELETE, chain verification, and a closed AuditAction catalog (login/status_change/vote_cast/config_change/config_revert/budget_*/pii_*/delegation_*). Other modules write via the record() hook; read/verify/revert under audit.read/audit.verify/audit.revert at GET/POST /api/admin/audit. Use when working on audit logging, hash-chain integrity, action catalog, or audit-log config/budget revert in backend/app/modules/audit.
---

# Audit Log — `backend/app/modules/audit`

**Does:** Append-only, tamper-evident audit log: every security-/config-/money-relevant action is hashed into a forward-linked chain (`hash = sha256(prev_hash || canonical_json(entry))`) that can be re-verified end to end. Other modules write entries through a service hook; admins read, verify, and revert config/budget changes from the log.

**Key files:**
- `service.py` — `AuditService` (record/verify_chain/query/query_cursor/list_actors + actor/target/data-id resolvers) and the module-level `record()` hook other modules call.
- `models.py` — `AuditEntry` ORM row (`audit_entry` table). Append-only: UPDATE/DELETE blocked by DB trigger + least-privilege `audit_writer` grant (in baseline migration).
- `hashing.py` — pure `canonical_payload(...)` (deterministic UTF-8 bytes, UTC-normalized `at`, sorted keys) and `compute_hash(prev_hash, canonical)`.
- `actions.py` — `AuditAction` StrEnum (closed action catalog) + `REVERTABLE_BUDGET_ACTIONS` frozenset.
- `router.py` — `/admin/audit` FastAPI router (list/actors/verify/revert).
- `schemas.py` — read-only camelCase out-models (`AuditEntryOut`, `AuditPageOut`, `AuditActorOut`, `ChainVerificationOut`, `AuditRevertOut`).
- `__init__.py` — re-exports `AuditAction`, `AuditService`, `record`.

**Domain / data model:**
- Table `audit_entry`: `id bigserial` PK (generation order = chain order), `actor` (Principal `sub`, nullable = system/anon), `action` (text, from `AuditAction`), `target_type`/`target_id` (nullable), `at` (tz-aware, `now()` default), `data` JSONB (`{}` default; **id-references/metadata only, never raw PII**), `prev_hash` bytea (nullable; genesis links from `b""`), `hash` bytea. Indexes: `ix_audit_entry_at`, `ix_audit_entry_target_type_target_id`.
- `AuditAction` catalog: `login`, `status_change`, `vote_cast`, `config_change`, `config_activation`, `config_revert`, `role_change`, `delegation_grant/revoke/use/substitute_add/substitute_remove`, `export`, `meeting_delete`, `webhook_config`, `attachment_quarantine/delete`, PII/DSGVO (`pii_access/deletion/export`, `anonymization`, `erasure_requested/executed/rejected`, `principal_erased`, `retention_anonymize`), budget (`budget_node_create/update/delete`, `budget_allocation_set`, `budget_expense_create/update/delete`, `budget_transfer_create`, `budget_invoice_create/update/delete`, `budget_assign`, `budget_move_fiscal_year`).
- `REVERTABLE_BUDGET_ACTIONS` = node_create/update, allocation_set, transfer_create, expense_create/update. Deletes + assign/move are deliberately NOT revertable (see [[revert-feature-scope]]).
- Chain verification (`ChainVerification` dataclass): catches `hash_mismatch` (mutated field) and `prev_hash_mismatch` (removed/inserted row); reports first `broken_at` id (fail-closed).

**API surface** (mounted under `/api`, prefix `/admin/audit`):
- `GET /api/admin/audit` — P(`audit.read`); keyset-paged log (`before` cursor, newest first), filters `action`/`actor`/`since`/`until`; resolves actor names, target labels, and embedded `data` UUIDs to clear names. Returns `AuditPageOut` (`items`, `nextCursor`, `hasMore`).
- `GET /api/admin/audit/actors` — P(`audit.read`); distinct actors with resolved names (actor-filter dropdown).
- `GET /api/admin/audit/verify` — P(`audit.verify`); recompute the whole chain, returns `ChainVerificationOut`.
- `POST /api/admin/audit/{entry_id}/revert` — P(`audit.revert`); undo the config/budget change described by the entry via `config_revision.RevertService`; 404 if entry/revision missing, 409 if not revertable / stale. Revert is itself logged + revertable.

**Conventions & gotchas:**
- **Write via the hook, never raw-insert:** `await record(session, actor=..., action=..., target_type=..., target_id=..., data=...)`. It does NOT commit — it runs in the caller's transaction (so the audit row is atomic with the audited change). `data` MUST contain only id-references/metadata, never raw PII (caller's responsibility).
- **Append serialization:** `record()` takes a fixed transaction advisory lock (`pg_advisory_xact_lock`, key `0x415544495400`) before reading the previous `hash`, so concurrent appends can't race on `prev_hash`. Don't bypass it.
- **Hash determinism:** `canonical_payload` sorts keys + uses compact separators and normalizes `at` to UTC ISO-8601 (naive treated as UTC) so the digest is reproducible regardless of key insertion order or server timezone. Non-JSON-native values in `data` raise `TypeError` on purpose (fail-closed). Any change to canonicalization breaks verification of existing rows.
- **No mutation path:** the ORM has no update/delete for `AuditEntry`; the DB enforces append-only via trigger + the `audit_writer` least-privilege grant (defined in the baseline migration). Don't add an UPDATE/DELETE statement.
- **`verify_chain` streams** rows via a server-side cursor (`stream_scalars`) so very long logs stay verifiable without loading the whole chain into memory.
- **Three separate permissions:** `audit.read` (read/list/actors), `audit.verify` (chain check), `audit.revert` (destructive undo) — keep them distinct; RBAC is fail-closed (401 no session, 403 missing perm).
- **No UUIDs in UI** ([[no-uuids-in-ui]]): the router batch-resolves actor `sub`, `(target_type,target_id)`, and every UUID-shaped value inside `data` to clear names server-side via `resolve_actor_names`/`resolve_target_labels`/`resolve_data_ids` (i18n labels prefer `de`). Resolution is best-effort; deleted/unknown ids fall back to the raw value in the FE. Adding a new `target_type` or `data` entity ref means extending these resolvers.
- `query_cursor` reads `limit+1` to compute `has_more` without a COUNT (scales on long logs); the older offset-based `query()` still exists for non-cursor callers.
- `revertable_flags` is a cheap, mostly-static per-row property for the list (it does a single batch `ConfigRevision` prev-revision lookup); the authoritative stale/conflict check happens at revert time (409), not here.

**Related:** be-config-revision, be-auth, be-budget, be-admin
