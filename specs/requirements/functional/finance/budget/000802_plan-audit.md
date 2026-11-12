---
id: "000802"
title: Each plan state change is audited
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_each_plan_change_is_audited"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/audit/actions.py
scope:
  - backend/app/modules/budget
---

# Each plan state change is audited

The platform must write an audit entry for each new version, each state change of a version
and each change of a line. The entry must name the Haushaltsplan, the version and the actor.

Reason: An examiner must be able to see who changed the plan and when.
