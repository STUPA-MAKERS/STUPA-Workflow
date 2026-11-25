---
id: "003021"
title: A row without the date of its list goes to its own group, not to its entry month
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
tests:
  - "backend/tests/integration/modules/budget/test_invoice_list_order.py:test_undated_invoices_come_last"
  - "frontend/src/app/pages/invoices/invoices.component.spec.ts:InvoicesComponent"
  - "frontend/src/app/shared/group-by-month.spec.ts:groupByMonth"
  - "frontend/src/app/pages/expenses/expenses.component.spec.ts:ExpensesComponent"
implementation:
  - backend/app/modules/budget/tree/invoices.py
  - backend/app/modules/budget/tree/expenses.py
  - backend/app/modules/budget/tree/transfers.py
  - frontend/src/app/shared/group-by-month.ts
  - frontend/src/app/pages/invoices/invoices.component.ts
  - frontend/src/app/pages/expenses/expenses.component.ts
  - frontend/src/app/pages/expenses/expense-transfers.state.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/invoices
  - frontend/src/app/pages/expenses
  - frontend/src/app/shared
---

# A row without the date of its list goes to its own group, not to its entry month

A list with month headings must put a row under the month of the date it sorts by, and of
no other date. A row without that date must not take the day of its entry instead. The rows
without it must come last and stand under one heading of their own: "Ohne Rechnungsdatum" in
the invoice list and in the bookings sorted by invoice date, "Ohne Zahlungsdatum" in the
bookings sorted by payment date and in the transfers. The transfers must sort by the payment
date, the date of their headings. Rows with the same date must sort by the time of the entry,
newest first, and then by the id, so that the pages of an infinite scroll do not overlap or
skip a row.

Reason: The invoice list put the invoices without an invoice date at the end but under the
month of their entry, so "November 2026" came after "Februar 2026". The day of the entry is
not the date of an invoice or of a payment.

Test: A backend test lists invoices with and without an invoice date and checks the order
over one page and over several pages. Frontend tests check the heading "Ohne Rechnungsdatum"
after the months and the sort of the transfer list.
