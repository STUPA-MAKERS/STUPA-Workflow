---
id: "000798"
title: A year with a plan refuses a direct allocation change
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_year_with_a_plan_refuses_a_direct_allocation"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_revert_of_a_first_allocation_respects_the_plan"
implementation:
  - backend/app/modules/budget/tree/allocations.py
  - backend/app/modules/budget/tree/revert.py
scope:
  - backend/app/modules/budget
---

# A year with a plan refuses a direct allocation change

In a fiscal year with a Haushaltsplan, a direct change of an allocation must answer 409
`allocation_from_plan` while the plan switch of the budget is on (000814). The revert of an
allocation change in the audit log must follow the same rule.

Reason: LHO § 33 permits a change of the plan only by a Nachtrag.

Test: The tests set an allocation by hand and revert a first allocation in a year with a plan.
