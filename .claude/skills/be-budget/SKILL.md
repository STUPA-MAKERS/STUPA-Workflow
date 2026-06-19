---
name: be-budget
description: Hierarchical Kostenstellen (cost-centre) budget tree with fiscal years, top-down allocations, bookings (expenses/income), cost-centre transfers, accounts, and ZUGFeRD/Factur-X invoice import — all money mutations audited and revertable. Use when working on Budget, BudgetTreeService, cost centres, fiscal years, allocations, expenses/transfers, accounts, invoices, ZUGFeRD import, /api/budgets, /api/expenses, /api/invoices in backend/app/modules/budget.
---

# Budget tree & bookings — `backend/app/modules/budget`

**Does:** Hierarchical cost-centre (Kostenstellen) budgeting: a budget tree with per-top-level fiscal years, top-down allocations, actual bookings (expenses/income) and transfers, free-standing bank accounts, and invoices importable from ZUGFeRD/Factur-X PDFs. Every money mutation is recorded in the append-only audit log and most are revertable.

**Key files:**
- `tree_models.py` — SQLAlchemy models for the tree: `Budget`, `FiscalYear`, `BudgetAllocation`, `BudgetExpense`, `Account`, `Invoice` (EUR-only, `Numeric(12,2)`).
- `models.py` — legacy flat-pot models `BudgetPot`/`BudgetField`/`BudgetEntry` (per-application 1:1 binding, `STAGES = requested→reserved→approved→paid`). Mostly superseded by the tree; `BudgetEntry.stage` still drives roll-up.
- `tree_rules.py` — pure, DB-free domain logic (100% branch-covered): path-key composition, descendant tests, HHJ interval overlap, allocation invariants, `rollup_committed`, `node_available`, `build_forest`, `fiscal_year_bounds`, `scope_forest`.
- `tree_service.py` — thin I/O wiring over `tree_rules` (largest file). CRUD, allocation, assign-budget, book/transfer, invoice parse/store/serve, `revert_audit` dispatcher.
- `tree_router.py` — FastAPI router (`tags=["budget"]`), mounted in `main.py` under `/api`.
- `tree_schemas.py` — Pydantic v2 camelCase DTOs (`_CamelModel`, `populate_by_name`).
- `schemas.py` — shared `_CamelModel` base only.
- `invoice_import.py` — pure ZUGFeRD/Factur-X CII-XML extraction + mapping (`parse_zugferd_pdf`, `NotZugferdError`, `UnsupportedInvoiceCurrencyError`). `pycheval`/`pypdf` imported lazily.
- `stats.py` — `BudgetStatsService.refresh()` for materialized views `mv_budget_usage`, `mv_status_distribution`.

**Domain / data model:**
- `budget` — tree node. `parent_id` self-FK `ON DELETE RESTRICT` (NULL = top-level); `key` = path segment (alphanumeric, ≤64, no `-`); `path_key` = composed `VS-800-04` (server-maintained, unique; key/parent are immutable for path stability). `gremium_id` only set at top-level. `accepted_state_keys`/`denied_state_keys` (JSONB) classify flow states as bound/excluded — everything else counts as *requested*. `fully_bound` = whole subtree allocation counts as committed (available 0). `hidden_in_budget` = display-only filter (still rolls up). `view_gremium_id` = grants scoped view of the subtree without global perms. `fiscal_start_month`/`fiscal_start_day` (top-level only; day 1–28) define the HHJ start date. Currency CHECK = EUR.
- `fiscal_year` (HHJ) — per top-level budget, identified by `year`; `start_date`/`end_date` derived from the top budget's start date (`start = date(year)`, `end = date(year+1) − 1 day`); unique `(budget_id, year)`; intervals must be disjoint per top-budget. Display `YYYY` (01.01.) else `YYYY/YY`.
- `budget_allocation` — top-down `(budget_id, fiscal_year_id, allocated)`. Invariant: Σ children allocated ≤ parent allocated, per HHJ. **No roll-up** of allocation.
- `budget_expense` — actual booking. `kind = 'expense'` (expended, lowers budget) | `'income'` (raises available). `application_id` (optional, NOT unique) binds a booking to an application, replacing its committed amount proportionally (`bound = max(0, amount − Σ bound expenses)`); inherits cost centre + HHJ from the app. `account_id`, `invoice_id`, `transfer_id` link bank account / invoice / the paired transfer rows. Metadata: `invoice_date`, `payment_date`, `correspondent`, `note`, `reference_number`, `payment_method` (ueberweisung|bar|lastschrift|karte|paypal), `category`. CHECKs: amount>0, EUR, valid kind/payment_method.
- `account` — free-standing bank account (name + free-text IBAN, no validation); NOT bound to cost centres. Optional booking reference.
- `invoice` — standalone document, 1 invoice : N bookings (`SET NULL` on delete). Fields: number, issue/due dates, supplier, net/tax/gross, `status` open|paid, stored original PDF (`file_object_key`/name/mime in MinIO). EUR + status CHECKs.
- Roll-up rule (R7.1b/c): **allocation flows down (top-down, no roll-up); consumption flows up.** `committed = bound + expended`; `available = allocated − bound − expended + income` (may go negative — intentionally unclamped).

