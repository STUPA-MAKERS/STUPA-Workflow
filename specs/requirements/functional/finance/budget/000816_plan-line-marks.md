---
id: "000816"
title: A plan line of an expense holds the Vermerke
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_set_line_checks_the_node_and_the_marks"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_an_income_side_takes_the_vermerke_off_the_draft_line"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_decided_version_keeps_the_side_of_its_titel"
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
implementation:
  - backend/app/modules/budget/tree/plans.py
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
  - frontend/src/app/pages/budget/cost-centre/cost-centre-settings.component.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget
---

# A plan line of an expense holds the Vermerke

A plan line of an expense Kostenstelle must hold the Vermerke "übertragbar" and
"deckungsfähig" as yes or no and a gesperrt amount from 0 € to the Ansatz, else 422
`plan_blocked_above_amount`. A line of an income Kostenstelle must not hold a Vermerk, else
422 `plan_marks_income`. When the line of a Titel gets the side income in a draft (000853),
the platform must take the Vermerke and the gesperrt amount off the lines of that Titel and
of each Kostenstelle below it in that draft. A version that left `draft` keeps its sides
and its Vermerke. The plan page must show the lines as the answer of the change gives
them, so it shows no Vermerk that the platform took off, and the open line must stay open.

Reason: A decided version is a record, so a side must not make its Vermerke wrong. LHO § 19,
§ 20 and § 22 name these Vermerke as a part of the plan. The plan shows them before the
platform applies them.

Test: The test sets the Vermerke of an expense line and of an income line, and a gesperrt
amount above the Ansatz, and sets the side of a Titel with Vermerke to income, in a draft
and in a decided version. The page test changes the side of an open line and reads the
Vermerke.
