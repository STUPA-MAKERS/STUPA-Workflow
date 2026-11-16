---
id: "000801"
title: A closed fiscal year refuses plan changes
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_closed_year_refuses_plan_writes"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_delete_node_keeps_the_draft_of_a_closed_year"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_the_side_of_a_closed_year_does_not_change"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_fiscal_year_with_a_decided_plan_is_not_deleted"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/tree/nodes.py
  - backend/app/modules/budget/tree/fiscal_years.py
scope:
  - backend/app/modules/budget
---

# A closed fiscal year refuses plan changes

In a closed fiscal year, each write to the Haushaltsplan, its versions and its lines must
answer 409 `fiscal_year_closed`. The delete of a Kostenstelle with a line in a draft of a
closed year and the change of a side with a line in a plan of a closed year must answer the
same. An accepted vote must pass no step of a plan of a closed year. The close of a fiscal
year must answer 409 `plan_in_progress` while a version of its plan is in `in_progress`.

Reason: A plan change moves allocations, and a closed year refuses money changes. A
version between its steps would stay open for ever in a closed year.

Test: The tests close a year and call each plan write, the delete of a Kostenstelle with a draft
line and the change of a side. A second test closes a year whose plan is in progress.
