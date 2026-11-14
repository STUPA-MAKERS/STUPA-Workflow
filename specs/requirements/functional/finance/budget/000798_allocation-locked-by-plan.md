---
id: "000798"
title: A year with a plan in force refuses a direct allocation change
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_year_with_a_plan_in_force_refuses_a_direct_allocation"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_revert_of_a_first_allocation_respects_the_plan"
implementation:
  - backend/app/modules/budget/tree/allocations.py
  - backend/app/modules/budget/tree/revert.py
scope:
  - backend/app/modules/budget
---

# A year with a plan in force refuses a direct allocation change

In a fiscal year whose Haushaltsplan has a version in force, a direct change of an allocation
must answer 409 `allocation_from_plan` while the plan switch of the budget is on (000814). A
year whose plan has no version in force yet must take the change (000854). The revert of an
allocation change in the audit log must follow the same rule.

Reason: LHO § 33 permits a change of the plan only by a Nachtrag.

Test: The tests set an allocation by hand before and after a version is in force, and revert a
first allocation in a year with a plan in force.
