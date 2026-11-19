---
id: "001291"
title: The revert of a booking sets the invoice it paid back to open
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "backend/tests/unit/modules/budget/test_tree_service_cov.py:test_revert_expense_create_reopens_invoice_it_paid"
  - "backend/tests/unit/modules/budget/test_tree_service_cov.py:test_revert_expense_create_keeps_invoice_another_booking_pays"
implementation:
  - backend/app/modules/budget/tree/revert.py
scope:
  - backend/app/modules/budget
---

# The revert of a booking sets the invoice it paid back to open

The revert of a booking must set its invoice back to open when the create of that booking set
the invoice to paid (001290). The invoice must stay paid when another booking still links it.
The audit entry of the create must record that the booking paid the invoice.

Reason: A revert undoes the whole create. Without the reset an invoice stays paid without a
booking.

Test: A unit test reverts a booking that paid its invoice and expects the invoice open.
