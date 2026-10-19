---
name: revert-feature-scope
description: Audit-log revert covers config, status transitions and budget/bookings. Deletes and assign/move stay out on purpose. Design rules and permissions
metadata:
  node_type: memory
  type: project
---

The audit-log revert ("Zurücknehmen", `POST /api/admin/audit/{id}/revert`) is a
**dispatcher** keyed on the audit entry: `RevertService` in `config_revision/revert.py`.

- **Config** (form/flow/site_config): `data.revisionId` present → restore the predecessor
  snapshot as a new version. The first version has no predecessor → `nothing_to_revert`, and
  the frontend hides the button.
- **Status change** (`status_change`): `FlowService.revert_status` moves the application back
  **only while it is still in the target state** (`stale_revert`). It writes a reverse status
  event and its own audit entry, so the revert is itself revertable. It cancels the votes of
  the state it leaves. It does NOT undo other side effects: sent webhooks and mails stay sent.
- **Budget** (`BudgetTreeService.revert_audit`, `budget/tree/revert.py`, only the actions in
  `REVERTABLE_BUDGET_ACTIONS`): a create (booking, transfer, cost centre) is deleted, a transfer
  with both rows; a node or booking update restores `data.before`; an allocation restores
  `data.previousAllocated`, or removes the row when there was none. A reverted booking leaves
  the invoice status as it is, because a booking never sets it.

**Deliberate non-goals** (the user chose them):

- **Deletes are not revertable** (no un-delete) → `not_revertable`.
- `budget_assign` and `budget_move_fiscal_year` are not revertable.
- The first config version has no revert-to-empty.

**Mechanics:**

- A reversible mutation stores a JSON-safe before-state (`before` / `previousAllocated`) and
  after-state (`after`) in the audit `data` (`_json_safe`). An update revert checks **every**
  field of `after` against the current row before it restores (`_assert_not_stale`). The check
  is Decimal-tolerant, because the DB round trip changes the scale ("70" → "70.00").
- `AuditService.revertable_flags()` drives the `revertable` flag of the list. It is cheap and
  static, with one batch lookup for config predecessors. The backend decides at click time
  (409 when stale).
- **Permissions:** `audit.revert` plus the permission of the original operation: `form.configure`
  / `flow.configure` / `admin.site` for config, `application.transition` for a status change,
  `budget.structure` (node, allocation) or `budget.book` (booking, transfer) for budget.
- The frontend (`pages/admin/audit/audit-log.component.ts`) maps the 409 codes `stale_revert`,
  `nothing_to_revert`, `already_reverted` and `not_revertable` to separate toasts.
