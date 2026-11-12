---
id: "000820"
title: A Kostenstelle of a decided plan cannot be deleted
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_delete_of_a_cost_centre_in_a_decided_plan"
implementation:
  - backend/app/modules/budget/tree/nodes.py
scope:
  - backend/app/modules/budget
---

# A Kostenstelle of a decided plan cannot be deleted

The platform must answer 409 `budget_in_plan` to the delete of a Kostenstelle that has a
line in a version that left `draft`. A line in a `draft` version must not block the delete,
and the delete must remove that line.

Reason: A decided Haushaltsplan is a record. A Kostenstelle that ends is left out of the
next plan and stays for the years that used it.
