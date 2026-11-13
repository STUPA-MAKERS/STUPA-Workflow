---
id: "000800"
title: A plan write needs budget.structure
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/unit/modules/budget/test_plan_router.py:test_write_route_needs_budget_structure"
  - "backend/tests/unit/modules/budget/test_plan_router.py:test_get_plan_follows_the_read_rule_of_the_cost_centre"
  - "backend/tests/unit/modules/budget/test_plan_router.py:test_the_plan_of_a_version_follows_the_read_rule_of_its_budget"
implementation:
  - backend/app/modules/budget/plan_router.py
scope:
  - backend/app/modules/budget
---

# A plan write needs budget.structure

Each write to a Haushaltsplan, a version, a line, the steps, the plan switch or a side must
need the permission `budget.structure`. A read of a Haushaltsplan, by its fiscal year or by
one of its versions, and a read of the steps must follow the read rule of the top-level
Kostenstelle of the plan: a person who can see that Kostenstelle can read its plan.

Reason: The persons who manage the Kostenstellen and the fiscal years also write the plan.
The plan shows each Kostenstelle of the budget, so it follows the view of the whole budget
and not the view of one Kostenstelle below it.

Test: The router tests call each write route without `budget.structure` and each read route with
and without the view of the budget.
