---
name: revert-feature-scope
description: audit-log revert now covers config + status transitions + budget/bookings. Design rules and deliberate non-goals
metadata: 
  node_type: memory
  type: project
---

The audit-log revert action (RevertService, `config_revision/revert.py`, German UI label
"Zurücknehmen") is a **dispatcher** keyed on the audit entry. On 2026-06-18 we extended it
beyond config to three domains:

- **Config** (form/flow/site_config): `data.revisionId` present → restore the predecessor snapshot. First version (no prev) → `nothing_to_revert`.
- **Status transitions** (`status_change`): `FlowService.revert_status` moves the application back to fromState **only if it is still in toState** (`stale_revert`). It writes a reverse StatusEvent (transition_id=NULL) + a status_change audit entry, so the revert is itself revertable (redo). It does NOT undo the side effects (canceled votes, fired webhooks and mails). The revert is state-only, by design.
- **Budget/money** (`BudgetTreeService.revert_audit`): create→delete, transfer→delete both rows, booking→delete + reopen paid invoice, node_update/expense_update→restore captured `data.before`, allocation_set→restore `data.previousAllocated` (or remove row).

Deliberate NON-goals (chosen by user, recommended options):
- **Deletes are not revertable** (no un-delete/recreate) → `not_revertable`.
- `budget_assign` / `budget_move_fiscal_year` are NOT revertable (kept scope to bookings/budget-changes/transitions).
- First config version → button hidden, not revert-to-empty.

Mechanics:
- A reversible mutation captures a JSON-safe **before-state** (`before` / `previousAllocated`) **and after-state** (`after`) in audit `data` via `_json_safe()`. The revert restores it via `BudgetNodeUpdate(**before)` / `ExpenseUpdate(**before)` (pydantic coerces str→Decimal/date/UUID). An update revert stale-checks **all** restored fields against `after` (`_assert_not_stale`, Decimal-tolerant — the DB round-trip drops scale, "70"→"70.00").
- `AuditService.revertable_flags()` drives the FE `revertable` flag (cheap and static, with a batch prev-lookup for config). The backend stays authoritative at click time (409 on stale).
- Single gate: **`audit.revert`** (admin-only, seeded migration 0034). No per-domain perm check — fine because admin has all rights ([[admin-domain-rules]]).
- The FE maps the 409 `code`s (stale_revert / nothing_to_revert / already_reverted / not_revertable) to distinct toasts. Config-diff card layout + dialog `size="sm"`.

Branch: feat/config-versioning-audit-revert. Related: [[flow-engine-redesign]], [[budget-tab-redesign]].
