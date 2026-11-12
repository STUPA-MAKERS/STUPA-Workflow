---
id: "000819"
title: A draft version can lose a line
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_delete_line"
implementation:
  - backend/app/modules/budget/tree/plans.py
scope:
  - backend/app/modules/budget
---

# A draft version can lose a line

A person with `budget.structure` must remove the line of a Kostenstelle from a version in
`draft`. The platform must answer 422 `plan_line_has_children` while a child Kostenstelle
has a line in that version. The platform must lower no Ansatz of a parent on a removal.
A `PUT` of a line for a Kostenstelle without one must add the Kostenstelle to the version.

Reason: A Kostenstelle that ends leaves the plan of the next year, and a new one enters it.
A parent line without its child stays valid, but a child line without its parent is not.
