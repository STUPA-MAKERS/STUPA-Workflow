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

The platform must write an audit entry for each new version, each deleted version, each
state change of a version, each passed step, each vote created for a step, each change of
the steps of a budget, each change of the plan switch, each change of a side and each
change of a line. The entry must name the Haushaltsplan, the version and the actor. The
entry of a line must hold the Ansatz before and after, the Erläuterung, the Vermerke, the
gesperrt amount and each Ansatz of a parent that the change moved. The entry of a version
that comes into force, and the entry of the plan switch, must hold each allocation that the
plan changed, with the amount before and after. A plan action must not be revertable from
the audit log.

Reason: An examiner must be able to see who changed the plan and when. The plan changes
again by a later version or a Nachtrag, so a revert would make a second way around the
steps.

Test: The test runs each plan action and reads the audit entries and their data.
