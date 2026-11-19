---
id: "001290"
title: A new booking sets its invoice to paid
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "backend/tests/unit/modules/budget/test_tree_service_cov.py:test_book_expense_pays_open_invoice"
  - "backend/tests/unit/modules/budget/test_tree_service_cov.py:test_book_expense_paid_invoice_stays_paid"
implementation:
  - backend/app/modules/budget/tree/expenses.py
scope:
  - backend/app/modules/budget
---

# A new booking sets its invoice to paid

The create of a booking with an invoice must set that invoice to "Bezahlt". An invoice that is
already "Bezahlt" must stay as it is. The edit of a booking must not change the status of its
invoice. A person can set the invoice back to open with "Bearbeiten".

Reason: A booking from an invoice records the payment. The invoice stayed open, and the person
had to mark it paid as a second step.

Test: A unit test books an expense with an open invoice and expects the invoice paid.
