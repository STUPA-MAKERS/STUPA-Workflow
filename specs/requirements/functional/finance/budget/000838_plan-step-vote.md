---
id: "000838"
title: The vote of a plan step is a vote of its Gremium
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_an_accepted_vote_of_the_gremium_passes_its_step"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_step_of_a_deleted_gremium_takes_no_vote"
  - "backend/tests/unit/modules/budget/test_plan_rules.py:test_step_vote_config_and_question"
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
  - "frontend/src/app/features/voting/vote-cast.component.spec.ts:VoteCastComponent"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/plan_rules.py
  - backend/app/modules/budget/plan_router.py
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
  - frontend/src/app/features/voting/vote-cast.component.ts
scope:
  - backend/app/modules/budget
  - backend/app/modules/voting
  - frontend/src/app/pages/budget
  - frontend/src/app/features/voting
---

# The vote of a plan step is a vote of its Gremium

A person with `budget.structure` must create the vote of the next step of a version
(`POST /budget-plan-versions/{id}/steps/next/vote`). The vote must start as a draft vote of
the Gremium of the step, without a meeting and without an Antrag. Its question must name
the budget, the fiscal year, the version and the step. It must be secret, use the simple
majority, count a tie as refused and use the quorum of the Gremium. A draft version must
leave the draft with this request (000792). A step without a Gremium must answer 422
`plan_step_no_gremium`, and a step whose vote is a draft or open must answer 409
`plan_step_vote_runs`.

The vote must open and close only through the vote routes, with the right of that Gremium
to manage votes. The plan page must link to the vote. The vote page must show a link to
the plan to a person who can read the plan (000800), and to no other person.

Reason: The person who manages the plan asks the body for its decision, and the body
decides with its own rights. The vote of a plan follows the same rules as each vote of the
Gremium.

Test: The backend tests create the vote of a step with and without a Gremium, a second vote
beside a running one, and read the config and the question. The vote page tests read the link to
the plan with and without the read right.