**API surface (all principal-only, fail-closed, RBAC server-side):**
- `GET /api/budgets` — cost-centre forest with `pathKey` + per-HHJ allocated/bound/requested/expended/income/committed/available; full view (`budget.view`/`structure`/`book`) or gremium scope (`view_gremium_id`).
- `POST/PATCH/DELETE /api/budgets[/{id}]` — node CRUD, `budget.structure`. Delete blocked (409) if children/allocations exist.
- `GET /api/budget/export.xlsx`, `GET /api/expenses/export.xlsx` — `budget.export`.
- `GET /api/budgets/{id}/applications` — apps in node + subtree (#17), optional `fiscalYear`.
- `GET/POST /api/budgets/{id}/expenses`, `POST /api/expenses`, `GET /api/expenses` (paged+filtered+sorted), `PATCH/DELETE /api/budget-expenses/{id}` — bookings, `budget.book` (list reads allow any budget perm).
- `POST /api/budget-transfers` — cost-centre→cost-centre transfer (expense+income, same HHJ), `budget.book`.
- `GET/POST/PATCH/DELETE /api/invoices`, `POST /api/invoices/parse` (ZUGFeRD), `POST /api/invoices/file`, `GET /api/invoices/{id}/file` — invoices; write = `budget.book`, read = any budget perm.
- `GET/POST/PATCH/DELETE /api/accounts`, `GET /api/accounts/options` — accounts, `account.manage` (options readable by bookers).
- `GET/POST/PATCH /api/budgets/{id}/fiscal-years[/{fyId}]`, `PUT /api/budgets/{id}/allocations/{fyId}` — `budget.structure`.
- `POST /api/applications/{id}/assign-budget`, `POST /api/applications/{id}/move-fiscal-year` — `application.manage`.

**Conventions & gotchas:**
- CRITICAL module — `budget` requires 100% branch coverage. Keep all decisions in `tree_rules.py` (pure) and keep `tree_service.py` as thin DB wiring; test rules in isolation.
- EUR-only everywhere (DB CHECKs + `_MAX_AMOUNT = 9999999999.99` `le` guards on input + invoice import) — a too-large amount must return 422, never a numeric-overflow 500.
- Fiscal start day is capped at 1–28 (schema + `is_valid_fiscal_start`) so the start date exists in every month; `fiscal_year_bounds` raises `ValueError` (→ 422) otherwise.
- Allocation invariants raise 422 (`children_allocation_exceeds_parent`, `parent_allocation_below_children`); HHJ overlap → 422; delete-with-children/allocations → 409. All as RFC-9457 problem+json.
- Every money mutation is audited (`AuditAction.BUDGET_*`, see `[[be-audit]]`). `revert_audit` dispatches revertable actions (`REVERTABLE_BUDGET_ACTIONS`): additive ops (expense/transfer/node create) are deleted; updates restored from the audit `data` snapshot; `stale_revert`/`already_reverted` → 409; deletes are deliberately NOT revertable (see `[[revert-feature-scope]]`).
- Booking an `invoice_id` flips that invoice to `paid` in the same transaction; reverting the booking reopens it.
- Invoice import: `pycheval` is a strict EN16931 validator and chokes on real-world PDFs, so we extract the CII-XML ourselves via `pypdf` (avoiding `dict(reader.attachments)` which decompresses ALL streams — DoS) and fall back to tolerant `_parse_cii_header`. `pycheval`'s `extract_facturx_from_pdf` loops forever on non-`factur-x.xml` attachment names. Embedded XML capped at 16 MiB.
- Invoice file serving forces `application/pdf` + `Content-Disposition: attachment` and ignores client-supplied `file_mime` (no PDF-polyglot render in app origin); file tokens must be server-issued under the `invoices/` prefix (`_validate_invoice_file_token`). Uploads are size-capped (`body_cap`), MIME-validated, and virus-scanned.
- Never show raw UUIDs in the UI: `ExpenseOut.actorName`/`applicationTitle`/`accountName` are resolved server-side (see `[[no-uuids-in-ui]]`).
- `income` bookings can never be linked to an application (`ExpenseCreate` validator).

**Related:** be-audit, be-applications, be-admin, be-antiabuse
