---
id: "000793"
title: Only a draft version can be edited
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_only_a_draft_can_be_edited"
implementation:
  - backend/app/modules/budget/tree/plans.py
scope:
  - backend/app/modules/budget
---

# Only a draft version can be edited

The lines of a plan version must be editable only in the state `draft`. A write to the
lines of a version in a different state must answer 409 `plan_version_locked`.

Reason: A decided version must stay the text that the STUPA decided.
