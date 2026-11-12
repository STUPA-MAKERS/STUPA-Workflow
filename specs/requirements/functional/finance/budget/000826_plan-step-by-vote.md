---
id: "000826"
title: An accepted vote of the Gremium passes its step
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_an_accepted_vote_of_the_gremium_passes_its_step"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_refused_vote_leaves_the_step_open"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_vote_passes_only_the_step_it_decides"
  - "backend/tests/unit/modules/budget/test_plan_rules.py:test_step_vote"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/plan_rules.py
  - backend/app/modules/voting/service.py
scope:
  - backend/app/modules/budget
  - backend/app/modules/voting
---

# An accepted vote of the Gremium passes its step

A step that names a Gremium must offer a vote of that Gremium on the plan version. The
platform must record the step as passed when the vote is accepted. The step must keep the
link to the vote. A refused vote must leave the step open.

Reason: The decision of the body is the vote, so the plan must not need a second entry
by hand.
