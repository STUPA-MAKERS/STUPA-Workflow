---
name: budget-import-zugferd
description: Budget backlog
metadata: 
  node_type: memory
  type: project
---

Backlog #8: support ZUGFeRD (e-invoice) as an **import function for bookings** (expenses).

**Settled design decision (user, 2026-06-13):** the import UX must support **a file drag into the
window**, with a **drop overlay** that appears during the drag. A file-picker button alone is not
enough.

Open: which ZUGFeRD parsing library to use, and how to map the invoice fields onto the
[[budget-kostenstellen-spec]] expense fields ([[antragsplattform-backlog]] cluster). This is a
research-first item (P4). It relates to the expense schema work #1-#4.

**2026-06-13 RESCOPED AND IN PROGRESS** (see [[backlog-2026-06-13]] tasks #13-#18): the item grew
into a full **Invoice entity plus an Invoices tab**, not only an expense pre-fill. Decisions: one
invoice maps to N expenses (`budget_expense.invoice_id` FK SET NULL). The invoice keeps the full
field set plus the stored original file (MinIO). The permissions are budget.view and budget.book.
The library is **pycheval** (PDF and XML, expenses-page style, lightweight, pypdf only). A
non-ZUGFeRD drop opens the manual dialog.
DONE: backend Invoice model and migration 0025 (`31211f0`). Backend invoice CRUD and the
expense-to-invoice link (`436c15c`). **#15 backend ZUGFeRD import**: the pycheval dependency,
`POST /api/invoices/parse` (scan, parse, store, then return the fields and a fileToken),
`POST /invoices` accepts fileToken, fileName and fileMime, `GET /invoices/{id}/file` returns a
signed URL, and delete removes the object. Decisions IMPLEMENTED: pre-fill the dialog and let the
user confirm, do NOT auto-create. Run the AV scan before the store (415 for an infected file, skip
the scan when ClamAV is off). A non-EUR invoice gives 422 `invoice_currency_unsupported`. A
non-ZUGFeRD file gives 422 `invoice_not_zugferd`, and the frontend then opens an empty manual
dialog. Importer: `app/modules/budget/invoice_import.py` (`parse_zugferd_pdf`, `_map`,
`NotZugferdError`, `UnsupportedInvoiceCurrencyError`). The service got the `storage` and `settings`
kwargs. Tests: `tests/test_budget_invoice_import.py`.
TODO: #16 frontend Invoices tab (api, models, route and nav). #17 frontend drag-drop overlay,
import and manual dialog: catch 422 `invoice_not_zugferd` and open an empty dialog, pre-fill from
InvoiceParseResult, and pass the fileToken on POST. #18 frontend expense-to-invoice select. The
CII-to-field mapping lives in `_map`: grand_total→gross, tax_basis→net, Σtax→tax,
invoice_date→issue, payment_terms.due_date→due, seller.name→supplier, invoice_number→number.
