---
id: "003021"
title: A list by month sorts by the same date that its month headings read
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
tests:
  - "backend/tests/integration/modules/budget/test_invoice_list_order.py:test_undated_invoice_sorts_by_its_entry_day"
  - "frontend/src/app/pages/expenses/expenses.component.spec.ts:ExpensesComponent"
implementation:
  - backend/app/modules/budget/tree/invoices.py
  - backend/app/modules/budget/tree/expenses.py
  - backend/app/modules/budget/tree/transfers.py
  - backend/app/modules/budget/tree/service_base.py
  - frontend/src/app/pages/expenses/expense-transfers.state.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/invoices
  - frontend/src/app/pages/expenses
---

# A list by month sorts by the same date that its month headings read

A list that shows month headings must sort its rows by exactly the date that puts a row
under its heading. The server must use the same fallback as the frontend: the invoice list
sorts newest first by the invoice date, and an invoice without an invoice date sorts by the
day it was entered. The bookings sorted by payment date and the transfers sort the same way:
the payment date, and without one the day of the entry. Rows with the same date must sort by
the time of the entry, newest first, and then by the id, so that the pages of an infinite
scroll do not overlap or skip a row. Each month must then appear exactly once.

Reason: The invoice list sorted by the invoice date with the rows without one at the end,
but grouped those rows by the day of the entry. So "November 2026" came after "Februar 2026",
and a page boundary could split one month into two headings.

Test: A backend test lists invoices with and without an invoice date and checks the order
over one page and over several pages. A frontend test checks that the transfer list asks for
the sort by payment date.
