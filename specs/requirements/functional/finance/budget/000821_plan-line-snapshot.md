---
id: "000821"
title: A decided version keeps the name and the key of each line
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_budget_without_steps_goes_from_draft_into_force"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_version_passes_the_steps_of_its_budget"
implementation:
  - backend/app/modules/budget/tree/plans.py
scope:
  - backend/app/modules/budget
---

# A decided version keeps the name and the key of each line

The platform must copy the name and the path key of the Kostenstelle into each line when
a version leaves `draft`. The plan read must show the copied values for a version that left
`draft` and the current values for a `draft` version.

Reason: A later rename of a Kostenstelle must not change the text of a decided plan.

Test: The test renames a Kostenstelle after its version left the draft and reads the plan.
