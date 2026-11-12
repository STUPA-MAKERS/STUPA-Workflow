---
id: "000821"
title: A decided version keeps the name and the key of each line
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_state_moves_and_balance"
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
