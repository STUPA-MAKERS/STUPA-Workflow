---
name: budget-import-zugferd
description: Budget backlog
metadata: 
  node_type: memory
  type: project
---

Backlog #8: support ZUGFeRD (e-invoice) as an **import function for Buchungen** (expenses).

**Settled design decision (user, 2026-06-13):** import UX must support **dragging the file into the window** with a **drop-overlay** appearing while dragging. Not just a file-picker button.

Open: which ZUGFeRD parsing library, mapping of invoice fields → [[budget-kostenstellen-spec]] expense fields ([[antragsplattform-backlog]] cluster). Research-first item (P4). Relates to expense schema work #1–#4.

**2026-06-13 RESCOPED + IN PROGRESS** (see [[backlog-2026-06-13]] tasks #13–#18): became a full **Invoice entity + Invoices tab**, not just an expense prefill. Decisions: 1 invoice : N expenses (`budget_expense.invoice_id` FK SET NULL); full invoice fields + stored original file (MinIO); perms budget.view/book; lib = **pycheval** (PDF+XML, expenses-page style, lightweight pypdf-only); non-ZUGFeRD drop → manual dialog.
DONE: BE Invoice model + migration 0025 (`31211f0`); BE invoice CRUD + expense↔invoice link (`436c15c`); **#15 BE ZUGFeRD import** — pycheval dep, `POST /api/invoices/parse` (scan→parse→store→return fields+fileToken), `POST /invoices` accepts fileToken/fileName/fileMime, `GET /invoices/{id}/file` signed URL, delete removes object. Decisions IMPLEMENTED: prefill-dialog-then-confirm (NOT auto-create); AV-scan before store (415 infected, skip if ClamAV off); non-EUR→422 `invoice_currency_unsupported`; non-ZUGFeRD→422 `invoice_not_zugferd` (FE opens empty manual dialog). Importer: `app/modules/budget/invoice_import.py` (`parse_zugferd_pdf`, `_map`, `NotZugferdError`, `UnsupportedInvoiceCurrencyError`). Service got `storage`+`settings` kwargs. Tests: `tests/test_budget_invoice_import.py`.
TODO: #16 FE Invoices tab (api+models+route/nav), #17 FE drag-drop overlay + import + manual dialog (catch 422 invoice_not_zugferd → empty dialog; prefill from InvoiceParseResult, pass fileToken on POST), #18 FE expense↔invoice select. CII→fields mapping done in `_map`: grand_total→gross, tax_basis→net, Σtax→tax, invoice_date→issue, payment_terms.due_date→due, seller.name→supplier, invoice_number→number.
