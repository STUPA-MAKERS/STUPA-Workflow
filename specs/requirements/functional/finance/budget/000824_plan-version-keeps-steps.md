---
id: "000824"
title: A version keeps the steps it started with
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_version_passes_the_steps_of_its_budget"
  - "backend/tests/unit/modules/budget/test_plan_rules.py:test_step_snapshot_and_pass"
  - "backend/tests/unit/modules/budget/test_plan_router.py:test_the_steps_route_needs_its_list"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/plan_rules.py
scope:
  - backend/app/modules/budget
---

# A version keeps the steps it started with

When a version leaves `draft`, the platform must copy the steps of its budget into the
version. A later change of the steps of the budget must not change a version that left
`draft`. The plan read must give the steps of each version with the time of each passed
step, and for a `draft` the steps of the budget. A request that sets the steps of a budget
must name the list, else 422.

Reason: A decided plan is a record of the steps that applied when it was decided.

Test: The tests change the steps of the budget after a version left the draft and read the steps
of the version.
