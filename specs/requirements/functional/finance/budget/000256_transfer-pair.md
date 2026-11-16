---
id: "000256"
title: A transfer is a pair of bookings
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/unit/modules/budget/test_tree_service_cov.py:test_update_of_one_transfer_leg_409"
implementation:
  - backend/app/modules/budget/tree/transfers.py
  - backend/app/modules/budget/tree/expenses.py
scope:
  - backend/app/modules/budget
---

# A transfer is a pair of bookings

A transfer between two cost centres must write an expense and an income in the same fiscal
year. The amount and the cost centre of one of the two bookings must not change alone: the
change of a booking answers 409 `transfer_leg_fixed`, and the change of the transfer changes
both bookings at once.
