---
id: "000796"
title: One version of a plan is in force
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_nachtrag"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/plan_models.py
scope:
  - backend/app/modules/budget
---

# One version of a plan is in force

A Haushaltsplan must have at most one version in the state `in_force`. When a version
comes into force, the platform must set the earlier version in force to `replaced`.

Reason: Only one plan applies at one time.
