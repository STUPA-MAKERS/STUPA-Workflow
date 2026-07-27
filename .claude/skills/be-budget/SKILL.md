---
name: be-budget
description: Hierarchical cost center budget tree with fiscal years, top-down allocations, bookings (expenses/income), cost-center transfers, accounts, and ZUGFeRD/Factur-X invoice import. The audit log records every money mutation, and most are revertable. Use when working on Budget, BudgetTreeService, cost centers, fiscal years, allocations, expenses/transfers, accounts, invoices, ZUGFeRD import, /api/budgets, /api/expenses, /api/invoices in backend/app/modules/budget.
---

# Budget tree & bookings — `backend/app/modules/budget`

**Does:** Hierarchical cost center budgeting. The tree carries fiscal years per top-level node, top-down allocations, bookings (expenses/income), transfers, free-standing bank accounts, and invoices imported from ZUGFeRD/Factur-X PDFs. The append-only audit log records every money mutation. Most mutations are revertable.

**Key files:**
- `tree_models.py` — SQLAlchemy models for the tree: `Budget`, `FiscalYear`, `BudgetAllocation`, `BudgetExpense`, `Account`, `Invoice` (EUR-only, `Numeric(12,2)`).
- `models.py` — legacy flat-pot models `BudgetPot`/`BudgetField`/`BudgetEntry` (per-application 1:1 binding, `STAGES = requested→reserved→approved→paid`). The tree supersedes most of this. `BudgetEntry.stage` still drives the roll-up.
- `tree_rules.py` — pure, DB-free domain logic (100% branch-covered): path-key composition, descendant tests, fiscal year interval overlap, allocation invariants, `rollup_committed`, `node_available`, `build_forest`, `fiscal_year_bounds`, `scope_forest`.
- `tree_service.py` — thin I/O wiring over `tree_rules` (largest file). CRUD, allocation, assign-budget, book/transfer, invoice parse/store/serve, `revert_audit` dispatcher.
- `tree_router.py` — FastAPI router (`tags=["budget"]`), mounted in `main.py` under `/api`.
- `tree_schemas.py` — Pydantic v2 camelCase DTOs (`_CamelModel`, `populate_by_name`).
- `schemas.py` — shared `_CamelModel` base only.
- `invoice_import.py` — pure ZUGFeRD/Factur-X CII-XML extraction + mapping (`parse_zugferd_pdf`, `NotZugferdError`, `UnsupportedInvoiceCurrencyError`). The module imports `pycheval` and `pypdf` lazily.
- `stats.py` — `BudgetStatsService.refresh()` for materialized views `mv_budget_usage`, `mv_status_distribution`.

**Domain / data model:**
- `budget` — tree node. `parent_id` is a self-FK with `ON DELETE RESTRICT` (NULL = top-level). `key` = path segment (alphanumeric, ≤64, no `-`). `path_key` = composed `VS-800-04`, server-maintained and unique. `key` and the parent stay immutable to keep the path stable. `gremium_id` is set only at top-level. `accepted_state_keys`/`denied_state_keys` (JSONB) classify flow states as bound or excluded. Every other state counts as *requested*. `fully_bound` = the whole subtree allocation counts as committed (available 0). `hidden_in_budget` = display-only filter. The node still rolls up. `view_gremium_id` grants a scoped view of the subtree without global permissions. `fiscal_start_month`/`fiscal_start_day` (top-level only, day 1–28) define the start date of the fiscal year. Currency CHECK = EUR.
- `fiscal_year` — one per top-level budget, identified by `year`. `start_date`/`end_date` follow the start date of the top budget (`start = date(year)`, `end = date(year+1) − 1 day`). Unique `(budget_id, year)`. The intervals must not overlap inside one top-level budget. The display is `YYYY` for a start on 01.01., else `YYYY/YY`.
- `budget_allocation` — top-down `(budget_id, fiscal_year_id, allocated)`. Invariant: Σ children allocated ≤ parent allocated, per fiscal year. **No roll-up** of allocation.
- `budget_expense` — actual booking. `kind = 'expense'` (expended, lowers the budget) or `'income'` (raises available). `application_id` (optional, NOT unique) binds a booking to an application and replaces its committed amount proportionally (`bound = max(0, amount − Σ bound expenses)`). The booking inherits the cost center and the fiscal year from the application. `account_id`, `invoice_id` and `transfer_id` link the bank account, the invoice and the paired transfer row. Metadata: `invoice_date`, `payment_date`, `correspondent`, `note`, `reference_number`, `payment_method` (ueberweisung|bar|lastschrift|karte|paypal), `category`. CHECKs: amount>0, EUR, valid kind and payment_method.
- `account` — free-standing bank account (name + free-text IBAN, no validation). An account is NOT bound to a cost center. A booking may reference one.
- `invoice` — standalone document, 1 invoice : N bookings (`SET NULL` on delete). Fields: number, issue/due dates, supplier, net/tax/gross, `status` open|paid, stored original PDF (`file_object_key`/name/mime in MinIO). EUR + status CHECKs.
- Roll-up rule (R7.1b/c): **allocation flows down, consumption flows up.** Allocation itself never rolls up. `committed = bound + expended`. `available = allocated − bound − expended + income`. The value may go negative, and that is intentional. Nothing clamps it.

