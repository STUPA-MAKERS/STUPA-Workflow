---
id: "000800"
title: A plan write needs budget.structure
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/unit/modules/budget/test_plan_router.py:test_write_route_needs_budget_structure"
  - "backend/tests/unit/modules/budget/test_plan_router.py:test_get_plan_follows_the_read_rule_of_the_cost_centre"
implementation:
  - backend/app/modules/budget/plan_router.py
scope:
  - backend/app/modules/budget
---

# A plan write needs budget.structure

Each write to a Haushaltsplan, a version or a line must need the permission
`budget.structure`. A read must follow the read rule of the Kostenstelle.

Reason: The persons who manage the Kostenstellen and the fiscal years also write the plan.
