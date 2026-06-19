---
name: revert-feature-scope
description: audit-log revert now covers config + status transitions + budget/bookings; design rules & deliberate non-goals
metadata: 
  node_type: memory
  type: project
---

Audit-log "Zurücknehmen" (RevertService, `config_revision/revert.py`) is a **dispatcher**
keyed on the audit entry, extended 2026-06-18 beyond config to three domains:

- **Config** (form/flow/site_config): `data.revisionId` present → restore predecessor snapshot; first version (no prev) → `nothing_to_revert`.
- **Status transitions** (`status_change`): `FlowService.revert_status` moves app back to fromState **only if still in toState** (`stale_revert`); writes reverse StatusEvent (transition_id=NULL) + status_change audit → itself revertable (redo). Side effects (cancelled votes, fired webhooks/mails) are NOT undone — state-only, by design.
- **Budget/money** (`BudgetTreeService.revert_audit`): create→delete, transfer→delete both rows, booking→delete + reopen paid invoice, node_update/expense_update→restore captured `data.before`, allocation_set→restore `data.previousAllocated` (or remove row).

Deliberate NON-goals (chosen by user, recommended options):
- **Deletes are not revertable** (no un-delete/recreate) → `not_revertable`.
- `budget_assign` / `budget_move_fiscal_year` are NOT revertable (kept scope to bookings/budget-changes/transitions).
- First config version → button hidden, not revert-to-empty.

Mechanics:
- Reversible mutations capture JSON-safe **before-state** (`before` / `previousAllocated`) **and after-state** (`after`) in audit `data` via `_json_safe()`; restore via `BudgetNodeUpdate(**before)` / `ExpenseUpdate(**before)` (pydantic coerces str→Decimal/date/UUID). Update reverts stale-check **all** restored fields against `after` (`_assert_not_stale`, Decimal-tolerant — DB round-trip drops scale "70"→"70.00").
- `AuditService.revertable_flags()` drives the FE `revertable` flag (cheap/static; batch prev-lookup for config). Backend stays authoritative at click (409 on stale).
- Single gate: **`audit.revert`** (admin-only, seeded migration 0034). No per-domain perm check — fine because admin has all rights ([[admin-domain-rules]]).
- FE distinguishes 409 `code`s (stale_revert / nothing_to_revert / already_reverted / not_revertable) into distinct toasts; config-diff card layout + dialog `size="sm"`.

Branch: feat/config-versioning-audit-revert. Related: [[flow-engine-redesign]], [[budget-tab-redesign]].
