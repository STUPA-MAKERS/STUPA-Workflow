---
id: "000839"
title: A version back in draft ends the votes of its steps
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_back_to_draft_ends_the_votes_of_the_version"
implementation:
  - backend/app/modules/budget/tree/plans.py
scope:
  - backend/app/modules/budget
  - backend/app/modules/voting
---

# A version back in draft ends the votes of its steps

When a version moves back to `draft`, the platform must delete each draft vote of its steps
and cancel each open vote of its steps. A closed vote must stay.

Reason: A draft can change, so a body must not decide on a text that is no longer the
plan. A closed vote is a record of a decision.

Test: The test moves a version with a draft vote and a version with an open vote back to draft
and reads the votes.
