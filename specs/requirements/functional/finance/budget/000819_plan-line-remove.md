---
id: "000819"
title: A draft version can lose a line
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_delete_line"
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget
---

# A draft version can lose a line

A person with `budget.structure` must remove the line of a Kostenstelle from a version in
`draft`. The platform must answer 422 `plan_line_has_children` while a child Kostenstelle
has a line in that version, and 404 `plan_line_not_found` for a Kostenstelle without a
line. The Ansatz of each parent must follow the removal (000794). A `PUT` of a line for a
Kostenstelle without one must add the Kostenstelle to the version. The plan page must ask
for a confirmation before it removes a line (000840).

Reason: A Kostenstelle that ends leaves the plan of the next year, and a new one enters it.
A parent line without its child stays valid, but a child line without its parent is not.

Test: The test removes a line with and without a child line, removes a missing line and adds a
line again.
