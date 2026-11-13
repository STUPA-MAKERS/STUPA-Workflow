---
id: "000791"
title: A fiscal year has one Haushaltsplan with versions
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_create_plan"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/plan_models.py
scope:
  - backend/app/modules/budget
---

# A fiscal year has one Haushaltsplan with versions

A fiscal year must have at most one Haushaltsplan. A Haushaltsplan must have one or more
versions with the numbers 0, 1, 2 and so on. Version 0 is the Stammplan. Each later version
is a Nachtrag.

Reason: LHO § 33 lets a Nachtrag change the plan, and the earlier plan must stay readable.

Test: The test creates the plan of a year twice and reads the version numbers.
