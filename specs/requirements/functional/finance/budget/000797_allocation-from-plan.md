---
id: "000797"
title: The plan in force sets the allocations
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_in_force_writes_the_allocations"
  - "backend/tests/unit/modules/budget/test_plan_rules.py:test_allocations_from_lines"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/plan_rules.py
scope:
  - backend/app/modules/budget
---

# The plan in force sets the allocations

When a version comes into force, the platform must write the allocation of each expense
Kostenstelle from the Ansatz of its line. An income Kostenstelle and a Kostenstelle without a
line must get the allocation 0 €. The top-level Kostenstelle must get the sum of the expense
Ansätze of its direct children.

Reason: The allocation and the approved plan must show the same amounts. An allocation is
money to spend, so an income Ansatz is no allocation.
