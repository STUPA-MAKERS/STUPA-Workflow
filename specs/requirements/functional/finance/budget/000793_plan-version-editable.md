---
id: "000793"
title: Only a draft version can be edited
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_only_a_draft_can_be_edited"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_create_a_cost_centre_in_a_draft"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_draft_version_is_deleted"
implementation:
  - backend/app/modules/budget/tree/plans.py
scope:
  - backend/app/modules/budget
---

# Only a draft version can be edited

The lines of a plan version must be editable only in the state `draft`. Each write to a
version in a different state must answer 409 `plan_version_locked`: the write of a line,
the removal of a line, the create of a Kostenstelle in the version (000830) and the delete
of the version (000835). The platform must read the state again after it holds the lock of
the plan, so a write that waited for another write sees the state that write left.

Reason: A decided version must stay the text that the STUPA decided.

Test: The test writes a line, removes a line, creates a Kostenstelle and deletes the version
after the version left the draft.
