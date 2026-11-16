---
id: "001032"
title: A booking takes only a Kostenstelle without a Kostenstelle below it
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_booking_is_not_made_on_a_cost_centre_with_children"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_transfer_is_not_made_on_a_cost_centre_with_children"
  - "frontend/src/app/pages/budget/cost-centre-select/cost-centre-select.component.spec.ts:CostCentreSelectComponent"
implementation:
  - backend/app/modules/budget/tree/service_base.py
  - backend/app/modules/budget/tree/expenses.py
  - backend/app/modules/budget/tree/transfers.py
  - frontend/src/app/pages/expenses/booking-form/booking-form.component.html
  - frontend/src/app/pages/expenses/transfer-form/transfer-form.component.html
  - frontend/src/app/pages/expenses/bulk-panel/bulk-panel.component.html
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/expenses
---

# A booking takes only a Kostenstelle without a Kostenstelle below it

A new booking, a booking that moves to another Kostenstelle and each leg of a transfer
must take only a leaf: a Kostenstelle that has no active Kostenstelle below it (001031). A
booking can be an expense or an income, so an income Kostenstelle stays choosable.

- The booking form (also from an invoice), the move of a booking, the bulk move and the
  transfer form must show the tree as before, with a node that is no leaf as not choosable
  (001031).
- The server must refuse such a booking, move or transfer with 422 `cost_centre_not_leaf`.
- A booking for an Antrag takes the Kostenstelle of the Antrag, also when the Antrag keeps a
  Kostenstelle that is no leaf (001031), because the Antrag decides where it is booked.
- A sub-booking takes the Kostenstelle of its booking.

A booking that already sits on a Kostenstelle with Kostenstellen below it must keep it and
stay readable, and a change of its other fields must work. The filter "Kostenstelle" of the
booking list must still offer every Kostenstelle.

Reason: The Ist of a Haushalt must come from the Kostenstellen where money is spent or comes
in. A booking on a Titel or a Haushalt with Kostenstellen below it does not say which of
them it belongs to.

Test: Integration tests: a booking, a move and a transfer on a node with children are
refused, on a leaf they are taken, an income booking on a leaf of an income Titel is taken.
Component test: the picker shows a node with children as not choosable.
