---
id: "000830"
title: A Kostenstelle created in a draft gets a line
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_create_a_cost_centre_in_a_draft"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_two_creates_of_one_key_answer_a_conflict"
implementation:
  - backend/app/modules/budget/tree/plans.py
scope:
  - backend/app/modules/budget
---

# A Kostenstelle created in a draft gets a line

`POST /budget-plan-versions/{id}/cost-centres` must create a Kostenstelle and its line
in the draft version in one request. The body must hold the parent, the key, the name, the
Ansatz and, for a direct child of the budget, the side. A failed request must leave no
Kostenstelle and no line. The request must answer 409 `plan_version_locked` for a
version that is not a draft. The request needs `budget.structure`.

Reason: A Kostenstelle without a line is no part of the plan of the year (000818), so the
person would not see what was created.

Test: The test creates a Kostenstelle in a draft, in a decided version, with a key that exists
and without a side.