**API surface (all principal-only, fail-closed, RBAC server-side):**
- `GET /api/budgets` — cost center forest with `pathKey` and per-fiscal-year allocated/bound/requested/expended/income/committed/available. Full view needs `budget.view`/`structure`/`book`, else the gremium scope of `view_gremium_id` applies.
- `POST/PATCH/DELETE /api/budgets[/{id}]` — node CRUD, `budget.structure`. Delete blocked (409) if children or allocations exist.
- `GET /api/budget/export.xlsx`, `GET /api/expenses/export.xlsx` — `budget.export`.
- `GET /api/budgets/{id}/applications` — applications in the node and its subtree (#17), optional `fiscalYear`.
- `GET/POST /api/budgets/{id}/expenses`, `POST /api/expenses`, `GET /api/expenses` (paged, filtered and sorted), `PATCH/DELETE /api/budget-expenses/{id}` — bookings, `budget.book`. A list read allows any budget permission.
- `POST /api/budget-transfers` — cost center to cost center transfer (expense + income, same fiscal year), `budget.book`.
- `GET/POST/PATCH/DELETE /api/invoices`, `POST /api/invoices/parse` (ZUGFeRD), `POST /api/invoices/file`, `GET /api/invoices/{id}/file` — invoices. Write needs `budget.book`, read needs any budget permission.
- `GET/POST/PATCH/DELETE /api/accounts`, `GET /api/accounts/options` — accounts, `account.manage`. A booker may read the options.
- `GET/POST/PATCH /api/budgets/{id}/fiscal-years[/{fyId}]`, `PUT /api/budgets/{id}/allocations/{fyId}` — `budget.structure`.
- `POST /api/applications/{id}/assign-budget`, `POST /api/applications/{id}/move-fiscal-year` — `application.manage`.

**Conventions & gotchas:**
- CRITICAL module — `budget` requires 100% branch coverage. Keep every decision in `tree_rules.py` (pure) and keep `tree_service.py` as thin DB wiring. Test the rules in isolation.
- EUR only everywhere: DB CHECKs plus `_MAX_AMOUNT = 9999999999.99` `le` guards on input and on invoice import. A too-large amount must return 422, never a numeric-overflow 500.
- The fiscal start day is capped at 1–28 (schema + `is_valid_fiscal_start`) so the start date exists in every month. Otherwise `fiscal_year_bounds` raises `ValueError`, which becomes a 422.
- Allocation invariants raise 422 (`children_allocation_exceeds_parent`, `parent_allocation_below_children`). A fiscal year overlap gives 422. A delete with children or allocations gives 409. All errors use RFC-9457 problem+json.
- The audit log records every money mutation (`AuditAction.BUDGET_*`, see `[[be-audit]]`). `revert_audit` dispatches the revertable actions (`REVERTABLE_BUDGET_ACTIONS`). It deletes an additive operation such as an expense, a transfer or a node create. It restores an update from the audit `data` snapshot. `stale_revert` and `already_reverted` give 409. Deletes are NOT revertable, and that is deliberate (see `[[revert-feature-scope]]`).
- A booking with an `invoice_id` flips that invoice to `paid` in the same transaction. A revert of the booking reopens the invoice.
- Invoice import: `pycheval` is a strict EN16931 validator and fails on real-world PDFs. The module extracts the CII-XML with `pypdf` instead and falls back to the tolerant `_parse_cii_header`. It avoids `dict(reader.attachments)`, because that call decompresses ALL streams and opens a DoS. `extract_facturx_from_pdf` from `pycheval` loops forever on an attachment name other than `factur-x.xml`. The embedded XML is capped at 16 MiB.
- Invoice file serving forces `application/pdf` and `Content-Disposition: attachment`. It ignores a client-supplied `file_mime`, so no PDF polyglot renders in the app origin. The server must issue every file token under the `invoices/` prefix (`_validate_invoice_file_token`). Uploads get a size cap (`body_cap`), a MIME check and a virus scan.
- Never show a raw UUID in the UI. The server resolves `ExpenseOut.actorName`, `applicationTitle` and `accountName` (see `[[no-uuids-in-ui]]`).
- An `income` booking can never link to an application (`ExpenseCreate` validator).

**Related:** be-audit, be-applications, be-admin, be-antiabuse
